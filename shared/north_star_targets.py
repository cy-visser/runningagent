"""North-star targets shared by the trend analysis and the schedule audit.

Peak weekly km per half / marathon north star (by target time) and the per-week running-volume target of
each training block. Long-run distance has no computed target: the coach reasons it from the facts.
"""

import math
from datetime import date, timedelta
from typing import Optional

from .dates import monday_of, parse_date
from .goal_distance import parse_target_time_minutes, resolve_goal_distance
from .goal_plan import KIND_SUB_GOAL, blocks, current_goal, north_star, race_day
from .weekly_buckets import build_week_buckets
from .workout_status import is_workout_completed

LONG_LABELS = frozenset({"Half Marathon", "Marathon"})

PHASE_TRANSITION = "transition"
PHASE_BUILD = "build"
PHASE_TAPER = "taper"
PHASE_RECOVERY = "recovery"
PHASE_RACE_WEEK = "race week"
PHASE_POST_RACE = "post-race"

# (max target minutes or None for slower / no time, peak weekly km), fastest tier first.
NS_PEAK_TABLE: dict[str, tuple[tuple[Optional[int], int], ...]] = {
    "Marathon": ((180, 110), (200, 100), (225, 85), (255, 70), (None, 60)),
    "Half Marathon": ((85, 85), (100, 70), (115, 55), (None, 45)),
}

# Weekly running km of a block as a share of the north-star peak weekly km (the north-star block itself: 1.0).
BLOCK_VOLUME_SHARE = {"5K": 0.65, "10K": 0.72, "10 Mile": 0.80, "Half Marathon": 0.85, "Marathon": 1.00}
BASELINE_WEEKS = 4              # recent complete weeks averaged as the starting level
RECOVERY_EVERY_WEEKS = 4        # every 4th build week of a block is a recovery week ...
RECOVERY_SHARE = 0.80           # ... at this share of that week's path step


def whole_km(value: float) -> int:
    """Rounds to the nearest km (halves round up)."""
    return math.floor(value + 0.5)


def pct_change(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Percentage change from `old` to `new` (1 decimal), or None when `old` has no volume.

    A fact only: whether a change is too steep is the coach's judgement, never a coded limit.
    """
    if not old or old <= 0 or new is None:
        return None
    return round((new / old - 1) * 100, 1)


def ns_peak_weekly_km(goal_text: Optional[str]) -> Optional[int]:
    """Peak weekly km for a half / marathon goal, else None."""
    rows = NS_PEAK_TABLE.get(resolve_goal_distance(goal_text) or "")
    if not rows:
        return None
    mins = parse_target_time_minutes(goal_text)
    row = rows[-1] if mins is None else next(r for r in rows if r[0] is None or mins <= r[0])
    return row[1]


def _same_block(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("kind", "index", "timeline", "training_goal"))


def _prev_block(profile: Optional[dict], goal: dict) -> Optional[dict]:
    prev = None
    for b in blocks(profile):
        if _same_block(b, goal):
            return prev
        prev = b
    return None


def _weeks_until(day: Optional[date], monday: date) -> Optional[int]:
    return (monday_of(day) - monday).days // 7 if day else None


def block_context(profile: Optional[dict], day: date) -> dict:
    """The block active on `day` and the north star it protects.

    `ns_goal` is the plan's north star for a sub-goal block, or the goal itself for a half / marathon
    north-star block or single goal (`own_block`); None when no half / marathon goal is involved.
    """
    goal = current_goal(profile, day)
    label = resolve_goal_distance(goal.get("training_goal"))
    monday = monday_of(day)
    race = race_day(goal)
    ns = north_star(profile)
    own = label in LONG_LABELS and goal.get("kind") != KIND_SUB_GOAL
    if own:
        ns_goal, ns_race = goal.get("training_goal"), race
    elif ns and goal.get("kind") == KIND_SUB_GOAL:
        ns_goal, ns_race = ns.get("training_goal"), race_day(ns)
    else:
        ns_goal, ns_race = None, None
    if ns_peak_weekly_km(ns_goal) is None:
        ns_goal, ns_race = None, None
    start = parse_date(goal.get("goal_set_date"))
    if not start:
        prev = _prev_block(profile, goal)
        prev_race = race_day(prev) if prev else None
        start = prev_race + timedelta(days=1) if prev_race else None
    return {
        "goal": goal, "label": label, "race": race, "start": start,
        "weeks_to_race": _weeks_until(race, monday),
        "ns_goal": ns_goal, "weeks_to_ns_race": _weeks_until(ns_race, monday), "own_block": own and bool(ns_goal),
    }


def block_volume_target(ctx: dict) -> Optional[int]:
    """Peak weekly running km of the block: north-star peak weekly km x the block's share."""
    peak = ns_peak_weekly_km(ctx.get("ns_goal"))
    if not peak or ctx.get("label") not in BLOCK_VOLUME_SHARE:
        return None
    share = 1.0 if ctx.get("own_block") else BLOCK_VOLUME_SHARE[ctx["label"]]
    return whole_km(peak * share)


def peak_weeks_before_race(label: Optional[str]) -> int:
    """The block's volume peaks this many weeks before its race (taper weeks follow)."""
    return 3 if label in LONG_LABELS else 2


def volume_taper_shares(label: Optional[str]) -> dict[int, float]:
    """Taper volume as a share of the block target, by weeks to the race."""
    return {2: 0.80, 1: 0.60} if label in LONG_LABELS else {1: 0.75}


def baseline_km(weekly_km: list[float]) -> Optional[float]:
    """Mean running km of the last BASELINE_WEEKS weeks with runs (oldest first in)."""
    recent = [k for k in weekly_km if k][-BASELINE_WEEKS:]
    return sum(recent) / len(recent) if recent else None


def baseline_window(today: date) -> tuple[date, date]:
    """(first day, last day) of the BASELINE_WEEKS complete weeks before today's week."""
    end = monday_of(today) - timedelta(days=1)
    return end - timedelta(weeks=BASELINE_WEEKS) + timedelta(days=1), end


def recent_volume_baseline(workouts: Optional[list[dict]], today: date) -> Optional[float]:
    """Starting level of the weekly-volume path: mean running km of the completed workouts in the last
    BASELINE_WEEKS complete weeks (TrainingPeaks data, identical in the trend report and the audit)."""
    start, end = baseline_window(today)
    done = [w for w in workouts or [] if is_workout_completed(w)]
    weeks = sorted(build_week_buckets(done, start, end).values(), key=lambda w: w["start_date"])
    return baseline_km([w["total_distance_km"] for w in weeks])


def week_volume_target(
    profile: Optional[dict], monday: date, baseline: Optional[float], today: date
) -> Optional[dict]:
    """Weekly running-km target of the week starting `monday`, or None (no target that week).

    Build weeks follow a linear reference path from the starting level to the block target at the
    block's peak week (no % cap: whether a step is safe for this runner is the coach's judgement);
    every RECOVERY_EVERY_WEEKS-th build week (never the peak week) is a recovery week at
    RECOVERY_SHARE of its path step. The block active today starts from
    `baseline` (recent weeks); later blocks start from the previous block's target. Taper weeks are a
    share of the block target; race, transition and post-race weeks have no target.
    """
    ctx = block_context(profile, monday)
    block_target = block_volume_target(ctx)
    if block_target is None:
        return None
    label, race, start, wtr = ctx["label"], ctx["race"], ctx["start"], ctx["weeks_to_race"]
    if (race and race < monday) or (start and monday + timedelta(days=6) < start) or wtr == 0:
        return None
    out = {
        "goal": ctx["goal"].get("training_goal"), "goal_label": label, "ns_goal": ctx["ns_goal"],
        "own_block": ctx["own_block"], "weeks_to_race": wtr, "block_target_km": block_target,
        "ns_peak_km": ns_peak_weekly_km(ctx["ns_goal"]), "phase": PHASE_BUILD, "target_km": block_target,
        "taper_share": None, "peak_week": None, "maintain": False,
    }
    taper = volume_taper_shares(label).get(wtr)
    if taper:
        return {**out, "phase": PHASE_TAPER, "target_km": whole_km(block_target * taper), "taper_share": taper}

    today_monday = monday_of(today)
    peak = monday_of(race) - timedelta(weeks=peak_weeks_before_race(label)) if race else None
    start_monday = monday_of(start) if start else today_monday
    if _same_block(ctx["goal"], current_goal(profile, today)):
        anchor, level = max(today_monday, start_monday) - timedelta(weeks=1), baseline
    else:
        prev = _prev_block(profile, ctx["goal"])
        prev_race = race_day(prev) if prev else None
        prev_target = block_volume_target(block_context(profile, prev_race)) if prev_race else None
        anchor, level = start_monday - timedelta(weeks=1), prev_target or baseline
    out["peak_week"] = peak
    out["start_km"] = round(level, 1) if level else None
    i = (monday - anchor).days // 7
    n = (peak - anchor).days // 7 if peak and peak > anchor else None
    if not level or n is None:
        path = block_target
    elif level >= block_target:
        path, out["maintain"] = block_target, True
    else:
        step = max(1, min(n, i))
        path = level + (block_target - level) * step / n
    if i > 0 and i % RECOVERY_EVERY_WEEKS == 0 and (n is None or i < n):
        return {**out, "phase": PHASE_RECOVERY, "target_km": whole_km(path * RECOVERY_SHARE),
                "ramp_km": whole_km(path)}
    return {**out, "target_km": whole_km(path)}


def volume_plan(profile: Optional[dict], today: date, baseline: Optional[float], max_weeks: int = 30) -> Optional[dict]:
    """The current block's weekly-volume targets from this week up to the week before its race."""
    ctx = block_context(profile, today)
    block_target = block_volume_target(ctx)
    if block_target is None:
        return None
    today_monday = monday_of(today)
    last = monday_of(ctx["race"]) - timedelta(weeks=1) if ctx["race"] else today_monday + timedelta(weeks=12)
    weeks = [today_monday + timedelta(weeks=i) for i in range(max_weeks)]
    targets = [(m, week_volume_target(profile, m, baseline, today)) for m in weeks if m <= last]
    targets = [(m, t) for m, t in targets if t]
    build = [t for _, t in targets if t["phase"] in (PHASE_BUILD, PHASE_RECOVERY)]
    this_week = next((t for m, t in targets if m == today_monday), None)
    peak = next((t["peak_week"] for t in build if t["peak_week"]), None)
    return {
        "goal": ctx["goal"].get("training_goal"), "goal_label": ctx["label"], "ns_goal": ctx["ns_goal"],
        "own_block": ctx["own_block"], "block_target_km": block_target, "ns_peak_km": ns_peak_weekly_km(ctx["ns_goal"]),
        "baseline_km": round(baseline, 1) if baseline else None,
        "this_week_km": this_week["target_km"] if this_week else None,
        "first_week": targets[0][0] if targets else None,
        "first_km": targets[0][1]["target_km"] if targets else None,
        "peak_week": peak,
        "maintain": any(t["maintain"] for t in build),
        "plan": [{"week": m, "km": t["target_km"], "phase": t["phase"]} for m, t in targets],
    }


def volume_rule_summary(ctx: dict) -> str:
    """One-line description of the weekly-volume rule for a block ('' when it has no volume target)."""
    block_target = block_volume_target(ctx)
    if block_target is None:
        return ""
    label, peak_km = ctx["label"], ns_peak_weekly_km(ctx["ns_goal"])
    share = "100%" if ctx["own_block"] else f"{round(BLOCK_VOLUME_SHARE[label] * 100)}%"
    taper = ", ".join(f"{w} wk out {round(s * 100)}%" for w, s in sorted(volume_taper_shares(label).items(), reverse=True))
    return (f"block target {block_target} km/week ({share} of the {peak_km} km/week {ctx['ns_goal']} peak); "
            "build weeks follow a linear reference path from the recent level (no % cap: the safe ramp "
            f"is a coaching judgement), every {RECOVERY_EVERY_WEEKS}th build week a recovery week at "
            f"{round(RECOVERY_SHARE * 100)}%, "
            f"peaking {peak_weeks_before_race(label)} weeks before the race; taper {taper} of the block target; "
            "race week: no target")
