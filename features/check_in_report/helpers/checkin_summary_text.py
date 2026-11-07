from typing import Optional

from ....shared.calendar_notes import truncate_note
from ....shared.dates import format_display_date
from ....shared.health_metrics import format_recovery_metrics
from .metrics_tables import format_fitness_pmc
from .weekly_totals import format_weekly_totals


def _run_time_weather(snippet: Optional[str]) -> str:
    """Hourly conditions when present (drops the redundant `| [Day: ...]`), else the day summary."""
    return str(snippet).split(" | [Day:", 1)[0] if snippet else ""


def format_completed_workouts(
    workouts_past: Optional[list[dict]],
    weather_map: Optional[dict[str, str]] = None,
) -> str:
    """Formats past completed workouts across all sports with optional embedded run-time weather."""
    if workouts_past is None:
        return ""
    completed_items = []
    weather_map = weather_map or {}
    for w in workouts_past:
        sport = w.get("sport", "Workout")
        w_id = w.get("id", "")
        w_title = w.get("title") or sport
        start_time = w.get("start_time")
        time_identifier = start_time or w.get("date", "")
        time_display = format_display_date(time_identifier)
        dist_km = round(w.get("distance_actual_km") or 0.0, 1)
        dur_hrs = w.get("duration_actual")
        dur_str = f" | Dur: {round(dur_hrs, 2)}h" if dur_hrs and isinstance(dur_hrs, (int, float)) else ""
        dist_str = f": {dist_km}km" if dist_km > 0 else ""
        actual_tss = w.get("tss_actual") or w.get("tss") or 0

        wx = _run_time_weather(weather_map.get(str(start_time))) if start_time else ""
        wx_str = f" [Weather: {wx}]" if wx else ""

        completed_items.append(
            f"- [{sport}] '{w_title}' [{w_id}] on {time_display}{dist_str}{dur_str} | TSS: {actual_tss}{wx_str}"
        )
    return "\n".join(completed_items) if completed_items else "No completed sessions found."


def format_planned_workouts(workouts_future: Optional[list[dict]]) -> str:
    """Formats upcoming scheduled workouts across all sports compactly."""
    if workouts_future is None:
        return ""
    upcoming_items = []
    for w in workouts_future:
        sport = w.get("sport", "Workout")
        w_id = w.get("id", "")
        w_title = w.get("title") or sport
        planned_km = round(w.get("distance_planned_km") or 0.0, 1)
        planned_tss = w.get("tss_planned") or 0
        date_str = str(w.get("date", ""))[:10]
        date_display = format_display_date(date_str)
        dist_str = f": {planned_km}km" if planned_km > 0 else ""
        upcoming_items.append(
            f"- [{sport}] '{w_title}' [{w_id}] on {date_display}{dist_str} | Planned TSS: {planned_tss}"
        )
    return "\n".join(upcoming_items) if upcoming_items else "No upcoming workouts planned."


def format_calendar_notes(notes_list: Optional[list[dict]]) -> str:
    """Formats runner calendar notes and context compactly."""
    if notes_list is None:
        return ""
    notes_summary_list = []
    for n in notes_list:
        n_date = str(n.get("date", ""))[:10]
        date_display = format_display_date(n_date)
        n_title = n.get("title") or "Note"
        n_desc = truncate_note(n.get("description") or "")
        desc_str = f" | {n_desc}" if n_desc else ""
        notes_summary_list.append(f"- {date_display}: {n_title}{desc_str}")
    return "\n".join(notes_summary_list) if notes_summary_list else "No calendar notes."


def compile_checkin_summary(
    lookback_days: int,
    lookahead_days: int,
    workouts_past: Optional[list[dict]],
    workouts_future: Optional[list[dict]],
    metrics_data: Optional[dict],
    fitness_data: Optional[dict],
    notes_list: Optional[list[dict]],
    weather_map: Optional[dict[str, str]] = None,
    race_projection: Optional[dict] = None,
    weekly_totals: Optional[list[dict]] = None,
    recovery_baseline: Optional[str] = None,
    lt_paces: Optional[dict] = None,
) -> str:
    """Compiles a complete, unified Check-In Summary payload for the check-in-report skill."""
    parts = ["### Weekly Check-In Training & Physiological Report\n"]

    if fitness_data is not None:
        parts.append(
            f"**1. Fitness PMC Trends, Goal Race Projection & Trajectory (Past {lookback_days} days):**\n"
            f"{format_fitness_pmc(fitness_data, race_projection, lt_paces)}\n"
        )

    if metrics_data is not None:
        recovery = format_recovery_metrics(metrics_data)
        if recovery_baseline:
            recovery += f"\n- 5-day vs 28-day baseline, recent hard effort & load (pre-computed facts): {recovery_baseline}"
        parts.append(f"**2. Autonomic & Physiological Recovery Trends (Past {lookback_days} days):**\n{recovery}\n")

    if weekly_totals is not None:
        parts.append(f"**3. Weekly Totals (completed, pre-computed; do not recompute):**\n{format_weekly_totals(weekly_totals)}\n")

    if workouts_past is not None:
        parts.append(f"**4. Completed Workouts & Environmental Context (Past {lookback_days} days):**\n{format_completed_workouts(workouts_past, weather_map)}\n")

    if notes_list is not None:
        parts.append(f"**5. Calendar & Travel Notes:**\n{format_calendar_notes(notes_list)}\n")

    if workouts_future is not None:
        parts.append(f"**6. Upcoming Scheduled Workouts (Next {lookahead_days} days):**\n{format_planned_workouts(workouts_future)}\n")

    return "\n".join(parts)
