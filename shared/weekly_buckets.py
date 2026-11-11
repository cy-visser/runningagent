"""Weekly (ISO week) aggregation of workouts, shared by the plan audit and the check-in."""

from datetime import date, timedelta
from typing import Any, Optional

from .dates import format_display_date, iso_week_key, parse_date
from .sports import BIKE_SPORTS, NON_TRAINING_SPORTS, RUN_SPORTS, STRENGTH_SPORTS, is_quality_title
from .workout_status import is_workout_completed


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
        "long_km": 0.0,
        "long_duration_h": None,
        "total_tss": 0.0,
        "easy_count": 0,
        "quality_count": 0,
        "bike_count": 0,
        "strength_count": 0,
        "other_sport_count": 0,
        "sessions": [],
        "session_items": [],
        "notes": [],
    }


def tally_workout(bucket: dict, workout: dict, w_date: date) -> None:
    """Adds one workout's volume, load and intensity classification to its week bucket.

    Completed workouts count their executed values; planned ones their planned values.
    """
    sport = (workout.get("sport") or "Run").strip()
    sport_lower = sport.lower()
    completed = is_workout_completed(workout)
    order = ("actual", "planned") if completed else ("planned", "actual")
    dist = next((_float(workout.get(f"distance_{k}_km")) for k in order if workout.get(f"distance_{k}_km")), 0.0)
    duration_h = next(
        (_float(workout.get(f"duration_{k}")) for k in order if workout.get(f"duration_{k}")),
        None,
    )
    tss = next(
        (_float(workout.get(f"tss_{k}")) for k in order if workout.get(f"tss_{k}")),
        _float(workout.get("tss")),
    )
    bucket["total_tss"] += tss

    title = workout.get("title") or sport
    if sport_lower in RUN_SPORTS:
        bucket["total_distance_km"] += dist
        category = "quality" if is_quality_title(title) else "easy"
        bucket[f"{category}_count"] += 1
        if dist > bucket["long_km"]:
            bucket["long_km"] = dist
            bucket["long_duration_h"] = duration_h
    elif sport_lower in BIKE_SPORTS:
        category = "bike"
        bucket["bike_count"] += 1
    elif sport_lower in STRENGTH_SPORTS:
        category = "strength"
        bucket["strength_count"] += 1
    else:
        category = "other"
        bucket["other_sport_count"] += 1

    bucket["session_items"].append({
        "date": w_date,
        "sport": sport,
        "title": title,
        "category": category,
        "km": dist,
        "minutes": (duration_h or 0.0) * 60.0,
        "tss": tss,
        "completed": completed,
    })
    dist_str = f"{round(dist, 1)}km, " if dist > 0 else ""
    # Same `[workout_id]` format as the check-in, so the coach can stage changes from an audit
    # without calling a report tool as a lookup.
    w_id = workout.get("id") or workout.get("workout_id")
    id_str = f" [{w_id}]" if w_id else ""
    bucket["sessions"].append(
        f"[{sport}] '{title}'{id_str} on {format_display_date(w_date)} ({dist_str}TSS: {round(tss, 0)})"
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


def format_week_line(w: dict) -> str:
    """One-line weekly totals: running km, run split, cross-training and TSS."""
    w_range = w.get("date_range", "Week")
    total_vol = round(w.get("total_distance_km", 0.0), 1)
    total_tss = round(w.get("total_tss", 0.0), 1)
    easy_runs = w.get("easy_count", 0)
    quality_runs = w.get("quality_count", 0)
    total_runs = easy_runs + quality_runs

    cross_parts = []
    bike_count = w.get("bike_count", 0)
    if bike_count > 0:
        cross_parts.append(f"{bike_count} bike" if bike_count == 1 else f"{bike_count} bikes")
    strength_count = w.get("strength_count", 0)
    if strength_count > 0:
        cross_parts.append(f"{strength_count} strength")
    other_count = w.get("other_sport_count", 0)
    if other_count > 0:
        cross_parts.append(f"{other_count} other")
    cross_str = f" | {', '.join(cross_parts)}" if cross_parts else ""

    return (
        f"* **{w_range}:** {total_vol} km ({total_runs} runs: {easy_runs} easy, "
        f"{quality_runs} quality{cross_str}) | TSS: {total_tss}"
    )
