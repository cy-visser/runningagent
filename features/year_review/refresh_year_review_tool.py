"""Internal zero-LLM tool for computing and caching Calendar-Year Annual Reviews in Firestore."""

from __future__ import annotations

import asyncio
from datetime import date
import json
import logging
from typing import Any, Awaitable, Callable, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations import firestore
from ...integrations.trainingpeaks import tp_calls
from ...shared.athlete_settings import extract_hr_zones, extract_thresholds
from ...shared.dates import get_now_utc, get_today_date, iso_date
from ...shared.parallel_fetch import gather_labeled
from ...shared.runner_identity import profile_user_id
from ...shared.tp_payloads import coerce_mcp_payload
from .helpers.aggregation import aggregate_year, calendar_year_window
from .helpers.fitness_progress import (
    PEAK_DISTANCES,
    compute_fitness_shift,
    format_peak_performances,
)
from .helpers.incremental import (
    build_raw_snapshot,
    compact_race_detail,
    deserialize_daily_pmc,
    deserialize_health,
    merge_daily_pmc,
    merge_events,
    merge_health,
    merge_workouts,
    plan_fetch_window,
)
from .helpers.payload import (
    YEAR_REVIEW_VERSION,
    build_year_index_entry,
    build_year_review_payload,
)
from .helpers.races import detect_main_races, enrich_races_with_details

logger = logging.getLogger(__name__)

PEAKS_CONCURRENCY = 3
RACE_DETAIL_CONCURRENCY = 3


async def _safe_fetch_events(
    fetch_events_fn: Callable[[date, date], Awaitable[list[dict[str, Any]]]],
    start: date,
    end: date,
) -> Optional[list[dict[str, Any]]]:
    try:
        return await fetch_events_fn(start, end)
    except Exception as exc:
        logger.warning("Best-effort tp_get_events failed during annual review: %s", exc)
        return None


async def _safe_fetch_peaks(
    fetch_peak_fn: Callable[[str, str, str], Awaitable[Any]],
    start_iso: str,
    end_iso: str,
) -> dict[str, dict[str, Any]]:
    sem = asyncio.Semaphore(PEAKS_CONCURRENCY)

    async def _one(pr_type: str) -> tuple[str, dict[str, Any]]:
        async with sem:
            try:
                raw = await fetch_peak_fn(pr_type, start_iso, end_iso)
                return pr_type, coerce_mcp_payload(raw) if raw else {}
            except Exception as exc:
                logger.debug("Ignoring tp_get_peaks(%s, %s..%s) failure: %s", pr_type, start_iso, end_iso, exc)
                return pr_type, {}

    results = await asyncio.gather(*(_one(pr_type) for pr_type, _, _, _ in PEAK_DISTANCES))
    return dict(results)


async def _fetch_race_details(
    fetch_workout_fn: Callable[[str], Awaitable[Any]],
    workout_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not workout_ids:
        return {}
    sem = asyncio.Semaphore(RACE_DETAIL_CONCURRENCY)

    async def _one(wid: str) -> tuple[str, dict[str, Any]]:
        async with sem:
            try:
                raw = await fetch_workout_fn(wid)
                parsed = coerce_mcp_payload(raw) if raw else {}
                return wid, {} if parsed.get("isError") else parsed
            except Exception as exc:
                logger.debug("Ignoring tp_get_workout(%s) race enrichment failure: %s", wid, exc)
                return wid, {}

    results = await asyncio.gather(*(_one(wid) for wid in workout_ids))
    return {wid: data for wid, data in results if data}


async def compile_and_cache_annual_review(
    *,
    user_id: str,
    profile: dict[str, Any],
    year: int,
    today: date,
    force_full: bool,
    fetch_workouts_fn: Callable[[date, date], Awaitable[list[dict[str, Any]]]],
    fetch_events_fn: Callable[[date, date], Awaitable[list[dict[str, Any]]]],
    fetch_health_fn: Callable[[date, date], Awaitable[dict[str, Any]]],
    fetch_fitness_fn: Callable[[str, str], Awaitable[Any]],
    fetch_settings_fn: Callable[[], Awaitable[Any]],
    fetch_peak_fn: Callable[[str, str, str], Awaitable[Any]],
    fetch_workout_fn: Callable[[str], Awaitable[Any]],
) -> dict[str, Any]:
    """Computes and persists `year_review_{year}`, `year_review_raw_{year}`, and `year_review_index`.

    Shared by the zero-LLM ADK quick action tool and the standalone historical backfill script.
    """
    start, end, is_complete = calendar_year_window(year, today)
    start_iso, end_iso = iso_date(start), iso_date(end)

    raw_cache = await firestore.get_cached_year_review_raw(user_id, year)
    mode, fetch_start, fetch_end = plan_fetch_window(
        raw_cache,
        year=year,
        start=start,
        end=end,
        is_complete=is_complete,
        force_full=force_full,
    )

    if mode == "cached":
        existing = await firestore.get_cached_year_review(user_id, year)
        if isinstance(existing, dict) and existing.get("version") == YEAR_REVIEW_VERSION:
            await firestore.upsert_year_review_index(user_id, build_year_index_entry(existing))
            total_w = int((existing.get("kpis") or {}).get("total_workouts") or 0)
            return {
                "status": "ready" if total_w > 0 else "empty",
                "year": year,
                "mode": "cached",
                "is_complete": True,
                "workouts": total_w,
                "races": len(existing.get("races") or []),
            }
        # Computed doc missing or older schema: recompute cleanly from cached raw or full fetch.
        mode, fetch_start, fetch_end = "full", start, end

    assert fetch_start is not None and fetch_end is not None
    is_incremental = mode == "incremental" and isinstance(raw_cache, dict)
    fetch_start_iso, fetch_end_iso = iso_date(fetch_start), iso_date(fetch_end)

    fetches: dict[str, Any] = {
        "workouts": fetch_workouts_fn(fetch_start, fetch_end),
        "fitness": fetch_fitness_fn(fetch_start_iso, fetch_end_iso),
        "events": _safe_fetch_events(fetch_events_fn, fetch_start, fetch_end),
        "health": fetch_health_fn(fetch_start, fetch_end),
        "athlete_settings": fetch_settings_fn(),
        "records": firestore.list_training_records(user_id, start_iso, end_iso),
        "peaks": _safe_fetch_peaks(fetch_peak_fn, start_iso, end_iso),
    }
    raw = await gather_labeled(fetches)

    fresh_workouts = raw.get("workouts") or []
    fresh_events = raw.get("events")  # None on transient error, list otherwise
    fresh_health = raw.get("health") or {}
    fresh_pmc = coerce_mcp_payload(raw["fitness"]).get("daily_data") or [] if raw.get("fitness") else []
    fresh_peaks = raw.get("peaks") or {}

    if is_incremental:
        workouts = merge_workouts(
            raw_cache.get("workouts") or [],
            fresh_workouts,
            window_start=start,
            delta_start=fetch_start,
            end=end,
        )
        events = merge_events(
            raw_cache.get("events") or [],
            fresh_events,
            window_start=start,
            delta_start=fetch_start,
            end=end,
        )
        dated_metrics = merge_health(
            deserialize_health(raw_cache.get("health")),
            fresh_health,
            window_start=start,
            delta_start=fetch_start,
            end=end,
        )
        daily_pmc = merge_daily_pmc(
            deserialize_daily_pmc(raw_cache.get("daily_pmc")),
            fresh_pmc,
            window_start=start,
            delta_start=fetch_start,
            end=end,
        )
        cached_race_details: dict[str, dict[str, Any]] = dict(raw_cache.get("race_details") or {})
    else:
        workouts = merge_workouts([], fresh_workouts, window_start=start, delta_start=start, end=end)
        events = merge_events([], fresh_events or [], window_start=start, delta_start=start, end=end)
        dated_metrics = merge_health({}, fresh_health, window_start=start, delta_start=start, end=end)
        daily_pmc = merge_daily_pmc([], fresh_pmc, window_start=start, delta_start=start, end=end)
        cached_race_details = {}

    records = raw.get("records") or []
    thresholds = extract_thresholds(raw.get("athlete_settings"))
    zones = extract_hr_zones(raw.get("athlete_settings"))
    lthr = thresholds.get("lthr")
    lt1_hr = zones[1]["max"] if len(zones) >= 2 else None

    peaks = format_peak_performances(fresh_peaks, profile, start, end)
    races, unlogged_race_ids = detect_main_races(
        profile=profile,
        workouts=workouts,
        records=records,
        events=events,
        daily_pmc=daily_pmc,
        start=start,
        today=end,
        lthr=lthr,
    )

    missing_detail_ids = [wid for wid in unlogged_race_ids if wid not in cached_race_details]
    if missing_detail_ids:
        fetched_details = await _fetch_race_details(fetch_workout_fn, missing_detail_ids)
        for wid, detail in fetched_details.items():
            cached_race_details[wid] = compact_race_detail(detail)
    if cached_race_details:
        enrich_races_with_details(races, cached_race_details, lthr=lthr)

    aggregated = aggregate_year(
        year=year,
        workouts=workouts,
        records=records,
        daily_pmc=daily_pmc,
        races=races,
        start=start,
        end=end,
        is_complete=is_complete,
    )
    fitness_shift = compute_fitness_shift(
        records=records,
        weekly=aggregated["weekly"],
        dated_metrics=dated_metrics,
        start=start,
        today=end,
        lthr=lthr,
        lt1_hr=lt1_hr,
    )
    runner_name = (
        f"{profile.get('firstname') or ''} {profile.get('lastname') or ''}".strip()
        or str(profile.get("email") or "Runner")
    )
    payload = build_year_review_payload(
        now=get_now_utc(),
        year=year,
        start=start,
        end=end,
        is_complete=is_complete,
        runner_name=runner_name,
        aggregated=aggregated,
        races=races,
        fitness_shift=fitness_shift,
        peaks=peaks,
        sync_mode=mode,
    )
    raw_snapshot = build_raw_snapshot(
        year=year,
        window_start=start,
        end=end,
        is_complete=is_complete,
        workouts=workouts,
        events=events,
        dated_metrics=dated_metrics,
        daily_pmc=daily_pmc,
        race_details=cached_race_details,
    )
    await asyncio.gather(
        firestore.save_year_review(user_id, year, payload),
        firestore.save_year_review_raw(user_id, year, raw_snapshot),
        firestore.upsert_year_review_index(user_id, build_year_index_entry(payload)),
    )
    status = "ready" if payload["kpis"]["total_workouts"] > 0 else "empty"
    return {
        "status": status,
        "year": year,
        "mode": mode,
        "is_complete": is_complete,
        "workouts": payload["kpis"]["total_workouts"],
        "races": len(payload["races"]),
    }


async def refresh_year_review(
    tool_context: ToolContext,
    year: Optional[int] = None,
    force_full: bool = False,
) -> str:
    """Computes a calendar-year Annual Review (Jan 1 – Dec 31) incrementally or full and persists it to Firestore."""
    tool_context.actions.skip_summarization = True
    profile = tool_context.state.get("user_profile") or {}
    user_id = profile_user_id(profile)
    if not user_id:
        return json.dumps({"status": "no_profile"})

    today = get_today_date()
    target_year = int(year) if year is not None else today.year
    if target_year < 2000 or target_year > today.year:
        return json.dumps({"status": "invalid_year", "year": target_year})

    result = await compile_and_cache_annual_review(
        user_id=user_id,
        profile=profile,
        year=target_year,
        today=today,
        force_full=bool(force_full),
        fetch_workouts_fn=lambda s, e: tp_calls.fetch_workouts(tool_context, s, e),
        fetch_events_fn=lambda s, e: tp_calls.fetch_events(tool_context, s, e),
        fetch_health_fn=lambda s, e: tp_calls.fetch_metrics_range(tool_context, s, e),
        fetch_fitness_fn=lambda s, e: tp_calls.run_tp_tool(
            tool_context, "tp_get_fitness", start_date=s, end_date=e
        ),
        fetch_settings_fn=lambda: tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
        fetch_peak_fn=lambda pr_type, s, e: tp_calls.run_tp_tool(
            tool_context, "tp_get_peaks", sport="Run", pr_type=pr_type, start_date=s, end_date=e
        ),
        fetch_workout_fn=lambda wid: tp_calls.run_tp_tool(tool_context, "tp_get_workout", workout_id=wid),
    )
    return json.dumps(result)


refresh_year_review_tool = FunctionTool(refresh_year_review)
