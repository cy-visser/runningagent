"""Formats the compact multi-week plan audit text summary and race-event audit checks."""

from datetime import date
from typing import Any, Optional

from ....shared.dates import iso_date, parse_date
from ....shared.goal_plan import goal_list, race_day
from ....shared.race_events import (
    event_date_iso,
    event_priority,
    format_event_summary,
    has_race_tag,
    is_running_event,
    match_event_for_date,
)
from ....shared.sports import is_race_title
from ....shared.weekly_buckets import format_week_sessions
from ....shared.workout_status import is_workout_completed
from .long_run_annotations import format_audit_week_header


def _is_planned_race_workout(w: dict[str, Any]) -> bool:
    if is_workout_completed(w):
        return False
    sport_low = str(w.get("sport") or "").strip().lower()
    if sport_low == "race" or has_race_tag(w.get("tags")):
        return True
    title = str(w.get("title") or "").strip()
    return title.lower().startswith(("race:", "event:")) or is_race_title(title)


def format_events_audit_section(
    events: Optional[list[dict[str, Any]]],
    workouts: list[dict[str, Any]],
    profile: dict[str, Any],
    q_start: date,
    q_end: date,
) -> str:
    """Deterministic audit facts for TrainingPeaks Calendar Events + paired race workouts in `[q_start, q_end]`."""
    if events is None:
        return "⚠️ **Race Events:** TrainingPeaks events unavailable (API error); could not verify race events."

    s_iso, e_iso = iso_date(q_start), iso_date(q_end)
    running_events = sorted(
        (ev for ev in events if is_running_event(ev) and (d := event_date_iso(ev)) and s_iso <= d <= e_iso),
        key=lambda ev: event_date_iso(ev) or "",
    )
    planned_runs_by_day: dict[str, list[dict[str, Any]]] = {}
    planned_races_by_day: dict[str, list[dict[str, Any]]] = {}
    for w in workouts or []:
        d = parse_date(w.get("date") or w.get("start_time"))
        if not d or not (q_start <= d <= q_end) or is_workout_completed(w):
            continue
        d_iso = iso_date(d)
        sport_low = str(w.get("sport") or "").strip().lower()
        if sport_low in ("run", "running", "trail run", "treadmill", "race"):
            planned_runs_by_day.setdefault(d_iso, []).append(w)
        if _is_planned_race_workout(w):
            planned_races_by_day.setdefault(d_iso, []).append(w)

    goal_races: list[tuple[str, dict[str, Any]]] = []
    for block in goal_list(profile):
        r_day = race_day(block)
        if r_day and q_start <= r_day <= q_end:
            goal_races.append((iso_date(r_day), block))
    goal_dates = {d for d, _ in goal_races}

    lines = ["**Race Events in Window:**"]
    if running_events:
        for ev in running_events:
            summary = format_event_summary(ev)
            ev_id = f" [event_id={ev['id']}]" if ev.get("id") is not None else ""
            lines.append(f"- {event_date_iso(ev)} {ev.get('name') or 'Event'}" + (f" ({summary})" if summary else "") + ev_id)
    else:
        lines.append("- None configured in TrainingPeaks.")

    findings: list[str] = []
    for g_iso, block in goal_races:
        label = block.get("race_name") or block.get("training_goal") or "Goal Race"
        ev = match_event_for_date(running_events, g_iso, label)
        if ev is None:
            findings.append(f"- ⚠️ Missing TrainingPeaks A-priority Event for block goal '{label}' on {g_iso}.")
        elif event_priority(ev) != "A":
            findings.append(
                f"- ⚠️ Block goal Event '{ev.get('name')}' on {g_iso} has priority {event_priority(ev) or 'unset'} (expected A)."
            )
        if not planned_runs_by_day.get(g_iso):
            findings.append(f"- ⚠️ Missing planned race workout on {g_iso} for block goal '{label}' (need Event + Workout).")

    for r_iso, r_workouts in sorted(planned_races_by_day.items()):
        if r_iso in goal_dates:
            continue
        w_title = str(r_workouts[0].get("title") or "Intermediate Race")
        ev = match_event_for_date(running_events, r_iso, w_title)
        if ev is None:
            findings.append(
                f"- ⚠️ Missing TrainingPeaks B/C-priority Event for intermediate race '{w_title}' on {r_iso}."
            )
        elif event_priority(ev) == "A":
            findings.append(
                f"- ⚠️ Intermediate race Event '{ev.get('name')}' on {r_iso} is priority A (must be B or C, not A)."
            )

    for ev in running_events:
        ev_iso = event_date_iso(ev)
        if not ev_iso or ev_iso in goal_dates:
            continue
        if event_priority(ev) == "A":
            findings.append(
                f"- ⚠️ Intermediate TP Event '{ev.get('name')}' on {ev_iso} is priority A (should be B or C if inside another block)."
            )
        if not planned_runs_by_day.get(ev_iso):
            findings.append(
                f"- ⚠️ TP Event '{ev.get('name')}' on {ev_iso} has no paired planned race workout (need Event + Workout)."
            )

    if findings:
        lines.extend(findings)
    elif not running_events and not goal_races and not planned_races_by_day:
        return ""
    return "\n".join(lines)


def format_plan_audit_summary(
    weeks_data: list[dict],
    goal_context: Optional[str] = None,
    events_section: Optional[str] = None,
) -> str:
    """Formats a compact multi-week plan audit breakdown with day-grouped sessions, events, and notes."""
    lines = ["### Training Plan Audit"]
    if goal_context:
        lines += ["", goal_context]
    if events_section:
        lines += ["", events_section]
    lines.append("")

    for w in weeks_data:
        lines.append(format_audit_week_header(w))
        sessions_line = format_week_sessions(w.get("session_items") or [])
        if sessions_line:
            lines.append(f"  Sessions: {sessions_line}")
        if w.get("notes"):
            lines.append(f"  Notes: {' · '.join(w['notes'])}")
    return "\n".join(lines)
