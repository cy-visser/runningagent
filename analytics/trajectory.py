from datetime import datetime, date
from typing import Any, Optional
from ..utils.date_helpers import parse_date, get_today_date

# Target peak CTL recommendations based on endurance event goals
PEAK_CTL_BENCHMARKS = {
    "half": 70.0,
    "21k": 70.0,
    "21.1k": 70.0,
    "marathon": 85.0,
    "ultra": 85.0,
    "10k": 55.0,
    "5k": 55.0,
}
DEFAULT_PEAK_CTL = 65.0

def get_target_peak_ctl(goal_name: str) -> float:
    """Resolves the target peak CTL benchmark based on event goal type."""
    goal_lower = str(goal_name or "").lower()
    for key, target_val in PEAK_CTL_BENCHMARKS.items():
        if key in goal_lower:
            return target_val
    return DEFAULT_PEAK_CTL

def evaluate_goal_trajectory(
    profile: dict,
    current_ctl: float,
    today_date: Optional[Any] = None
) -> dict:
    """Evaluates whether the runner's current CTL is on expected level to achieve their goal by timeline date."""
    ref_date = parse_date(today_date) or get_today_date()
    goal_name = profile.get("training_goal", "") or "General Fitness"
    timeline_str = profile.get("timeline")
    target_peak_ctl = get_target_peak_ctl(goal_name)
    
    weeks_remaining = None
    expected_current_ctl = target_peak_ctl
    status = "ON_TRACK"
    status_label = "🟢 On Track"
    explanation = ""
    
    if timeline_str:
        try:
            timeline_date = parse_date(timeline_str)
            if timeline_date:
                days_diff = (timeline_date - ref_date).days
                weeks_remaining = max(0.0, round(days_diff / 7.0, 1))
                
                # Assuming safe CTL build rate of ~3.5 points per week leading up to a 2-week taper
                build_weeks = max(0.0, weeks_remaining - 2.0)
                expected_current_ctl = max(20.0, target_peak_ctl - (build_weeks * 3.5))
                expected_current_ctl = round(min(expected_current_ctl, target_peak_ctl), 1)
                
                ctl_diff = current_ctl - expected_current_ctl
                if ctl_diff >= -3.0:
                    status = "ON_TRACK"
                    status_label = "🟢 On Track"
                    explanation = f"Current CTL ({current_ctl}) meets or exceeds the expected build target ({expected_current_ctl}) for {weeks_remaining} weeks out."
                elif ctl_diff >= -10.0:
                    status = "SLIGHTLY_BEHIND"
                    status_label = "🟡 Slightly Behind"
                    explanation = f"Current CTL ({current_ctl}) is slightly below the target build level ({expected_current_ctl}). Gradual volume increase recommended."
                else:
                    status = "SIGNIFICANTLY_BEHIND"
                    status_label = "🔴 Significantly Behind"
                    explanation = f"Current CTL ({current_ctl}) is below the required progression ({expected_current_ctl}). Goal adjustment or structured volume build needed."
        except Exception as e:
            print(f"Error evaluating timeline date in evaluate_goal_trajectory: {e}")

    return {
        "goal_name": goal_name,
        "timeline_date": timeline_str,
        "weeks_remaining": weeks_remaining,
        "target_peak_ctl": target_peak_ctl,
        "expected_current_ctl": expected_current_ctl,
        "current_ctl": current_ctl,
        "status": status,
        "status_label": status_label,
        "explanation": explanation
    }
