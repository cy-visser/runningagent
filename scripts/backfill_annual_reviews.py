#!/usr/bin/env python3
"""One-off historical backfill CLI for Calendar-Year Annual Reviews (default: 2023–2025).

Populates `users/{runner_id}/cache/year_review_{YYYY}`, `year_review_raw_{YYYY}`, and
`year_review_index` in Firestore using the exact same `compile_and_cache_annual_review`
pipeline as the web app, with date-bounded `tp_get_peaks` (tp_mcp >= 2.3.0).

Usage (dry run first):
    /usr/local/google/home/cyvisser/source/venv/bin/python scripts/backfill_annual_reviews.py \
        --runner-id cyrille_visser --from-year 2023 --to-year 2025 --dry-run

Live run (after manually adding historical TrainingPeaks Events):
    /usr/local/google/home/cyvisser/source/venv/bin/python scripts/backfill_annual_reviews.py \
        --runner-id cyrille_visser --from-year 2023 --to-year 2025
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import logging
import os
import sys
from typing import Any, Optional

from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_PARENT = os.path.dirname(REPO_ROOT)
if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from running_coach.features.year_review.helpers.aggregation import calendar_year_window
from running_coach.features.year_review.refresh_year_review_tool import (
    compile_and_cache_annual_review,
)
from running_coach.integrations import firestore
from running_coach.integrations.trainingpeaks import credentials, tp_calls
from running_coach.shared.dates import get_today_date
from running_coach.shared.health_metrics import extract_health_metrics_dated

logger = logging.getLogger("backfill_annual_reviews")


def resolve_target_years(
    *,
    years: Optional[list[int]] = None,
    from_year: int = 2023,
    to_year: int = 2025,
    today: Optional[date] = None,
) -> list[int]:
    """Returns deduplicated valid calendar years sorted latest-first (e.g. [2025, 2024, 2023])."""
    max_year = (today or get_today_date()).year
    raw = list(years) if years else list(range(from_year, to_year + 1))
    valid = sorted({int(y) for y in raw if 2000 <= int(y) <= max_year}, reverse=True)
    if not valid:
        raise ValueError(f"No valid years in range 2000..{max_year} (got {raw!r}).")
    return valid


async def _fetch_chunked_tp(fetch_chunk_fn: Any, key: str, start: date, end: date) -> list[dict[str, Any]]:
    chunks = tp_calls.date_chunks(start, end)
    merged: dict[str, dict[str, Any]] = {}
    for s_iso, e_iso in chunks:
        payload = await fetch_chunk_fn(s_iso, e_iso)
        if not isinstance(payload, dict):
            continue
        if payload.get("isError"):
            raise RuntimeError(f"TP error for {key} {s_iso}..{e_iso}: {payload.get('message')}")
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            iid = item.get("id")
            merged.setdefault(str(iid) if iid is not None else f"_{len(merged)}", item)
    return list(merged.values())


async def _fetch_chunked_health(tp_get_metrics_fn: Any, start: date, end: date) -> dict[str, list]:
    merged: dict[str, list] = {"sleep": [], "hrv": [], "rhr": []}
    for s_iso, e_iso in tp_calls.date_chunks(start, end):
        raw = await tp_get_metrics_fn(s_iso, e_iso)
        if isinstance(raw, dict) and raw.get("isError"):
            logger.warning("Skipping health chunk %s..%s: %s", s_iso, e_iso, raw.get("message"))
            continue
        for k, vals in extract_health_metrics_dated(raw).items():
            merged[k].extend(vals)
    return merged


async def backfill_years(
    *,
    runner_id: str,
    years: list[int],
    force: bool = False,
    delay_seconds: float = 3.0,
    dry_run: bool = False,
    tp_tools: Optional[dict[str, Any]] = None,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Backfills the requested calendar years into Firestore for `runner_id`."""
    today_d = today or get_today_date()
    profile = await firestore.get_user_profile(runner_id)
    if not profile:
        raise RuntimeError(f"Runner profile 'users/{runner_id}' not found in Firestore.")

    if dry_run:
        plan: list[dict[str, Any]] = []
        for yr in years:
            start, end, is_complete = calendar_year_window(yr, today_d)
            existing = await firestore.get_cached_year_review(runner_id, yr)
            already_complete = bool(isinstance(existing, dict) and existing.get("is_complete"))
            chunks = tp_calls.date_chunks(start, end)
            plan.append({
                "year": yr,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "is_complete": is_complete,
                "chunks": len(chunks),
                "action": "skip (cached complete)" if (already_complete and not force) else "backfill",
            })
        return plan

    if tp_tools is None:
        if not os.getenv("TP_AUTH_COOKIE"):
            cookie = await credentials.get_runner_tp_cookie(runner_id)
            if not cookie:
                raise RuntimeError(
                    f"No TrainingPeaks cookie found for '{runner_id}' (set TP_AUTH_COOKIE or connect via Web App)."
                )
            os.environ["TP_AUTH_COOKIE"] = cookie

        from tp_mcp.tools.events import tp_get_events
        from tp_mcp.tools.fitness import tp_get_fitness
        from tp_mcp.tools.metrics import tp_get_metrics
        from tp_mcp.tools.peaks import tp_get_peaks
        from tp_mcp.tools.settings import tp_get_athlete_settings
        from tp_mcp.tools.workouts import tp_get_workout, tp_get_workouts

        tp_tools = {
            "workouts": tp_get_workouts,
            "events": tp_get_events,
            "metrics": tp_get_metrics,
            "fitness": tp_get_fitness,
            "settings": tp_get_athlete_settings,
            "peaks": tp_get_peaks,
            "workout": tp_get_workout,
        }

    settings_cache: dict[str, Any] = {}

    async def _settings() -> Any:
        if "value" not in settings_cache:
            settings_cache["value"] = await tp_tools["settings"]()
        return settings_cache["value"]

    results: list[dict[str, Any]] = []
    for idx, yr in enumerate(years):
        logger.info("Processing calendar year %d (%d/%d)...", yr, idx + 1, len(years))
        res = await compile_and_cache_annual_review(
            user_id=runner_id,
            profile=profile,
            year=yr,
            today=today_d,
            force_full=force,
            fetch_workouts_fn=lambda s, e: _fetch_chunked_tp(tp_tools["workouts"], "workouts", s, e),
            fetch_events_fn=lambda s, e: _fetch_chunked_tp(tp_tools["events"], "events", s, e),
            fetch_health_fn=lambda s, e: _fetch_chunked_health(tp_tools["metrics"], s, e),
            fetch_fitness_fn=lambda s, e: tp_tools["fitness"](start_date=s, end_date=e),
            fetch_settings_fn=_settings,
            fetch_peak_fn=lambda pr_type, s, e: tp_tools["peaks"](
                sport="Run", pr_type=pr_type, start_date=s, end_date=e
            ),
            fetch_workout_fn=lambda wid: tp_tools["workout"](wid),
        )
        results.append(res)
        logger.info(
            "Year %d complete: status=%s mode=%s workouts=%d races=%d",
            yr,
            res.get("status"),
            res.get("mode"),
            res.get("workouts", 0),
            res.get("races", 0),
        )
        if delay_seconds > 0 and idx + 1 < len(years):
            await asyncio.sleep(delay_seconds)
    return results


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill historical Calendar-Year Annual Reviews from TrainingPeaks into Firestore."
    )
    p.add_argument("--runner-id", default="cyrille_visser", help="Firestore runner document ID (default: cyrille_visser)")
    p.add_argument("--years", type=int, nargs="+", default=None, help="Explicit list of years (e.g. --years 2025 2024 2023)")
    p.add_argument("--from-year", type=int, default=2023, help="Start year when --years is omitted (default: 2023)")
    p.add_argument("--to-year", type=int, default=2025, help="End year when --years is omitted (default: 2025)")
    p.add_argument("--force", action="store_true", help="Re-fetch even if a finished year is already cached")
    p.add_argument("--delay-seconds", type=float, default=3.0, help="Pause between years to respect TP rate limits (default: 3.0)")
    p.add_argument("--dry-run", action="store_true", help="Print planned years and chunks without calling TP or writing Firestore")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    years = resolve_target_years(years=args.years, from_year=args.from_year, to_year=args.to_year)
    summary = asyncio.run(
        backfill_years(
            runner_id=args.runner_id,
            years=years,
            force=args.force,
            delay_seconds=args.delay_seconds,
            dry_run=args.dry_run,
        )
    )
    for row in summary:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
