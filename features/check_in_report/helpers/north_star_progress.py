from datetime import date
from typing import Any, Optional

from ....shared.goal_plan import (
    KIND_NORTH_STAR,
    current_goal,
    north_star,
)
from ....shared.race_equivalents import (
    format_gap,
    goal_target_s,
    north_star_equivalent,
)
from ....shared.units import as_float, format_seconds_hms


def format_projection_vs_north_star(
    profile: Optional[dict], race_projection: Optional[dict], today: Optional[date] = None
) -> str:
    """One line mapping the current block's projected race-day time onto the north star, or ''."""
    ns = north_star(profile)
    projection = (race_projection or {}).get("projection") or {}
    race_day_s = as_float(projection.get("race_day_s"))
    if not ns or not race_day_s:
        return ""
    current = current_goal(profile, today)
    if current["kind"] == KIND_NORTH_STAR:
        return ""
    ns_goal = ns["training_goal"]
    equiv = north_star_equivalent(race_day_s, current["training_goal"], ns_goal)
    if not equiv:
        return ""
    gap = format_gap(equiv - goal_target_s(ns_goal)) if goal_target_s(ns_goal) else "-"
    return (
        f"- Current block projection: {current['training_goal']} race-day {format_seconds_hms(race_day_s)} "
        f"-> north-star equivalent {format_seconds_hms(equiv)} (gap to north star: {gap})."
    )


GOAL_PLAN_POINTER = (
    "- Goal-plan table (sub goals, results, north-star equivalents and gaps): see GOAL PLAN in your "
    "instructions; it is not repeated here."
)


def north_star_progress(profile: dict, race_projection: Optional[dict], today_date: Any) -> str:
    """'North Star Progress' check-in section (goal plans only; reads saved results, never fills them).

    The goal-plan table itself is in the coach instruction on every call, so only the check-in's
    own evidence (the current projection mapped onto the north star) is added here.
    """
    if not north_star(profile):
        return ""
    lines = ["### North Star Progress", GOAL_PLAN_POINTER]
    projection_line = format_projection_vs_north_star(profile, race_projection, today_date)
    if projection_line:
        lines.append(projection_line)
    return "\n".join(lines)
