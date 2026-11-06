from typing import Optional

from ....shared.dates import parse_iso_timestamp
from ....shared.sports import BIKE_SPORTS, NON_TRAINING_SPORTS, RUN_SPORTS, STRENGTH_SPORTS
from ....shared.units import as_float
from ....shared.workout_status import is_workout_completed

# Sport priority when picking a day's primary session (lower = more important).
_SPORT_TIERS = ((RUN_SPORTS, 0), (BIKE_SPORTS, 1), (STRENGTH_SPORTS, 3))
_OTHER_ENDURANCE_TIER = 2  # swim, row, ...
_NON_TRAINING_TIER = 4
_NON_TRAINING = {s.lower() for s in NON_TRAINING_SPORTS}
_SPORT_FAMILIES = {"run": RUN_SPORTS, "bike": BIKE_SPORTS}


def _sport_key(workout: dict) -> str:
    return (workout.get("sport") or "").strip().lower()


def _sport_tier(workout: dict) -> int:
    sport = _sport_key(workout)
    if sport in _NON_TRAINING:
        return _NON_TRAINING_TIER
    for sports, tier in _SPORT_TIERS:
        if sport in sports:
            return tier
    return _OTHER_ENDURANCE_TIER


def _start_ordinal(workout: dict) -> float:
    ts = parse_iso_timestamp(workout.get("start_time") or workout.get("date"))
    return ts.timestamp() if ts else 0.0


def select_primary_workout(
    completed: list[dict], sport: Optional[str] = None
) -> tuple[Optional[dict], list[dict]]:
    """Returns (primary, others) for a day's completed workouts.

    `sport` ('run' / 'bike') restricts the choice to that family when one exists.
    Ranking: sport tier (run > bike > other endurance > strength > non-training),
    then highest actual TSS, longest duration, latest start.
    """
    if not completed:
        return None, []
    family = _SPORT_FAMILIES.get((sport or "").strip().lower())
    pool = [w for w in completed if family and _sport_key(w) in family] or completed
    primary = min(pool, key=lambda w: (
        _sport_tier(w),
        -(as_float(w.get("tss_actual")) or 0.0),
        -(as_float(w.get("duration_actual")) or 0.0),
        -_start_ordinal(w),
    ))
    return primary, [w for w in completed if w is not primary]


def format_other_sessions(others: list[dict], date_iso: str) -> str:
    """One-line disclosure of the day's other completed sessions, or '' when none."""
    items = []
    for w in others or []:
        details = [w.get("sport") or "Workout"]
        hours = as_float(w.get("duration_actual"))
        if hours:
            details.append(f"{round(hours * 60)} min")
        tss = as_float(w.get("tss_actual"))
        if tss is not None:
            details.append(f"TSS {round(tss, 1)}")
        details.append(f"id {w.get('id')}")
        items.append(f"'{w.get('title') or w.get('sport') or 'Workout'}' ({', '.join(details)})")
    if not items:
        return ""
    return (
        f"Other completed sessions on {date_iso} (not analysed): {'; '.join(items)}. "
        "Call analyze_workout(workout_id=...) to analyse one."
    )


NO_WORKOUT_PREFIX = "No completed workout"


def format_no_workout(date_iso: str, day_workouts: list[dict], recent_workouts: list[dict]) -> str:
    """Runner-facing reply for a date without a completed workout."""
    msg = f"{NO_WORKOUT_PREFIX} on {date_iso} in TrainingPeaks."
    planned = [w.get("title") or w.get("sport") or "Workout" for w in day_workouts]
    if planned:
        msg += f" Planned that day: {', '.join(planned)}."
    done = [w for w in recent_workouts if is_workout_completed(w)]
    if done:
        last = max(done, key=_start_ordinal)
        msg += f" Your most recent completed workout is {last.get('title') or last.get('sport')} on {str(last.get('date'))[:10]}."
    return msg + " If you've already trained, sync it to TrainingPeaks and ask again, or tell me which date to analyze."
