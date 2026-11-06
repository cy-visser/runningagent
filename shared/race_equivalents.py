"""Riegel race-time equivalence and north-star gap calculations."""

from typing import Optional

from .goal_distance import DISTANCE_PROFILES, parse_target_time_minutes, resolve_goal_distance
from .units import format_seconds_hms

RIEGEL_EXPONENT = 1.06


def riegel_predict(time_s: float, from_km: float, to_km: float) -> float:
    """Riegel: T2 = T1 * (D2 / D1) ** 1.06."""
    return time_s * (to_km / from_km) ** RIEGEL_EXPONENT


def goal_km(goal_text: Optional[str]) -> Optional[float]:
    """Race distance in km for a goal string ('Sub-21 5K' -> 5.0), or None."""
    label = resolve_goal_distance(goal_text)
    return DISTANCE_PROFILES[label]["km"] if label in DISTANCE_PROFILES else None


def goal_target_s(goal_text: Optional[str]) -> Optional[float]:
    """Target finish time in seconds from a goal string, or None."""
    minutes = parse_target_time_minutes(goal_text)
    return minutes * 60.0 if minutes else None


def north_star_equivalent(time_s: Optional[float], from_goal: Optional[str], to_goal: Optional[str]) -> Optional[float]:
    """Riegel-equivalent time over the north-star distance for a time over `from_goal`'s distance."""
    from_km, to_km = goal_km(from_goal), goal_km(to_goal)
    if not time_s or not from_km or not to_km:
        return None
    return riegel_predict(time_s, from_km, to_km)


def format_gap(delta_s: Optional[float]) -> str:
    """'+6:30 slower' / '-1:05 faster' / 'on target' for an equivalent-minus-target delta."""
    if delta_s is None:
        return "-"
    if abs(delta_s) < 1:
        return "on target"
    sign, word = ("+", "slower") if delta_s > 0 else ("-", "faster")
    return f"{sign}{format_seconds_hms(abs(delta_s))} {word}"
