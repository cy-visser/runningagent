"""Long-run target: one deterministic rule shared by the schedule audit and the trend analysis.

Pure helpers (no I/O). The rule (coaching consensus: Daniels, Pfitzinger; taper: Bosquet 2007, Mujika):

- Share: the long run is 25-30% of the week's running km.
- Floor: the goal distance's long-run minimum (`DISTANCE_PROFILES[goal]["long_km"]`), raised to
  16 km while the north star is a half marathon or marathon (aerobic-base protection).
- Cap: 110 min for 5K/10K blocks, 150 min otherwise (converted to km with the run's pace when known).
  The floor wins over the cap: it is the minimum stimulus.
- Sharpening (last 2 weeks before the race): goal floor up to 16 km. Race week: no long-run requirement.
"""

import math
from datetime import date, timedelta
from typing import Optional

from .date_helpers import parse_date
from .goals import KIND_NORTH_STAR, current_goal, north_star
from .race_readiness import DISTANCE_PROFILES
from .trajectory import resolve_goal_distance, resolve_target_peak_ctl

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


def _fmt_km(value: float) -> str:
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
    """Long-run range for one week, or None when the goal distance is unsupported.

    weeks_to_race: whole weeks from this week's Monday to the race week's Monday (0 = race week);
        None = a build week with no race-distance context.
    Returns {low_km, high_km, floor_km, cap_km, north_star_floor, phase, rationale}; low/high are
    None in race week.
    """
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
    parts.append(f"floor {_fmt_km(floor)} km" + (" (north-star protection)" if protect else f" ({goal_label})"))
    if cap_km:
        parts.append(f"cap {cap_min} min ≈ {cap_km:.1f} km")
    if sharpening:
        parts.append(f"sharpening: max {_fmt_km(max(floor, NORTH_STAR_FLOOR_KM))} km")
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


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _north_star_label(profile: Optional[dict]) -> Optional[str]:
    ns = north_star(profile)
    return resolve_goal_distance(ns["training_goal"]) if ns else None


def annotate_long_runs(weeks: list[dict], profile: Optional[dict]) -> list[dict]:
    """Adds `long_run` = {goal_label, phase, weeks_to_race, target, flag} to each week bucket.

    Each week is judged against the goal block active on its Monday, so an audit window that
    crosses a block boundary uses the right goal per week. Mutates and returns `weeks`.
    """
    ns_label = _north_star_label(profile)
    for w in weeks:
        monday, sunday = w["start_date"], w["end_date"]
        goal = current_goal(profile, monday)
        label = resolve_goal_distance(goal.get("training_goal"))
        race, start = parse_date(goal.get("timeline")), parse_date(goal.get("goal_set_date"))
        info = {"goal_label": label, "goal": goal.get("training_goal"), "phase": None,
                "weeks_to_race": None, "target": None, "flag": None}
        if label:
            if race and race < monday:
                info["phase"] = PHASE_POST_RACE
            elif start and sunday < start:
                info["phase"] = PHASE_TRANSITION
            else:
                weeks_to_race = (_monday(race) - monday).days // 7 if race else None
                block_ns = ns_label if goal.get("kind") != KIND_NORTH_STAR else None
                pace = None
                if w.get("long_km") and w.get("long_duration_h"):
                    pace = w["long_duration_h"] * 3600 / w["long_km"]
                target = long_run_target(label, block_ns, w.get("total_distance_km"), pace, weeks_to_race)
                runs = w.get("easy_count", 0) + w.get("quality_count", 0)
                info.update(phase=target["phase"], weeks_to_race=weeks_to_race, target=target,
                            flag=long_run_flag(w.get("long_km"), target, runs))
        w["long_run"] = info
    return weeks


def format_week_long_run(w: dict) -> str:
    """'Long run: 14 km | target 16-19.5 km (build, 12 wk to 5K) ⚠ below north-star floor', or ''."""
    info = w.get("long_run") or {}
    if not info.get("phase"):
        return ""
    long_km = w.get("long_km") or 0.0
    head = f"Long run: {long_km:.1f} km"
    phase = info["phase"]
    target = info.get("target")
    if phase in (PHASE_TRANSITION, PHASE_POST_RACE):
        return f"{head} | {phase} week (outside the {info['goal_label']} block): no long-run target"
    if not target or target["low_km"] is None:
        return f"{head} | {phase}: no long-run requirement"
    wk = f", {info['weeks_to_race']} wk to {info['goal_label']}" if info.get("weeks_to_race") is not None else ""
    return (f"{head} | target {_fmt_km(target['low_km'])}-{_fmt_km(target['high_km'])} km "
            f"({phase}{wk}; {target['rationale']}) {info['flag']}")


def rule_summary(goal_label: str, north_star_label: Optional[str]) -> str:
    """One-line description of the long-run rule for this block."""
    goal_floor = DISTANCE_PROFILES[goal_label]["long_km"]
    floor = f"floor {_fmt_km(goal_floor)} km ({goal_label})"
    if north_star_label in LONG_NORTH_STARS and NORTH_STAR_FLOOR_KM > goal_floor:
        floor += f", raised to {_fmt_km(NORTH_STAR_FLOOR_KM)} km to protect the {north_star_label} north star"
    return (f"{int(LONG_RUN_SHARE[0] * 100)}-{int(LONG_RUN_SHARE[1] * 100)}% of the week's running km; {floor}; "
            f"cap {cap_minutes(goal_label)} min; last {SHARPEN_WEEKS} weeks before the race: "
            f"{_fmt_km(goal_floor)}-{_fmt_km(max(goal_floor, NORTH_STAR_FLOOR_KM))} km; race week: no long run")


def format_goal_context(profile: Optional[dict], today: date, ctl: Optional[float] = None) -> str:
    """Goal (plan) context for the schedule audit: current block, north star and long-run rule; '' if no goal."""
    goal = current_goal(profile, today)
    label = resolve_goal_distance(goal.get("training_goal"))
    if not label:
        return ""
    ns = north_star(profile)
    ns_label = _north_star_label(profile) if goal.get("kind") != KIND_NORTH_STAR else None
    race = parse_date(goal.get("timeline"))
    weeks = f" ({max(0, (_monday(race) - _monday(today)).days // 7)} weeks)" if race else ""
    block = f"{goal['training_goal']}, race {goal.get('timeline') or 'not set'}{weeks}"
    if goal.get("before_start"):
        block += f"; block starts {goal['goal_set_date']} (transition/recovery until then)"

    if ns:
        lines = ["**Goal Plan Context** (judge the plan on both levels: the current sub goal AND the north star):"]
        kind = "north-star block" if goal.get("kind") == KIND_NORTH_STAR else "sub-goal block"
        lines.append(f"- Current {kind}: {block}.")
        name = f" ({ns['race_name']})" if ns.get("race_name") else ""
        _, (lo, hi) = resolve_target_peak_ctl(ns["training_goal"])
        ctl_str = f"; current CTL {ctl:.1f}" if ctl is not None else ""
        lines.append(f"- North star: {ns['training_goal']}{name}, race {ns['timeline']}. "
                     f"North-star peak CTL reference range {lo:.0f}-{hi:.0f}{ctl_str}.")
    else:
        lines = ["**Goal Context:**", f"- Current goal: {block}."]
    lines.append(f"- Long-run rule ({label} block): {rule_summary(label, ns_label)}. "
                 "Per-week targets and flags are below; use them, never a generic range.")
    return "\n".join(lines)


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
    ns_label = _north_star_label(profile) if goal.get("kind") != KIND_NORTH_STAR else None
    recent = [r["km"] for r in rows if r.get("complete") and r.get("runs")][-RECENT_VOLUME_WEEKS:]
    weekly_km = sum(recent) / len(recent) if recent else None
    build = long_run_target(label, ns_label, weekly_km, easy_pace_s, None)
    sharpen = long_run_target(label, ns_label, weekly_km, easy_pace_s, 1)
    when = "upcoming" if goal.get("before_start") else "current"
    volume = f"{weekly_km:.0f} km/week (mean of the last {len(recent)} complete weeks)" if weekly_km else "no recent volume"
    return (
        f"Long-run target for the {when} {goal['training_goal']} block (shared rule, identical in the schedule "
        f"audit; at {volume}): build weeks {_fmt_km(build['low_km'])}-{_fmt_km(build['high_km'])} km; "
        f"last {SHARPEN_WEEKS} weeks {_fmt_km(sharpen['low_km'])}-{_fmt_km(sharpen['high_km'])} km; race week none. "
        f"Rule: {rule_summary(label, ns_label)}. Long-run advice uses only this target, never the pattern split."
    )
