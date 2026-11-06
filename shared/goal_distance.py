"""Goal distance classification, distance profiles, target time parsing and peak CTL reference ranges."""

import re
from typing import Any, Optional

# Peak CTL targets per distance follow the Coggan/Friel PMC methodology.
DEFAULT_PEAK_RANGE = (55.0, 70.0)
DEFAULT_PEAK_CTL = 65.0

# Per-distance profiles: goal km, typical race HR as a fraction of LTHR, minimum
# goal-pace segment length, threshold->race speed ratio per durability tier, and
# what counts as a "long run" for that distance.
DISTANCE_PROFILES: dict[str, dict[str, Any]] = {
    "5K": {"km": 5.0, "race_hr": 1.03, "min_seg_s": 120, "long_km": 12.0,
           "ratios": {"strong": 1.07, "moderate": 1.07, "weak": 1.07}},
    "10K": {"km": 10.0, "race_hr": 1.00, "min_seg_s": 240, "long_km": 14.0,
            "ratios": {"strong": 1.025, "moderate": 1.025, "weak": 1.025}},
    "10 Mile": {"km": 16.0934, "race_hr": 0.97, "min_seg_s": 480, "long_km": 16.0,
                "ratios": {"strong": 0.985, "moderate": 0.985, "weak": 0.975}},
    "Half Marathon": {"km": 21.0975, "race_hr": 0.95, "min_seg_s": 480, "long_km": 18.0,
                      "ratios": {"strong": 0.97, "moderate": 0.97, "weak": 0.955}},
    "Marathon": {"km": 42.195, "race_hr": 0.89, "min_seg_s": 600, "long_km": 20.0,
                 "ratios": {"strong": 0.93, "moderate": 0.91, "weak": 0.88}},
}

# Goal distance patterns, most specific first ("half marathon" must match
# before "marathon", "10 mile" before "10k"). Word boundaries stop "15k"
# from matching "5k" and "50min" from matching an ultra.
_DISTANCE_PATTERNS = (
    ("ultra", re.compile(r"\bultra\b|\b(50|100)\s?(k|km|mi|miles?)\b")),
    ("half", re.compile(r"\bhalf\b|\b21(\.1)?\s?km?\b")),
    ("10mi", re.compile(r"\b(10|ten)[\s-]?mi(les?)?\b|\b16(\.1)?\s?km?\b")),
    ("marathon", re.compile(r"\bmarathon\b|\b42(\.2)?\s?km?\b")),
    ("10k", re.compile(r"\b10\s?km?\b")),
    ("5k", re.compile(r"\b5\s?km?\b")),
)

# Supported goal races -> label used by DISTANCE_PROFILES.
GOAL_LABELS = {
    "5k": "5K",
    "10k": "10K",
    "10mi": "10 Mile",
    "half": "Half Marathon",
    "marathon": "Marathon",
}


def goal_distance_key(text: str) -> Optional[str]:
    """Classifies a goal string into a distance key, or None."""
    text = str(text or "").lower()
    for key, pattern in _DISTANCE_PATTERNS:
        if pattern.search(text):
            return key
    return None


def resolve_goal_distance(goal_text: Optional[str]) -> Optional[str]:
    """Returns the goal-race label (e.g. 'Half Marathon') for supported goals, else None."""
    return GOAL_LABELS.get(goal_distance_key(goal_text or ""))


def parse_target_time_minutes(goal_text: Optional[str]) -> Optional[float]:
    """Extracts the target race finish time in minutes from a goal string.

    'A:BB' is read as MM:SS when A >= 10 (no supported race takes 10+ hours)
    and as H:MM otherwise; 'H:MM:SS' is always hours.
    """
    if not goal_text:
        return None
    text = str(goal_text).lower().strip()

    # 1. H:MM:SS, H:MM or MM:SS
    m = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text)
    if m:
        a, b, c = int(m[1]), int(m[2]), m[3]
        if c is not None:
            return a * 60 + b + int(c) / 60
        return a + b / 60 if a >= 10 else a * 60 + b

    # 2. X hours Y minutes format
    m = re.search(r"\b(\d+)\s*(?:hours?|hrs?|h)\s*(?:and\s*)?(?:(\d+)\s*(?:mins?|minutes?|m)?)?\b", text)
    if m:
        h = int(m.group(1))
        mins = int(m.group(2)) if m.group(2) else 0
        return h * 60 + mins

    # 3. X mins format (for 5K/10K)
    m = re.search(r"\b(\d+)\s*(?:mins?|minutes?)\b", text)
    if m:
        return int(m.group(1))

    # 4. sub-XX format (e.g. sub-20, sub-45)
    m = re.search(r"\bsub[- ]?(\d{2})\b", text)
    if m:
        return int(m.group(1))

    return None


def resolve_target_peak_ctl(goal_name: Optional[str]) -> tuple[float, tuple[float, float]]:
    """Dynamically resolves the target peak CTL and reference range based on distance and target time.

    Returns:
        tuple of (target_peak_ctl, (range_low, range_high))
    """
    text = str(goal_name or "").lower().strip()
    mins = parse_target_time_minutes(text)
    key = goal_distance_key(text)

    if key == "ultra":
        return (90.0, (80.0, 110.0))

    # Half marathon is classified BEFORE marathon because 'half marathon' contains 'marathon'
    elif key == "half":
        if mins is not None:
            if mins <= 90:       # <= 1:30 (Competitive)
                return (75.0, (70.0, 85.0))
            elif mins <= 105:    # 1:31 - 1:45 (Strong)
                return (68.0, (60.0, 75.0))
            elif mins <= 120:    # 1:46 - 2:00 (Intermediate)
                return (58.0, (52.0, 65.0))
            else:                # > 2:00 (Novice / Finish)
                return (48.0, (42.0, 55.0))
        return (65.0, (55.0, 75.0))

    elif key == "10mi":
        if mins is not None:
            if mins <= 65:       # <= 1:05 (Competitive)
                return (70.0, (62.0, 78.0))
            elif mins <= 80:     # 1:06 - 1:20 (Intermediate)
                return (60.0, (54.0, 68.0))
            else:                # > 1:20 (Novice / Finish)
                return (50.0, (44.0, 56.0))
        return (60.0, (50.0, 70.0))

    elif key == "marathon":
        if mins is not None:
            if mins <= 180:      # <= 3:00 / 2:45 (Elite / BQ)
                return (95.0, (85.0, 105.0))
            elif mins <= 210:    # 3:01 - 3:30 (Strong Age-Grouper)
                return (80.0, (75.0, 90.0))
            elif mins <= 240:    # 3:31 - 4:00 (Intermediate)
                return (70.0, (65.0, 80.0))
            else:                # > 4:00 (Novice / First-Time Finish)
                return (55.0, (50.0, 65.0))
        return (75.0, (65.0, 85.0))

    elif key == "10k":
        if mins is not None:
            if mins <= 40:
                return (65.0, (60.0, 72.0))
            elif mins <= 50:
                return (55.0, (48.0, 60.0))
            else:
                return (45.0, (40.0, 50.0))
        return (55.0, (45.0, 60.0))

    elif key == "5k":
        if mins is not None:
            if mins <= 20:
                return (60.0, (55.0, 65.0))
            elif mins <= 26:
                return (50.0, (45.0, 55.0))
            else:
                return (40.0, (35.0, 45.0))
        return (50.0, (40.0, 55.0))

    return (DEFAULT_PEAK_CTL, DEFAULT_PEAK_RANGE)
