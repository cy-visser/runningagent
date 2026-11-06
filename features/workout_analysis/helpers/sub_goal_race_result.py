import logging
from typing import Any, Optional

from google.adk.tools import ToolContext

from ....integrations import firestore
from ....shared.dates import parse_date
from ....shared.goal_plan import (
    KIND_NORTH_STAR,
    current_goal,
    is_plan,
    north_star,
    sub_goal_for_date,
)
from ....shared.race_equivalents import (
    format_gap,
    goal_target_s,
    north_star_equivalent,
)
from ....shared.runner_identity import profile_user_id
from ....shared.sports import RUN_SPORTS
from ....shared.units import as_float, format_seconds_hms

logger = logging.getLogger(__name__)


def race_duration_s(workout_meta: Optional[dict], analysis: Optional[dict]) -> Optional[float]:
    """Finish time in seconds of an analysed workout (TP `duration_actual` hours, else totals)."""
    hours = as_float((workout_meta or {}).get("duration_actual"))
    if hours and hours > 0:
        return hours * 3600.0
    totals = (analysis or {}).get("totals") or {}
    seconds = as_float(totals.get("Duration"))
    return seconds if seconds and seconds > 0 else None


def race_result_update(
    profile: Optional[dict],
    workout_date: Any,
    duration_s: Optional[float],
    workout_id: Any,
    sport: Optional[str] = None,
) -> Optional[dict]:
    """Firestore update {'sub_goals': [...]} saving a sub-goal race result, or None.

    Returns None unless the profile is a plan, the workout is a run (when `sport` is given)
    and `workout_date` is a sub-goal race date. Re-analysing the race replaces the result
    with the same workout's data.
    """
    if not is_plan(profile) or not duration_s or duration_s <= 0:
        return None
    if sport and sport.strip().lower() not in RUN_SPORTS:
        return None
    block = sub_goal_for_date(profile, workout_date)
    if not block:
        return None
    sub_goals = [dict(s) if isinstance(s, dict) else s for s in profile.get("sub_goals") or []]
    sub_goals[block["index"]]["result"] = {
        "time": format_seconds_hms(duration_s),
        "time_s": round(duration_s),
        "workout_id": str(workout_id or ""),
    }
    return {"sub_goals": sub_goals}


def format_workout_goal_context(
    profile: Optional[dict], workout_date: Any, duration_s: Optional[float], result_saved: bool
) -> str:
    """Goal-plan context for a workout analysis. '' for single goals.

    On a sub-goal race day: the result, its north-star equivalent and gap. Otherwise a one-line
    reference to the current block and the north star.
    """
    ns = north_star(profile)
    if not ns:
        return ""
    ns_goal = ns["training_goal"]
    block = sub_goal_for_date(profile, workout_date)
    if not block:
        current = current_goal(profile, parse_date(workout_date))
        if current["kind"] == KIND_NORTH_STAR:
            return f"**Goal plan:** north-star block ({ns_goal}, race {ns['timeline']})."
        return (
            f"**Goal plan:** current block {current['training_goal']} (race {current['timeline']}) "
            f"-> north star {ns_goal} (race {ns['timeline']})."
        )
    equiv = north_star_equivalent(duration_s, block["training_goal"], ns_goal)
    target_s = goal_target_s(ns_goal)
    parts = [
        f"**Sub-goal race ({block['training_goal']}):** finish time {format_seconds_hms(duration_s)}",
    ]
    if equiv:
        parts.append(f"north-star equivalent {format_seconds_hms(equiv)} for {ns_goal}")
        if target_s:
            parts.append(f"gap to north star {format_gap(equiv - target_s)}")
    line = "; ".join(parts) + "."
    if result_saved:
        line += " Result saved to the runner's goal plan."
    return line


async def goal_plan_context(
    tool_context: ToolContext, profile: dict, workout_date: Any, workout_id: str, sport: Any,
    meta: dict, data: dict,
) -> str:
    """Goal-plan line for a workout analysis; saves the result when this is a sub-goal race."""
    if not is_plan(profile):
        return ""
    duration_s = race_duration_s(meta, data)
    update = race_result_update(profile, workout_date, duration_s, workout_id, sport=sport)
    saved = False
    if update:
        user_id = profile_user_id(profile)
        try:
            if not user_id:
                raise ValueError("no runner name in profile")
            await firestore.update_user_profile(user_id, update)
            tool_context.state["user_profile"] = {**profile, **update}
            saved = True
        except Exception as e:
            logger.error("Failed to save sub-goal race result for %s: %s", user_id, e)
    return format_workout_goal_context(profile, workout_date, duration_s, saved)
