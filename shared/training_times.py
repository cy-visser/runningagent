"""The runner's preferred training times (profile `run_time_of_day` / `strength_time_of_day`).

Values are 'morning', 'afternoon' or 'evening'. The plan builder shows them in the plan context and
times the run and strength sessions of a double day in that order in TrainingPeaks.
"""

from typing import Any, Optional

TIMES_OF_DAY = ("morning", "afternoon", "evening")
CLOCK = {"morning": "07:00", "afternoon": "13:00", "evening": "18:00"}
# Plan sport -> profile field.
PROFILE_FIELDS = {"Run": "run_time_of_day", "Strength": "strength_time_of_day"}
# Same slot for run and strength: the run goes first, strength this many minutes later.
SAME_SLOT_GAP_MIN = 90

_ALIASES = {
    "morning": "morning", "am": "morning", "early": "morning",
    "afternoon": "afternoon", "midday": "afternoon", "noon": "afternoon", "lunch": "afternoon", "mid": "afternoon",
    "evening": "evening", "pm": "evening", "night": "evening", "late": "evening",
}


def normalize_time_of_day(value: Any) -> Optional[str]:
    """'Morning' / 'am' / 'lunch' / 'evening' ... -> 'morning' | 'afternoon' | 'evening'; else None."""
    return _ALIASES.get(str(value or "").strip().lower())


def training_times_text(profile: Optional[dict]) -> str:
    """'run morning · strength evening' (the set preferences only), or '' when none is set."""
    profile = profile or {}
    parts = []
    for sport, field in PROFILE_FIELDS.items():
        when = normalize_time_of_day(profile.get(field))
        if when:
            parts.append(f"{sport.lower()} {when}")
    return " · ".join(parts)


def _add_minutes(clock: str, minutes: int) -> str:
    total = min(int(clock[:2]) * 60 + int(clock[3:]) + minutes, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def default_session_times(profile: Optional[dict]) -> dict[str, str]:
    """{'Run': 'HH:MM', 'Strength': 'HH:MM'} for double days; {} unless both preferences are set."""
    profile = profile or {}
    run = normalize_time_of_day(profile.get(PROFILE_FIELDS["Run"]))
    strength = normalize_time_of_day(profile.get(PROFILE_FIELDS["Strength"]))
    if not run or not strength:
        return {}
    times = {"Run": CLOCK[run], "Strength": CLOCK[strength]}
    if run == strength:
        times["Strength"] = _add_minutes(times["Run"], SAME_SLOT_GAP_MIN)
    return times
