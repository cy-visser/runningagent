"""Goal plans: a single goal race, or a north star with dated sub-goal training blocks."""

from datetime import date, timedelta
from typing import Any, Optional

from .dates import get_today_date, parse_date

GOAL_TYPE_SINGLE = "single"
GOAL_TYPE_PLAN = "plan"

KIND_SINGLE = "single"
KIND_SUB_GOAL = "sub_goal"
KIND_NORTH_STAR = "north_star"


def normalize_timeline(timeline: Optional[str]) -> Optional[str]:
    """Returns the goal date as ISO (YYYY-MM-DD) when parseable, else the raw value."""
    parsed = parse_date(timeline) if timeline else None
    return parsed.isoformat() if parsed else timeline


def is_plan(profile: Optional[dict]) -> bool:
    """True when the runner set a north star with sub goals."""
    return (profile or {}).get("goal_type") == GOAL_TYPE_PLAN


def _iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def race_day(block: dict) -> Optional[date]:
    return parse_date(block.get("timeline"))


def _block(kind: str, data: dict, index: Optional[int] = None, start: Optional[str] = None) -> dict:
    return {
        "kind": kind,
        "index": index,
        "training_goal": data.get("goal"),
        "race_name": data.get("race_name"),
        "goal_set_date": start or data.get("start_date"),
        "timeline": data.get("race_date"),
        "taper_weeks": data.get("taper_weeks"),
        "result": data.get("result"),
    }


def blocks(profile: Optional[dict]) -> list[dict]:
    """Training blocks of a plan in race order: sub goals, then the north star.

    The north-star block starts on its own start_date, or the day after the last sub-goal race.
    Each sub-goal block keeps `index`, its position in the stored `sub_goals` list.
    """
    if not is_plan(profile):
        return []
    subs = [(i, s) for i, s in enumerate(profile.get("sub_goals") or []) if isinstance(s, dict)]
    subs.sort(key=lambda pair: parse_date(pair[1].get("race_date")) or date.max)
    out = [_block(KIND_SUB_GOAL, s, index=i) for i, s in subs]

    north_star_data = profile.get("north_star") or {}
    if north_star_data:
        start = north_star_data.get("start_date")
        if not start and out:
            last_race = race_day(out[-1])
            start = _iso(last_race + timedelta(days=1)) if last_race else None
        out.append(_block(KIND_NORTH_STAR, north_star_data, start=start))
    return out


def current_goal(profile: Optional[dict], today: Optional[date] = None) -> dict:
    """The goal that drives training now, with single-goal profile keys.

    Single goal: the profile's own fields. Plan: the first block whose race is today or
    later (the last block once every race has passed). `before_start` is True between
    blocks, i.e. before the active block's start date.
    """
    profile = profile or {}
    today = today or get_today_date()
    all_blocks = blocks(profile)
    if not all_blocks:
        return {
            "kind": KIND_SINGLE,
            "index": None,
            "training_goal": profile.get("training_goal"),
            "race_name": None,
            "goal_set_date": profile.get("goal_set_date"),
            "timeline": profile.get("timeline"),
            "taper_weeks": profile.get("taper_weeks"),
            "result": None,
            "before_start": False,
        }
    active = next((b for b in all_blocks if (race_day(b) or date.max) >= today), all_blocks[-1])
    start = parse_date(active["goal_set_date"])
    return {**active, "before_start": bool(start and today < start)}


def goal_race_dates(profile: Optional[dict]) -> set[date]:
    """Race days of every goal: the single goal's timeline, or each sub goal and the north star."""
    profile = profile or {}
    if is_plan(profile):
        days = {race_day(b) for b in blocks(profile)}
    else:
        days = {parse_date(profile.get("timeline"))}
    return {d for d in days if d}


def north_star(profile: Optional[dict]) -> Optional[dict]:
    """The north-star block of a plan, or None."""
    all_blocks = blocks(profile)
    if all_blocks and all_blocks[-1]["kind"] == KIND_NORTH_STAR:
        return all_blocks[-1]
    return None


def final_race_passed(profile: Optional[dict], today: Optional[date] = None) -> Optional[dict]:
    """The final goal (single goal or north star) when its race date is in the past, else None.

    Sub-goal races never count: they are steps of the plan, not its end.
    """
    today = today or get_today_date()
    goal = current_goal(profile, today)
    if goal["kind"] == KIND_SUB_GOAL:
        return None
    r_day = race_day(goal)
    return goal if r_day and today > r_day else None


def sub_goals_missing_result(profile: Optional[dict], today: Optional[date] = None) -> list[dict]:
    """Sub-goal blocks whose race date has passed but that have no saved result."""
    today = today or get_today_date()
    return [
        b for b in blocks(profile)
        if b["kind"] == KIND_SUB_GOAL and not b["result"]
        and (race_day(b) or date.max) < today
    ]


def sub_goal_for_date(profile: Optional[dict], day: Any) -> Optional[dict]:
    """The sub-goal block whose race is on `day`, or None."""
    target = parse_date(day)
    if not target:
        return None
    return next(
        (b for b in blocks(profile) if b["kind"] == KIND_SUB_GOAL and race_day(b) == target),
        None,
    )


def next_block(profile: Optional[dict], block: dict) -> Optional[dict]:
    """The block after `block` in race order, or None."""
    all_blocks = blocks(profile)
    for i, b in enumerate(all_blocks):
        if b["kind"] == block.get("kind") and b["index"] == block.get("index") \
                and b["timeline"] == block.get("timeline"):
            return all_blocks[i + 1] if i + 1 < len(all_blocks) else None
    return None
