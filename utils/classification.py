"""Single source of truth for sport sets and workout-title classification.

Shared by the schedule audit (tools.py) and the race-readiness model so both
count the same sessions as races / quality work.
"""

import re

RUN_SPORTS = {"run", "running", "trail run", "treadmill"}
BIKE_SPORTS = {"bike", "cycling", "mtnbike", "gravel", "virtualride"}
STRENGTH_SPORTS = {"strength", "gym", "weighttraining", "s&c"}
# Calendar placeholders that carry no training load.
NON_TRAINING_SPORTS = {"DayOff", "Other"}

RACE_RE = re.compile(r"\b(race|parkrun|time[- ]?trial|tt|wedstrijd)\b", re.IGNORECASE)
# Titles that mention "race" without being one (race-pace blocks, shakeouts, ...).
NOT_RACE_RE = re.compile(
    r"\brace[- ]?(pace|week|prep|specific|sim\w*)\b|\b(pre|post)[- ]?race\b",
    re.IGNORECASE,
)
QUALITY_RE = re.compile(
    r"(interval|tempo|threshold|speed|reps|\bmp\b|marathon pace|race pace|canova|"
    r"progression|hills?\b|fartlek|vo2|\bpush\b|\d+\s*x\s*\d+)",
    re.IGNORECASE,
)


def is_race_title(title: str) -> bool:
    """True when the title names an actual race or time trial."""
    title = title or ""
    return bool(RACE_RE.search(title)) and not NOT_RACE_RE.search(title)


def is_quality_title(title: str) -> bool:
    """True for races and structured intensity sessions (intervals, tempo, reps, ...)."""
    title = title or ""
    return is_race_title(title) or bool(QUALITY_RE.search(title))
