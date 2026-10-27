import logging
import re
from datetime import timedelta
from typing import Any, Optional
from .date_helpers import parse_date, get_today_date

logger = logging.getLogger(__name__)

# Peak CTL targets per distance follow the Coggan/Friel PMC methodology.

DEFAULT_PEAK_RANGE = (55.0, 70.0)
DEFAULT_PEAK_CTL = 65.0
# Pre-race taper excluded from the CTL build window. Distance defaults follow
# common practice (Pfitzinger / Daniels / Hudson); TAPER_WEEKS is the fallback
# when the goal distance is unknown. A profile `taper_weeks` overrides both.
TAPER_WEEKS = 2.0
TAPER_WEEKS_BY_DISTANCE = {
    "ultra": 3.0,
    "marathon": 3.0,
    "half": 2.0,
    "10mi": 2.0,
    "10k": 1.0,
    "5k": 1.0,
}
# CTL can't be meaningfully built in a partial week: floor the ramp divisor.
MIN_BUILD_WEEKS = 1.0
# Weekly CTL ramp tiers (pts/week): <= SAFE is sustainable, <= MAX is aggressive, above is high risk.
SAFE_RAMP_PER_WEEK = 3.5
MAX_RAMP_PER_WEEK = 5.0
# Banked fitness: peak CTL from this many days before the taper start up to today.
PRE_TAPER_PEAK_WINDOW_DAYS = 7


def peak_ctl(daily_pmc: Optional[list[dict]], start: Any, end: Any) -> Optional[float]:
    """Highest CTL in [start, end] from PMC daily data, or None."""
    best = None
    for entry in daily_pmc or []:
        d = parse_date(entry.get("date"))
        if d is None or not (start <= d <= end):
            continue
        try:
            val = float(entry.get("ctl"))
        except (TypeError, ValueError):
            continue
        best = val if best is None else max(best, val)
    return best


def ramp_status(required_ramp_rate: Optional[float]) -> Optional[str]:
    """Status badge for a required weekly CTL ramp rate (single source for the check-in tiers)."""
    if required_ramp_rate is None:
        return None
    if required_ramp_rate <= SAFE_RAMP_PER_WEEK:
        return f"🟢 safe (<= {SAFE_RAMP_PER_WEEK})"
    if required_ramp_rate <= MAX_RAMP_PER_WEEK:
        return f"🟡 aggressive ({SAFE_RAMP_PER_WEEK}-{MAX_RAMP_PER_WEEK})"
    return f"🔴 high risk (> {MAX_RAMP_PER_WEEK})"

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

# Supported goal races -> label used by the race-readiness DISTANCE_PROFILES.
GOAL_LABELS = {
    "5k": "5K",
    "10k": "10K",
    "10mi": "10 Mile",
    "half": "Half Marathon",
    "marathon": "Marathon",
}


def _goal_distance_key(text: str) -> Optional[str]:
    """Classifies a goal string into a distance key, or None."""
    text = str(text or "").lower()
    for key, pattern in _DISTANCE_PATTERNS:
        if pattern.search(text):
            return key
    return None


def resolve_goal_distance(goal_text: Optional[str]) -> Optional[str]:
    """Returns the goal-race label (e.g. 'Half Marathon') for supported goals, else None."""
    return GOAL_LABELS.get(_goal_distance_key(goal_text or ""))


def resolve_taper_weeks(goal_text: Optional[str], override: Any = None) -> float:
    """Taper length in weeks: a valid profile override, else the goal-distance default."""
    if override not in (None, ""):
        try:
            value = float(override)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
        logger.warning("Ignoring invalid taper_weeks '%s'", override)
    return TAPER_WEEKS_BY_DISTANCE.get(_goal_distance_key(goal_text or ""), TAPER_WEEKS)


def parse_target_time_minutes(goal_text: Optional[str]) -> Optional[float]:
    """Extracts the target race finish time in minutes from a goal string.

    'A:BB' is read as MM:SS when A >= 10 (no supported race takes 10+ hours)
    and as H:MM otherwise; 'H:MM:SS' is always hours.

    Examples:
        'Sub-3:30 Marathon' -> 210
        'Sub-19:30 5K' -> 19.5
        '3:15:00 Marathon' -> 195
        'Sub-4 hour marathon' -> 240
        '3 hours and 15 mins' -> 195
        'Sub-20 5K' -> 20
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
    key = _goal_distance_key(text)
    
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


def evaluate_goal_trajectory(
    profile: dict,
    current_ctl: float,
    today_date: Optional[Any] = None,
    daily_pmc: Optional[list[dict]] = None,
) -> dict:
    """Computes quantitative trajectory metrics and required build rates for LLM coaching reasoning.

    phase is "build" (ramp toward the target peak) or "taper" (fitness is banked:
    no ramp; progress is judged on pre_taper_ctl, the CTL on the day before the
    taper started, since CTL is expected to decline during the taper).
    """
    ref_date = parse_date(today_date) or get_today_date()
    timeline_str = profile.get("timeline")

    target_peak_ctl, ref_range = resolve_target_peak_ctl(profile.get("training_goal"))
    taper_weeks = resolve_taper_weeks(profile.get("training_goal"), profile.get("taper_weeks"))

    weeks_remaining = None
    build_weeks = None
    required_ramp_rate = None
    phase = None
    pre_taper_ctl = None

    timeline_date = parse_date(timeline_str) if timeline_str else None
    if timeline_str and not timeline_date:
        logger.warning("Could not parse timeline date '%s'", timeline_str)
    if timeline_date:
        days_diff = (timeline_date - ref_date).days
        weeks_remaining = max(0.0, round(days_diff / 7.0, 1))
        # Build until the pre-race taper starts.
        build_weeks = max(0.0, round(weeks_remaining - taper_weeks, 1))

        if build_weeks <= 0:
            # In the taper: hold fitness and shed fatigue; no CTL build is required.
            phase = "taper"
            taper_start = timeline_date - timedelta(days=round(taper_weeks * 7))
            window_start = taper_start - timedelta(days=PRE_TAPER_PEAK_WINDOW_DAYS)
            pre_taper_ctl = peak_ctl(daily_pmc, window_start, ref_date)
            pre_taper_ctl = max(pre_taper_ctl or 0.0, current_ctl or 0.0)
        else:
            phase = "build"
            # Required weekly CTL build rate to reach the target peak before the taper
            ctl_deficit = max(0.0, target_peak_ctl - current_ctl)
            required_ramp_rate = round(ctl_deficit / max(build_weeks, MIN_BUILD_WEEKS), 2)

    return {
        "weeks_remaining": weeks_remaining,
        "build_weeks": build_weeks,
        "taper_weeks": taper_weeks,
        "phase": phase,
        "pre_taper_ctl": pre_taper_ctl,
        "target_peak_ctl": target_peak_ctl,
        "reference_range": list(ref_range),
        "required_ramp_rate": required_ramp_rate,
    }
