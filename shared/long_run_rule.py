"""Long-run target rule shared by the schedule audit and the trend analysis."""

import math
from datetime import date, timedelta
from typing import Optional

from .goal_distance import DISTANCE_PROFILES, resolve_goal_distance
from .goal_plan import north_star

LONG_RUN_SHARE = (0.25, 0.30)
SHORT_GOAL_CAP_MIN = 110
DEFAULT_CAP_MIN = 150
SHORT_GOALS = frozenset({"5K", "10K"})
NORTH_STAR_FLOOR_KM = 16.0
LONG_NORTH_STARS = frozenset({"Half Marathon", "Marathon"})
SHARPEN_WEEKS = 2

PHASE_TRANSITION = "transition"
PHASE_BUILD = "build"
PHASE_SHARPENING = "sharpening"
PHASE_RACE_WEEK = "race week"
PHASE_POST_RACE = "post-race"

FLAG_OK = "✓ on target"
FLAG_BELOW_FLOOR = "⚠ below north-star floor"
FLAG_BELOW = "⚠ below target"
FLAG_ABOVE = "⚠ above target"
FLAG_NO_RUNS = "no runs"


def _half_km(value: float) -> float:
    """Rounds to the nearest 0.5 km (halves round up)."""
    return math.floor(value * 2 + 0.5) / 2


def fmt_km(value: float) -> str:
    return f"{value:g}"


def cap_minutes(goal_label: Optional[str]) -> int:
    return SHORT_GOAL_CAP_MIN if goal_label in SHORT_GOALS else DEFAULT_CAP_MIN


def long_run_target(
    goal_label: Optional[str],
    north_star_label: Optional[str] = None,
    weekly_km: Optional[float] = None,
    pace_s_per_km: Optional[float] = None,
    weeks_to_race: Optional[int] = None,
) -> Optional[dict]:
    """Long-run range for one week, or None when the goal distance is unsupported."""
    if goal_label not in DISTANCE_PROFILES:
        return None
    if weeks_to_race == 0:
        return {"low_km": None, "high_km": None, "floor_km": None, "cap_km": None,
                "north_star_floor": False, "phase": PHASE_RACE_WEEK,
                "rationale": "race week: no long-run requirement"}

    sharpening = weeks_to_race is not None and 0 < weeks_to_race <= SHARPEN_WEEKS
    goal_floor = DISTANCE_PROFILES[goal_label]["long_km"]
    protect = north_star_label in LONG_NORTH_STARS and not sharpening and NORTH_STAR_FLOOR_KM > goal_floor
    floor = NORTH_STAR_FLOOR_KM if protect else goal_floor

    km = weekly_km or 0.0
    low, high = (LONG_RUN_SHARE[0] * km, LONG_RUN_SHARE[1] * km) if km > 0 else (floor, floor)
    cap_min = cap_minutes(goal_label)
    cap_km = cap_min * 60 / pace_s_per_km if pace_s_per_km and pace_s_per_km > 0 else None
    if cap_km:
        high = min(high, cap_km)
        low = min(low, high)
    if sharpening:
        high = min(high, max(floor, NORTH_STAR_FLOOR_KM))
        low = floor
    low = max(low, floor)
    high = max(high, low)

    parts = [f"{int(LONG_RUN_SHARE[0] * 100)}-{int(LONG_RUN_SHARE[1] * 100)}% of {km:.0f} km"
             if km > 0 else "no weekly volume: floor only"]
    parts.append(f"floor {fmt_km(floor)} km" + (" (north-star protection)" if protect else f" ({goal_label})"))
    if cap_km:
        parts.append(f"cap {cap_min} min ≈ {cap_km:.1f} km")
    if sharpening:
        parts.append(f"sharpening: max {fmt_km(max(floor, NORTH_STAR_FLOOR_KM))} km")
    return {
        "low_km": _half_km(low), "high_km": _half_km(high), "floor_km": floor,
        "cap_km": round(cap_km, 1) if cap_km else None, "north_star_floor": protect,
        "phase": PHASE_SHARPENING if sharpening else PHASE_BUILD, "rationale": "; ".join(parts),
    }


def long_run_flag(long_km: Optional[float], target: Optional[dict], runs: int = 1) -> Optional[str]:
    """Verdict of a week's longest run against its target (None when there is no range)."""
    if not target or target["low_km"] is None:
        return None
    if not runs:
        return FLAG_NO_RUNS
    km = long_km or 0.0
    if km < target["low_km"] - 0.25:            # tolerance: half the 0.5 km rounding step
        return FLAG_BELOW_FLOOR if target["north_star_floor"] and km < target["floor_km"] else FLAG_BELOW
    if km > target["high_km"] + 0.25:
        return FLAG_ABOVE
    return FLAG_OK


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def north_star_label(profile: Optional[dict]) -> Optional[str]:
    ns = north_star(profile)
    return resolve_goal_distance(ns["training_goal"]) if ns else None


def rule_summary(goal_label: str, ns_label: Optional[str]) -> str:
    """One-line description of the long-run rule for this block."""
    goal_floor = DISTANCE_PROFILES[goal_label]["long_km"]
    floor = f"floor {fmt_km(goal_floor)} km ({goal_label})"
    if ns_label in LONG_NORTH_STARS and NORTH_STAR_FLOOR_KM > goal_floor:
        floor += f", raised to {fmt_km(NORTH_STAR_FLOOR_KM)} km to protect the {ns_label} north star"
    return (f"{int(LONG_RUN_SHARE[0] * 100)}-{int(LONG_RUN_SHARE[1] * 100)}% of the week's running km; {floor}; "
            f"cap {cap_minutes(goal_label)} min; last {SHARPEN_WEEKS} weeks before the race: "
            f"{fmt_km(goal_floor)}-{fmt_km(max(goal_floor, NORTH_STAR_FLOOR_KM))} km; race week: no long run")
