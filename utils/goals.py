"""Goal plans: a single goal race, or a north star with dated sub-goal training blocks.

Pure helpers (no I/O). Firestore profile shapes:

- single (``goal_type`` 'single' or missing): ``training_goal``, ``timeline``,
  ``goal_set_date``, ``taper_weeks``.
- plan (``goal_type`` 'plan'):
  ``north_star`` = {goal, race_name, start_date, race_date, taper_weeks} and
  ``sub_goals`` = [{goal, race_name, start_date, race_date, taper_weeks, result}], where
  ``result`` = {time, time_s, workout_id} once the sub-goal race has been analysed.

``current_goal`` returns the active block with the same keys as a single-goal profile
(training_goal, timeline, goal_set_date, taper_weeks), so the trajectory and race
projection maths work unchanged for both goal types.
"""

from datetime import date, timedelta
from typing import Any, Optional

from .classification import RUN_SPORTS
from .date_helpers import get_today_date, parse_date
from .race_prediction import format_seconds_hms, riegel_predict
from .race_readiness import DISTANCE_PROFILES
from .trajectory import parse_target_time_minutes, resolve_goal_distance, resolve_target_peak_ctl

GOAL_TYPE_SINGLE = "single"
GOAL_TYPE_PLAN = "plan"

KIND_SINGLE = "single"
KIND_SUB_GOAL = "sub_goal"
KIND_NORTH_STAR = "north_star"


def is_plan(profile: Optional[dict]) -> bool:
    """True when the runner set a north star with sub goals."""
    return (profile or {}).get("goal_type") == GOAL_TYPE_PLAN


def _iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def _to_float(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _race_day(block: dict) -> Optional[date]:
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

    north_star = profile.get("north_star") or {}
    if north_star:
        start = north_star.get("start_date")
        if not start and out:
            last_race = _race_day(out[-1])
            start = _iso(last_race + timedelta(days=1)) if last_race else None
        out.append(_block(KIND_NORTH_STAR, north_star, start=start))
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
    active = next((b for b in all_blocks if (_race_day(b) or date.max) >= today), all_blocks[-1])
    start = parse_date(active["goal_set_date"])
    return {**active, "before_start": bool(start and today < start)}


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
    race_day = _race_day(goal)
    return goal if race_day and today > race_day else None


def sub_goals_missing_result(profile: Optional[dict], today: Optional[date] = None) -> list[dict]:
    """Sub-goal blocks whose race date has passed but that have no saved result."""
    today = today or get_today_date()
    return [
        b for b in blocks(profile)
        if b["kind"] == KIND_SUB_GOAL and not b["result"]
        and (_race_day(b) or date.max) < today
    ]


def sub_goal_for_date(profile: Optional[dict], day: Any) -> Optional[dict]:
    """The sub-goal block whose race is on `day`, or None."""
    target = parse_date(day)
    if not target:
        return None
    return next(
        (b for b in blocks(profile) if b["kind"] == KIND_SUB_GOAL and _race_day(b) == target),
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


def race_duration_s(workout_meta: Optional[dict], analysis: Optional[dict]) -> Optional[float]:
    """Finish time in seconds of an analysed workout (TP `duration_actual` hours, else totals)."""
    hours = _to_float((workout_meta or {}).get("duration_actual"))
    if hours and hours > 0:
        return hours * 3600.0
    totals = (analysis or {}).get("totals") or {}
    seconds = _to_float(totals.get("Duration"))
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


def _equivalent_cell(time_s: Optional[float], goal: Optional[str], ns_goal: Optional[str]) -> str:
    if not time_s:
        return "-"
    equiv = north_star_equivalent(time_s, goal, ns_goal)
    return f"{format_seconds_hms(time_s)} -> {format_seconds_hms(equiv)}" if equiv else format_seconds_hms(time_s)


def _gap_cell(time_s: Optional[float], goal: Optional[str], ns_goal: Optional[str], ns_target_s: Optional[float]) -> str:
    equiv = north_star_equivalent(time_s, goal, ns_goal)
    return format_gap(equiv - ns_target_s) if equiv and ns_target_s else "-"


def format_goal_plan(profile: Optional[dict], today: Optional[date] = None) -> str:
    """Goal-plan block for the coach instruction and the check-in. '' for single goals."""
    ns = north_star(profile)
    if not ns:
        return ""
    today = today or get_today_date()
    current = current_goal(profile, today)
    ns_goal = ns["training_goal"]
    ns_target_s = goal_target_s(ns_goal)
    ns_race = _race_day(ns)

    weeks = f", {max(0, (ns_race - today).days) / 7:.0f} weeks away" if ns_race else ""
    race_name = f" ({ns['race_name']})" if ns.get("race_name") else ""
    lines = [
        "GOAL PLAN (north star with sub goals):",
        f"- North star: {ns_goal}{race_name}, race {ns['timeline']}{weeks}; "
        f"marathon-block start {ns['goal_set_date'] or 'not set'}.",
        "- Sub goals (each a full training block; results are progress toward the north star, "
        "never pass/fail). Times shown as 'time -> north-star equivalent' (Riegel):",
        "",
        "| Sub goal | Block | Status | Target | Result | Result gap to north star |",
        "|---|---|---|---|---|---|",
    ]
    for b in blocks(profile):
        if b["kind"] != KIND_SUB_GOAL:
            continue
        race_day = _race_day(b)
        if b["index"] == current["index"] and current["kind"] == KIND_SUB_GOAL:
            status = "upcoming (next block)" if current["before_start"] else "active"
        elif race_day and race_day < today:
            status = "done"
        else:
            status = "upcoming"
        result_s = _to_float((b["result"] or {}).get("time_s"))
        if result_s:
            result = _equivalent_cell(result_s, b["training_goal"], ns_goal)
        elif status == "done":
            result = "missing: ask the runner"
        else:
            result = "-"
        lines.append(
            f"| {b['training_goal']} | {b['goal_set_date']} -> {b['timeline']} | {status} | "
            f"{_equivalent_cell(goal_target_s(b['training_goal']), b['training_goal'], ns_goal)} | "
            f"{result} | {_gap_cell(result_s, b['training_goal'], ns_goal, ns_target_s)} |"
        )

    lines.append("")
    if current["kind"] == KIND_NORTH_STAR:
        lines.append(f"- Current block: the north-star block ({ns_goal}).")
    else:
        lines.append(f"- Current block: {current['training_goal']}, race {current['timeline']}.")
    if current["before_start"]:
        lines.append(
            f"- Between blocks: the next block starts {current['goal_set_date']}; "
            "treat this period as recovery/transition."
        )
    _, (lo, hi) = resolve_target_peak_ctl(ns_goal)
    lines.append(f"- North-star peak CTL reference range: {lo:.0f}-{hi:.0f} (context for aerobic base).")
    return "\n".join(lines)


def format_projection_vs_north_star(profile: Optional[dict], race_projection: Optional[dict], today: Optional[date] = None) -> str:
    """One line mapping the current block's projected race-day time onto the north star, or ''."""
    ns = north_star(profile)
    projection = (race_projection or {}).get("projection") or {}
    race_day_s = _to_float(projection.get("race_day_s"))
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
