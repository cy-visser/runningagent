"""Weekly (ISO week) aggregation of workouts, shared by the schedule audit and the check-in."""

from datetime import date, timedelta
from typing import Any, Optional

from .classification import BIKE_SPORTS, NON_TRAINING_SPORTS, RUN_SPORTS, STRENGTH_SPORTS, is_quality_title
from .date_helpers import format_display_date, iso_week_key, parse_date
from .workouts import is_workout_completed


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def new_week_bucket(day: date) -> dict:
    """Creates an empty weekly aggregation bucket for the ISO week containing `day`."""
    w_start = day - timedelta(days=day.weekday())
    w_end = w_start + timedelta(days=6)
    return {
        "date_range": f"{w_start.strftime('%b %d')} - {w_end.strftime('%b %d, %Y')}",
        "start_date": w_start,
        "end_date": w_end,
        "total_distance_km": 0.0,
        "total_tss": 0.0,
        "easy_count": 0,
        "quality_count": 0,
        "bike_count": 0,
        "strength_count": 0,
        "other_sport_count": 0,
        "sessions": [],
        "notes": [],
    }


def tally_workout(bucket: dict, workout: dict, w_date: date) -> None:
    """Adds one workout's volume, load and intensity classification to its week bucket.

    Completed workouts count their executed values; planned ones their planned values.
    """
    sport = (workout.get("sport") or "Run").strip()
    sport_lower = sport.lower()
    order = ("actual", "planned") if is_workout_completed(workout) else ("planned", "actual")
    dist = next((_float(workout.get(f"distance_{k}_km")) for k in order if workout.get(f"distance_{k}_km")), 0.0)
    tss = next(
        (_float(workout.get(f"tss_{k}")) for k in order if workout.get(f"tss_{k}")),
        _float(workout.get("tss")),
    )
    bucket["total_tss"] += tss

    title = workout.get("title") or sport
    if sport_lower in RUN_SPORTS:
        bucket["total_distance_km"] += dist
        bucket["quality_count" if is_quality_title(title) else "easy_count"] += 1
    elif sport_lower in BIKE_SPORTS:
        bucket["bike_count"] += 1
    elif sport_lower in STRENGTH_SPORTS:
        bucket["strength_count"] += 1
    else:
        bucket["other_sport_count"] += 1

    dist_str = f"{round(dist, 1)}km, " if dist > 0 else ""
    bucket["sessions"].append(
        f"[{sport}] '{title}' on {format_display_date(w_date)} ({dist_str}TSS: {round(tss, 0)})"
    )


def build_week_buckets(workouts: Optional[list[dict]], start: date, end: date) -> dict[str, dict]:
    """Returns {iso_week_key: bucket} for every ISO week touching [start, end], with workouts tallied."""
    weeks: dict[str, dict] = {}
    cur = start - timedelta(days=start.weekday())  # Monday, so no partial week is skipped
    while cur <= end:
        weeks[iso_week_key(cur)] = new_week_bucket(cur)
        cur += timedelta(days=7)

    for w in workouts or []:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date or not (start <= w_date <= end):
            continue
        # Skip calendar rest placeholders and educational/tip cards.
        if (w.get("sport") or "Run").strip() in NON_TRAINING_SPORTS:
            continue
        bucket = weeks.get(iso_week_key(w_date))
        if bucket:
            tally_workout(bucket, w, w_date)
    return weeks


def add_notes_to_weeks(weeks: dict[str, dict], notes: Optional[list[dict]]) -> None:
    """Appends every calendar note to the bucket of its week."""
    for n in notes or []:
        n_date = parse_date(n.get("date"))
        bucket = weeks.get(iso_week_key(n_date)) if n_date else None
        if bucket is None:
            continue
        title = n.get("title") or "Note"
        desc = n.get("description") or ""
        bucket["notes"].append(f"{format_display_date(n_date)}: {title}" + (f" | {desc}" if desc else ""))
