import logging
import re
from typing import Any, Optional
from .date_helpers import parse_date, get_today_date

logger = logging.getLogger(__name__)

# Target peak CTL recommendations based on Dr. Andrew Coggan and Joe Friel's
# Training Stress Score (TSS) / Performance Management Chart (PMC) methodology.
# Standard reference ranges:
# - 5K/10K: CTL 40-65 (Higher intensity density, moderate volume)
# - Half Marathon: CTL 48-85 (Steady aerobic volume + threshold work)
# - Marathon: CTL 55-105+ (High aerobic volume, long runs 2.5-3.5h)
# - Ultra: CTL 80-110+ (Substantial volume, back-to-back long runs)

DEFAULT_PEAK_RANGE = (55.0, 70.0)
DEFAULT_PEAK_CTL = 65.0

TEN_MILE_KEYWORDS = ("10 mile", "10-mile", "10mi", "10 mi ", "ten mile", "16k", "16.1k")

# Goal race distances: (label, km, TrainingPeaks run PR type).
GOAL_DISTANCES = {
    "5k": ("5K", 5.0, "speed5K"),
    "10k": ("10K", 10.0, "speed10K"),
    "10mi": ("10 Mile", 16.0934, "speed10Mi"),
    "half": ("Half Marathon", 21.0975, "speedHalfMarathon"),
    "marathon": ("Marathon", 42.195, "speedMarathon"),
}


def _goal_distance_key(text: str) -> Optional[str]:
    """Classifies a lowercase goal string into a distance key (order matters)."""
    if any(k in text for k in ["ultra", "50k", "100k", "50m", "100m"]):
        return "ultra"
    # Half before marathon because 'half marathon' contains 'marathon'.
    if any(k in text for k in ["half", "21k", "21.1k"]):
        return "half"
    if any(k in f"{text} " for k in TEN_MILE_KEYWORDS):
        return "10mi"
    if any(k in text for k in ["marathon", "42k", "42.2k"]):
        return "marathon"
    if "10k" in text:
        return "10k"
    if "5k" in text:
        return "5k"
    return None


def resolve_goal_distance(goal_text: Optional[str]) -> Optional[tuple[str, float, str]]:
    """Returns (label, distance_km, pr_type) for supported goal races, else None."""
    key = _goal_distance_key(str(goal_text or "").lower().strip())
    return GOAL_DISTANCES.get(key) if key else None


def parse_target_time_minutes(goal_text: Optional[str]) -> Optional[int]:
    """Extracts target race finish time in total minutes from goal strings.
    
    Examples:
        'Sub-3:30 Marathon' -> 210
        '3:00 Marathon' -> 180
        'Sub-4 hour marathon' -> 240
        '3 hours and 15 mins' -> 195
        'Sub-1:45 Half' -> 105
        'Sub-20 5K' -> 20
        'Sub-45 10K' -> 45
    """
    if not goal_text:
        return None
    text = str(goal_text).lower().strip()
    
    # 1. H:MM(:SS)? format
    m = re.search(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\b", text)
    if m:
        h, mins = int(m.group(1)), int(m.group(2))
        return h * 60 + mins if h > 0 else mins
        
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
    today_date: Optional[Any] = None
) -> dict:
    """Computes quantitative trajectory metrics and required build rates for LLM coaching reasoning."""
    ref_date = parse_date(today_date) or get_today_date()
    goal_name = profile.get("training_goal", "") or "General Fitness"
    timeline_str = profile.get("timeline")
    
    # Resolve dynamic target peak CTL and reference range from training_goal
    target_peak_ctl, ref_range = resolve_target_peak_ctl(goal_name)
    
    weeks_remaining = None
    build_weeks = None
    required_ramp_rate = None
    
    if timeline_str:
        try:
            timeline_date = parse_date(timeline_str)
            if timeline_date:
                days_diff = (timeline_date - ref_date).days
                weeks_remaining = max(0.0, round(days_diff / 7.0, 1))
                
                # Friel/Coggan safe running CTL ramp rate: ~3.0 - 5.0 pts/week (sweet spot 3.5).
                # Accounts for a standard 2-week race taper (build_weeks = weeks_remaining - 2).
                build_weeks = max(0.0, weeks_remaining - 2.0)
                
                # Calculate required weekly CTL build rate to reach target peak before taper
                ctl_deficit = max(0.0, target_peak_ctl - current_ctl)
                if build_weeks > 0:
                    required_ramp_rate = round(ctl_deficit / build_weeks, 2)
                else:
                    required_ramp_rate = 0.0 if ctl_deficit == 0 else round(ctl_deficit, 2)
        except Exception as e:
            logger.warning("Failed to evaluate timeline date '%s': %s", timeline_str, e)

    return {
        "goal_name": goal_name,
        "timeline_date": timeline_str,
        "weeks_remaining": weeks_remaining,
        "build_weeks": build_weeks,
        "target_peak_ctl": target_peak_ctl,
        "reference_range": list(ref_range),
        "current_ctl": current_ctl,
        "required_ramp_rate": required_ramp_rate,
        "safe_ramp_limit": 5.0
    }
