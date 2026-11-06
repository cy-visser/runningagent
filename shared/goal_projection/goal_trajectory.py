from datetime import timedelta
import logging
from typing import Any, Optional

from ..dates import get_today_date, parse_date
from ..goal_distance import goal_distance_key, resolve_target_peak_ctl
from ..goal_plan import current_goal
from ..tp_payloads import parse_mcp_response

logger = logging.getLogger(__name__)

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
    return TAPER_WEEKS_BY_DISTANCE.get(goal_distance_key(goal_text or ""), TAPER_WEEKS)


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


def summarize_fitness(
    fitness_raw: Any, profile: dict, today_date: Any, window_start: Any = None
) -> Optional[dict]:
    """Extracts PMC start/end values and the resulting goal trajectory.

    When window_start is given, start/end bounds and daily_list cover only the
    check-in window; the full PMC series is kept under 'history'.
    """
    if not fitness_raw:
        return None

    fit_parsed = parse_mcp_response(fitness_raw) or {}
    history = fit_parsed.get("daily_data", [])
    if not isinstance(history, list):
        history = []

    window_date = parse_date(window_start)
    fitness_list = [
        d for d in history
        if window_date is None or (parse_date(d.get("date")) or window_date) >= window_date
    ]

    bounds = {f"{m}_{edge}": 0.0 for m in ("ctl", "atl", "tsb") for edge in ("start", "end")}
    if fitness_list:
        ordered = sorted(fitness_list, key=lambda x: str(x.get("date", "")))
        for metric in ("ctl", "atl", "tsb"):
            bounds[f"{metric}_start"] = ordered[0].get(metric, 0.0)
            bounds[f"{metric}_end"] = ordered[-1].get(metric, 0.0)

    return {
        **bounds,
        "daily_list": fitness_list,
        "history": history,
        "trajectory_info": evaluate_goal_trajectory(
            current_goal(profile, parse_date(today_date)), bounds["ctl_end"], today_date, daily_pmc=history
        ),
    }
