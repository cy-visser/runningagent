"""Long-run facts shared by the plan audit and the trend analysis.

There is deliberately no computed long-run target, floor or cap: the coach reasons the long-run
progression toward the goal / north star from these facts (recent long runs, share of the week, time to
the races) and states its own per-week distances.
"""

from datetime import date, timedelta
from typing import Optional

from .dates import monday_of
from .weekly_buckets import build_week_buckets
from .workout_status import is_workout_completed

LONG_RUN_HISTORY_WEEKS = 6      # complete weeks before today's week shown as the long-run history


def fmt_km(value: float) -> str:
    return f"{value:g}"


def fmt_duration(hours: Optional[float]) -> str:
    """'1:28' (h:mm), or '' when unknown."""
    if not hours or hours <= 0:
        return ""
    minutes = round(hours * 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def history_window(today: date) -> tuple[date, date]:
    """(first day, last day) of the LONG_RUN_HISTORY_WEEKS complete weeks before today's week."""
    end = monday_of(today) - timedelta(days=1)
    return end - timedelta(weeks=LONG_RUN_HISTORY_WEEKS) + timedelta(days=1), end


def recent_long_runs(workouts: Optional[list[dict]], today: date) -> list[dict]:
    """[{'week', 'km', 'hours', 'week_km'}] longest completed run and total running km per complete week
    of the history window, oldest first."""
    start, end = history_window(today)
    done = [w for w in workouts or [] if is_workout_completed(w)]
    weeks = sorted(build_week_buckets(done, start, end).values(), key=lambda w: w["start_date"])
    return [{"week": w["start_date"], "km": round(w["long_km"] or 0.0, 1), "hours": w["long_duration_h"],
             "week_km": round(w["total_distance_km"] or 0.0, 1)}
            for w in weeks]


def format_weekly_km_history(entries: list[dict]) -> str:
    """'48 · 52 · – · 55' running km per history week (oldest first; '–' = no runs), or ''."""
    if not any(e.get("week_km") for e in entries):
        return ""
    return " · ".join(f"{e['week_km']:.0f}" if e.get("week_km") else "–" for e in entries)


def format_history(entries: list[dict]) -> str:
    """'12 km 1:05 · 14 km 1:16 · – · 16 km 1:28' (oldest first; '–' = no run that week), or ''."""
    if not any(e.get("km") for e in entries):
        return ""
    parts = []
    for e in entries:
        if not e.get("km"):
            parts.append("–")
            continue
        dur = fmt_duration(e.get("hours"))
        parts.append(f"{fmt_km(e['km'])} km" + (f" {dur}" if dur else ""))
    return " · ".join(parts)


def week_long_run_facts(long_km: Optional[float], hours: Optional[float], week_km: Optional[float]) -> str:
    """'16 km (1:28, 34% of the week's running km)', or 'no run'."""
    if not long_km:
        return "no run"
    extras = [d for d in (fmt_duration(hours),) if d]
    if week_km:
        extras.append(f"{round(long_km / week_km * 100)}% of the week's running km")
    return f"{fmt_km(round(long_km, 1))} km" + (f" ({', '.join(extras)})" if extras else "")
