"""Lightweight TrainingPeaks calendar peek tool (no report card, no SKILL.md)."""

from datetime import date, timedelta
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.calendar_notes import add_notes_to_weeks
from ...shared.dates import get_today_date, iso_date, monday_of, parse_date
from ...shared.parallel_fetch import gather_labeled
from ...shared.weekly_buckets import build_week_buckets, format_week_sessions

MAX_SCHEDULE_DAYS = 42  # <= 6 weeks; full blocks use fetch_plan_audit_data + plan-audit


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
) -> str:
    """TrainingPeaks calendar check for <= 6 weeks (e.g. checking a week, holiday, or travel window to discuss/adjust runs; default: current Mon-Sun ISO week; YYYY-MM-DD `start_date`/`end_date`; not a plan audit, opens no report card)."""
    today_date = get_today_date()
    q_start = parse_date(start_date) or monday_of(today_date)
    q_end = parse_date(end_date) or (q_start + timedelta(days=6))
    if q_end < q_start:
        q_start, q_end = q_end, q_start
    clamped = False
    max_end = q_start + timedelta(days=MAX_SCHEDULE_DAYS - 1)
    if q_end > max_end:
        q_end = max_end
        clamped = True

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

    lines = [f"### Schedule ({start_str} – {end_str})", ""]
    for w in weeks.values():
        lines.append(_format_schedule_week_header(w))
        sessions_line = format_week_sessions(w.get("session_items") or [])
        lines.append(f"  Sessions: {sessions_line}" if sessions_line else "  Sessions: none scheduled")
        if w.get("notes"):
            lines.append(f"  Notes: {' · '.join(w['notes'])}")
    if clamped:
        lines.append(f"\n*(Capped to {MAX_SCHEDULE_DAYS} days ending {end_str}.)*")
    if raw["calendar notes"] is None:
        lines.append("\n⚠️ Calendar notes unavailable (TrainingPeaks error).")
    return "\n".join(lines)


get_schedule_tool = FunctionTool(get_schedule)
