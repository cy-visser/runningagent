"""Per-week long-run target annotations and goal context for the schedule audit."""

from datetime import date
from typing import Optional

from ....shared.dates import parse_date
from ....shared.goal_distance import resolve_goal_distance, resolve_target_peak_ctl
from ....shared.goal_plan import KIND_NORTH_STAR, current_goal, north_star
from ....shared.long_run_rule import (
    PHASE_POST_RACE,
    PHASE_TRANSITION,
    fmt_km,
    long_run_flag,
    long_run_target,
    monday_of,
    north_star_label,
    rule_summary,
)


def annotate_long_runs(weeks: list[dict], profile: Optional[dict]) -> list[dict]:
    """Adds `long_run` = {goal_label, phase, weeks_to_race, target, flag} to each week bucket.

    Each week is judged against the goal block active on its Monday, so an audit window that
    crosses a block boundary uses the right goal per week. Mutates and returns `weeks`.
    """
    ns_label = north_star_label(profile)
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
                weeks_to_race = (monday_of(race) - monday).days // 7 if race else None
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
    return (f"{head} | target {fmt_km(target['low_km'])}-{fmt_km(target['high_km'])} km "
            f"({phase}{wk}; {target['rationale']}) {info['flag']}")


def format_goal_context(profile: Optional[dict], today: date, ctl: Optional[float] = None) -> str:
    """Goal (plan) context for the schedule audit: current block, north star and long-run rule; '' if no goal."""
    goal = current_goal(profile, today)
    label = resolve_goal_distance(goal.get("training_goal"))
    if not label:
        return ""
    ns = north_star(profile)
    ns_label = north_star_label(profile) if goal.get("kind") != KIND_NORTH_STAR else None
    race = parse_date(goal.get("timeline"))
    weeks = f" ({max(0, (monday_of(race) - monday_of(today)).days // 7)} weeks)" if race else ""
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
