"""Per-week long-run facts, running-volume facts and goal context for the plan audit.

Volume is reported as facts only (km, change vs the prior week, deviation from the block's linear
reference path). There is deliberately no coded ramp limit or ⚠ verdict: the coach judges whether a
ramp is appropriate for this runner (CTL, recent weekly km, background, recovery).
"""

from datetime import date
from typing import Optional

from ....shared.dates import monday_of, parse_date
from ....shared.goal_distance import resolve_target_peak_ctl
from ....shared.goal_plan import KIND_NORTH_STAR, north_star, race_day
from ....shared.long_run_facts import format_history, format_weekly_km_history, week_long_run_facts
from ....shared.north_star_targets import (
    PHASE_POST_RACE,
    PHASE_RACE_WEEK,
    PHASE_RECOVERY,
    PHASE_TAPER,
    PHASE_TRANSITION,
    RECOVERY_SHARE,
    block_context,
    pct_change,
    volume_rule_summary,
    week_volume_target,
)

NO_RUNS_PLANNED = "no runs planned"


def annotate_long_runs(weeks: list[dict], profile: Optional[dict]) -> list[dict]:
    """Adds `long_run` = {goal_label, phase, weeks_to_race} to each week bucket (facts only, no target).

    Each week is placed in the goal block active on its Monday, so an audit window that crosses a
    block boundary labels each week correctly. Mutates and returns `weeks`.
    """
    for w in weeks:
        monday, sunday = w["start_date"], w["end_date"]
        ctx = block_context(profile, monday)
        label, race, start = ctx["label"], ctx["race"], ctx["start"]
        phase = None
        if label:
            if race and race < monday:
                phase = PHASE_POST_RACE
            elif start and sunday < start:
                phase = PHASE_TRANSITION
            elif ctx["weeks_to_race"] == 0:
                phase = PHASE_RACE_WEEK
        w["long_run"] = {"goal_label": label, "phase": phase, "weeks_to_race": ctx["weeks_to_race"]}
    return weeks


def format_week_long_run(w: dict) -> str:
    """'Long run: 16 km (1:28, 34% of the week's running km) | 9 wk to 5K', or ''."""
    info = w.get("long_run") or {}
    if not info.get("goal_label") and not w.get("long_km"):
        return ""
    facts = week_long_run_facts(w.get("long_km"), w.get("long_duration_h"), w.get("total_distance_km"))
    phase = info.get("phase")
    if phase in (PHASE_TRANSITION, PHASE_POST_RACE):
        where = f"{phase} week (outside the {info['goal_label']} block)"
    elif phase == PHASE_RACE_WEEK:
        where = f"{info['goal_label']} race week"
    elif info.get("weeks_to_race") is not None:
        where = f"{info['weeks_to_race']} wk to {info['goal_label']}"
    else:
        where = ""
    return f"Long run: {facts}" + (f" | {where}" if where else "")


def annotate_week_over_week(weeks: list[dict], prior_km: Optional[float]) -> list[dict]:
    """Adds `prior_km` and `vs_prior_pct` (running km change vs the previous week) to each week bucket.

    `prior_km` is the running km of the week before the first audited week (None when unknown).
    Mutates and returns `weeks`.
    """
    prev = prior_km
    for w in weeks:
        km = w.get("total_distance_km") or 0.0
        w["prior_km"] = round(prev, 1) if prev is not None else None
        w["vs_prior_pct"] = pct_change(km, prev)
        prev = km
    return weeks


def annotate_volume(weeks: list[dict], profile: Optional[dict], baseline: Optional[float], today: date) -> list[dict]:
    """Adds `volume` = {path target..., vs_path_pct} (or None) to each week bucket; completed weeks get no target."""
    today_monday = monday_of(today)
    for w in weeks:
        monday = w["start_date"]
        target = week_volume_target(profile, monday, baseline, today) if monday >= today_monday else None
        if target:
            km = w.get("total_distance_km") or 0.0
            w["volume"] = {**target, "vs_path_pct": pct_change(km, target.get("target_km")) if km > 0 else None}
        else:
            w["volume"] = None
    return weeks


def _signed_pct(value: Optional[float]) -> str:
    return f"{value:+.0f}%"


def format_week_over_week(w: dict) -> str:
    """'+14% vs prior week 54.4 km', or '' when there is no prior-week volume."""
    if w.get("vs_prior_pct") is None:
        return ""
    return f"{_signed_pct(w['vs_prior_pct'])} vs prior week {w['prior_km']:.1f} km"


def format_week_volume(w: dict) -> str:
    """'Volume: 62.0 km (+14% vs prior week 54.4 km) | path 58 km (build, ...), +7% vs path', or ''."""
    v = w.get("volume")
    km = w.get("total_distance_km") or 0.0
    wow = format_week_over_week(w)
    head = f"Volume: {km:.1f} km" + (f" ({wow})" if wow else "")
    if not v:
        return head if wow else ""
    wk = f", {v['weeks_to_race']} wk to {v['goal_label']}" if v.get("weeks_to_race") is not None else ""
    if v["phase"] == PHASE_TAPER:
        detail = f"taper{wk}; {round(v['taper_share'] * 100)}% of the {v['block_target_km']} km block target"
    elif v["phase"] == PHASE_RECOVERY:
        detail = (f"recovery week{wk}; {round(RECOVERY_SHARE * 100)}% of this week's {v['ramp_km']} km path step, "
                  f"block target {v['block_target_km']} km")
    else:
        detail = f"build{wk}; block target {v['block_target_km']} km"
        if v.get("maintain"):
            detail += ", already reached: maintain, no cut needed"
        elif v.get("peak_week"):
            detail += f" by {v['peak_week'].isoformat()}"
    if km <= 0:
        tail = NO_RUNS_PLANNED
    elif v.get("vs_path_pct") is not None:
        tail = f"{_signed_pct(v['vs_path_pct'])} vs path"
    else:
        tail = ""
    return f"{head} | path {v['target_km']} km ({detail})" + (f", {tail}" if tail else "")


def format_goal_context(
    profile: Optional[dict], today: date, ctl: Optional[float] = None, long_runs: Optional[list[dict]] = None
) -> str:
    """Goal (plan) context for the plan audit: current block, north star, long-run and weekly-km facts,
    volume rule."""
    ctx = block_context(profile, today)
    goal, label = ctx["goal"], ctx["label"]
    if not label:
        return ""
    ns = north_star(profile)
    race = parse_date(goal.get("timeline"))
    weeks = f" ({max(0, (monday_of(race) - monday_of(today)).days // 7)} weeks)" if race else ""
    block = f"{goal['training_goal']}, race {goal.get('timeline') or 'not set'}{weeks}"
    if goal.get("before_start"):
        block += f"; block starts {goal['goal_set_date']} (transition/recovery until then)"
    ctl_str = f"; current CTL {ctl:.1f}" if ctl is not None else ""

    if ns:
        lines = ["**Goal Plan Context** (judge the plan on both levels: the current sub goal AND the north star):"]
        kind = "north-star block" if goal.get("kind") == KIND_NORTH_STAR else "sub-goal block"
        lines.append(f"- Current {kind}: {block}.")
        name = f" ({ns['race_name']})" if ns.get("race_name") else ""
        ns_race = race_day(ns)
        ns_weeks = f" ({(monday_of(ns_race) - monday_of(today)).days // 7} weeks)" if ns_race else ""
        _, (lo, hi) = resolve_target_peak_ctl(ns["training_goal"])
        lines.append(f"- North star: {ns['training_goal']}{name}, race {ns['timeline']}{ns_weeks}. "
                     f"North-star peak CTL reference range {lo:.0f}-{hi:.0f}{ctl_str}.")
    else:
        lines = ["**Goal Context:**", f"- Current goal: {block}{ctl_str}."]
    history = format_history(long_runs or [])
    n = len(long_runs or [])
    lines.append(f"- Long-run history (longest completed run of each of the last {n} complete weeks, oldest "
                 f"first): {history or 'no completed runs'}.")
    weekly = format_weekly_km_history(long_runs or [])
    lines.append(f"- Recent weekly running km (last {n} complete weeks, oldest first): {weekly or 'no completed runs'}.")
    lines.append("- Long run: no computed target. Decide each week's long run yourself from these facts "
                 "(see the skill's long-run guidance).")
    lines.append("- Weekly ramp: no coded limit. Each week shows its change vs the prior week and vs the reference "
                 "path; judge whether each step suits this runner (see the skill's volume guidance).")
    volume = volume_rule_summary(ctx)
    if volume:
        lines.append(f"- Weekly-volume reference ({label} block): {volume}. Per-week path values are below.")
    return "\n".join(lines)
