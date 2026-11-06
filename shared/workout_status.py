"""Workout completion checks and past/upcoming date partitioning."""

from datetime import date
from typing import Any, Optional

from .dates import parse_date


def _is_positive(value: Any) -> bool:
    """True when a raw MCP value represents a number greater than zero."""
    if isinstance(value, bool) or value is None:
        return False
    try:
        return float(value) > 0
    except (ValueError, TypeError):
        return False


# Fields that, when positive, prove a session was actually executed.
_ACTUALS_FIELDS = (
    "distance_actual_km",
    "tss_actual",
    "duration_actual",
)


def is_workout_completed(workout: dict) -> bool:
    """Canonical check for whether a workout has been executed/completed."""
    if not workout:
        return False
    if workout.get("type") == "completed":
        return True
    return any(_is_positive(workout.get(field)) for field in _ACTUALS_FIELDS)


def partition_workouts_by_date(
    workouts_list: list[dict],
    reference_date: date,
) -> tuple[list[dict], Optional[list[dict]]]:
    """Splits workouts into (completed/past, upcoming).

    A session on the reference date counts as past only once it is completed.
    The upcoming list is None when empty so callers can omit the section entirely.
    """
    past_list: list[dict] = []
    future_list: list[dict] = []

    for w in workouts_list or []:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date:
            continue
        if w_date < reference_date or (w_date == reference_date and is_workout_completed(w)):
            past_list.append(w)
        else:
            future_list.append(w)

    return past_list, (future_list or None)
