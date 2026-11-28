"""Lightweight TrainingPeaks calendar peek tool (no report card, no SKILL.md)."""

from datetime import date, timedelta
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.athlete_settings import sport_thresholds
from ...shared.calendar_notes import add_notes_to_weeks
from ...shared.dates import get_today_date, iso_date, monday_of, parse_date
from ...shared.parallel_fetch import gather_labeled
from ...shared.sports import BIKE_SPORTS, RUN_SPORTS
from ...shared.tp_payloads import coerce_mcp_payload
from ...shared.weekly_buckets import build_week_buckets, compact_prescription, format_week_sessions
from ...shared.workout_builder import builder_summary, has_builder
from ...shared.workout_upsert import run_throttled

MAX_SCHEDULE_DAYS = 42  # <= 6 weeks; full blocks use fetch_plan_audit_data + plan-audit
PRESCRIPTION_MAX_DAYS = 14  # <= 2 weeks inline zero-extra-MCP workout prescriptions from description
DETAIL_MAX_DAYS = 7  # <= 1 week when fetching external structured workout builders via tp_get_workout


def resolve_schedule_window(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    *,
    include_details: bool = False,
) -> tuple[date, date, bool]:
    """Resolves `(q_start, q_end, clamped)` using `get_schedule`'s ISO-week default and day caps."""
    today_date = get_today_date()
    q_start = parse_date(start_date) or monday_of(today_date)
    q_end = parse_date(end_date) or (q_start + timedelta(days=6))
    if q_end < q_start:
        q_start, q_end = q_end, q_start
    limit_days = DETAIL_MAX_DAYS if include_details else MAX_SCHEDULE_DAYS
    max_end = q_start + timedelta(days=limit_days - 1)
    clamped = q_end > max_end
    if clamped:
        q_end = max_end
    return q_start, q_end, clamped


async def _fetch_workout_detail(tool_context: ToolContext, workout_id: str) -> tuple[str, Optional[dict]]:
    raw = await tp_calls.run_tp_tool(tool_context, "tp_get_workout", workout_id=workout_id)
    payload = coerce_mcp_payload(raw) if raw else {}
    return workout_id, (payload if isinstance(payload, dict) and not payload.get("isError") else None)


async def _enrich_external_builders(
    tool_context: ToolContext,
    workouts: list[dict],
    weeks: dict[str, dict],
    q_start: date,
    q_end: date,
) -> None:
    """Populates builder step summaries via `tp_get_workout` for Run/Bike workouts lacking a coded description."""
    detail_ids: list[str] = []
    for w in workouts:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date or not (q_start <= w_date <= q_end):
            continue
        sport_low = (w.get("sport") or "Run").strip().lower()
        w_id = w.get("id") or w.get("workout_id")
        desc = str(w.get("description") or "")
        if w_id is not None and sport_low in (RUN_SPORTS | BIKE_SPORTS) and "plan code:" not in desc.lower():
            detail_ids.append(str(w_id))
    unique_ids = list(dict.fromkeys(detail_ids))
    if not unique_ids:
        return

    extra = await gather_labeled({
        "settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
        "details": run_throttled(unique_ids, lambda wid: _fetch_workout_detail(tool_context, wid)),
    })
    details_by_id = {wid: d for wid, d in (extra.get("details") or []) if d}
    if not details_by_id:
        return
    settings_raw: Any = extra.get("settings")

    for bucket in weeks.values():
        for item in bucket.get("session_items") or []:
            wid = item.get("id")
            detail = details_by_id.get(str(wid)) if wid else None
            if not detail:
                continue
            structured = detail.get("structured_workout")
            if has_builder(structured):
                thr = sport_thresholds(settings_raw, item.get("sport"))
                summary = builder_summary(structured, thr)
                if summary:
                    note = item.get("prescription")
                    if note and note.casefold() != summary.casefold() and summary not in note:
                        combined = f"{summary} · {note}"
                        item["prescription"] = combined if len(combined) <= 140 else summary
                    else:
                        item["prescription"] = summary
                    continue
            if not item.get("prescription") and detail.get("description"):
                item["prescription"] = compact_prescription(detail.get("description"))


def _format_schedule_week_header(w: dict) -> str:
    start: date = w["start_date"]
    end: date = w["end_date"]
    km = round(w.get("total_distance_km") or 0.0, 1)
    tss = round(w.get("total_tss") or 0.0)
    splits = [f"{w.get('easy_count', 0)}E/{w.get('quality_count', 0)}Q"]
    if w.get("bike_count"):
        splits.append(f"{w['bike_count']} Bike")
    if w.get("strength_count"):
        splits.append(f"{w['strength_count']} Str")
    if w.get("other_sport_count"):
        splits.append(f"{w['other_sport_count']} Oth")
    lr_km = round(w.get("long_km") or 0.0, 1)
    lr_part = f" · LR {lr_km:g} km" if lr_km > 0 else ""
    return f"* **{iso_date(start)} – {end.strftime('%b %d')}**: {km} km · TSS {tss} · {', '.join(splits)}{lr_part}"


async def get_schedule(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    include_details: bool = False,
) -> str:
    """TrainingPeaks calendar check for <= 6 weeks (default: current Mon-Sun ISO week; YYYY-MM-DD `start_date`/`end_date`; inline prescriptions shown automatically for <= 2 weeks; pass `include_details=True` for <= 7 days only when a planned workout's structured step targets are missing from an active schedule; opens no report card)."""
    q_start, q_end, clamped = resolve_schedule_window(
        start_date, end_date, include_details=include_details
    )
    limit_days = DETAIL_MAX_DAYS if include_details else MAX_SCHEDULE_DAYS

    start_str, end_str = iso_date(q_start), iso_date(q_end)
    raw = await gather_labeled({
        "workouts": tp_calls.fetch_workouts(tool_context, start_str, end_str),
        "calendar notes": tp_calls.fetch_notes(tool_context, start_str, end_str),
    })

    if raw["workouts"] is None:
        return (
            f"Error: Could not load TrainingPeaks workouts for {start_str} to {end_str}. "
            "This is a data-loading failure: do NOT tell the runner the calendar is empty. "
            "Say the calendar could not be loaded and suggest trying again shortly."
        )

    weeks = build_week_buckets(raw["workouts"], q_start, q_end)
    add_notes_to_weeks(weeks, raw["calendar notes"] or [])
    if include_details:
        await _enrich_external_builders(tool_context, raw["workouts"], weeks, q_start, q_end)

    show_prescriptions = include_details or (q_end - q_start).days < PRESCRIPTION_MAX_DAYS
    lines = [f"### Schedule ({start_str} – {end_str})", ""]
    for w in weeks.values():
        lines.append(_format_schedule_week_header(w))
        sessions_line = format_week_sessions(
            w.get("session_items") or [],
            show_prescriptions=show_prescriptions,
            force_planned_ids=include_details,
        )
        lines.append(f"  Sessions: {sessions_line}" if sessions_line else "  Sessions: none scheduled")
        if w.get("notes"):
            lines.append(f"  Notes: {' · '.join(w['notes'])}")
    if clamped:
        lines.append(f"\n*(Capped to {limit_days} days ending {end_str}.)*")
    if raw["calendar notes"] is None:
        lines.append("\n⚠️ Calendar notes unavailable (TrainingPeaks error).")
    return "\n".join(lines)


get_schedule_tool = FunctionTool(get_schedule)
