from datetime import date
from typing import Optional

from ....shared.goal_distance import resolve_goal_distance
from ....shared.goal_plan import KIND_NORTH_STAR, current_goal
from ....shared.long_run_rule import (
    SHARPEN_WEEKS,
    fmt_km,
    long_run_target,
    north_star_label,
    rule_summary,
)

RECENT_VOLUME_WEEKS = 4


def format_trend_long_run_target(
    profile: Optional[dict], today: date, rows: list[dict], easy_pace_s: Optional[float] = None
) -> str:
    """Long-run target line for the trend analysis (same rule as the schedule audit), or ''.

    Uses the mean km of the last complete weeks as the weekly volume and the easy-pace midpoint
    for the duration cap. Gives the build-week range and the sharpening range of the current block.
    """
    goal = current_goal(profile, today)
    label = resolve_goal_distance(goal.get("training_goal"))
    if not label:
        return ""
    ns_label = north_star_label(profile) if goal.get("kind") != KIND_NORTH_STAR else None
    recent = [r["km"] for r in rows if r.get("complete") and r.get("runs")][-RECENT_VOLUME_WEEKS:]
    weekly_km = sum(recent) / len(recent) if recent else None
    build = long_run_target(label, ns_label, weekly_km, easy_pace_s, None)
    sharpen = long_run_target(label, ns_label, weekly_km, easy_pace_s, 1)
    when = "upcoming" if goal.get("before_start") else "current"
    volume = f"{weekly_km:.0f} km/week (mean of the last {len(recent)} complete weeks)" if weekly_km else "no recent volume"
    return (
        f"Long-run target for the {when} {goal['training_goal']} block (shared rule, identical in the schedule "
        f"audit; at {volume}): build weeks {fmt_km(build['low_km'])}-{fmt_km(build['high_km'])} km; "
        f"last {SHARPEN_WEEKS} weeks {fmt_km(sharpen['low_km'])}-{fmt_km(sharpen['high_km'])} km; race week none. "
        f"Rule: {rule_summary(label, ns_label)}. Long-run advice uses only this target, never the pattern split."
    )
