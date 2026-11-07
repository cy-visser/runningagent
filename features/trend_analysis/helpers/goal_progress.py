"""Progress toward the current goal and the north star for the trend report.

Feeds the header projection, the four goal-progress charts (fitness vs CTL band, implied race time,
north-star milestones, long-run & volume readiness) and the goal context the coach reasons over. Long runs
have no computed target: the coach reasons them from the long-run history.
"""

import math
from datetime import date, timedelta
from typing import Any, Optional

from ....shared.goal_distance import DISTANCE_PROFILES, resolve_goal_distance, resolve_target_peak_ctl
from ....shared.goal_plan import KIND_NORTH_STAR, KIND_SUB_GOAL, blocks, current_goal, north_star, race_day
from ....shared.goal_projection.race_projection import format_projection_evidence
from ....shared.north_star_targets import (
    RECOVERY_EVERY_WEEKS,
    RECOVERY_SHARE,
    volume_plan,
)
from ....shared.race_equivalents import format_gap, goal_target_s, north_star_equivalent
from ....shared.units import as_float, format_seconds_hms

IMPLIED_TIER = "moderate"           # threshold -> race speed ratio used for the implied race-time chart
MAX_PLAN_WEEKS = 26                 # cap on the projected CTL ramp drawn into the future


def _iso(day: Optional[date]) -> Optional[str]:
    return day.isoformat() if day else None


def _round(value: Any) -> Optional[int]:
    num = as_float(value)
    return round(num) if num is not None else None


def _weeks_to(day: Optional[date], today: date) -> Optional[float]:
    return round(max(0, (day - today).days) / 7, 1) if day else None


def implied_time_s(lt2_pace_s: Optional[float], label: Optional[str]) -> Optional[float]:
    """Finish time over `label`'s distance implied by a threshold (LT2) pace, via the distance ratio."""
    prof = DISTANCE_PROFILES.get(label or "")
    if not prof or not lt2_pace_s:
        return None
    return prof["km"] * lt2_pace_s / prof["ratios"][IMPLIED_TIER]


def _projection(race_projection: Optional[dict]) -> Optional[dict]:
    proj = (race_projection or {}).get("projection")
    if not isinstance(proj, dict):
        return None
    rng = proj.get("range_s")
    return {
        "today_s": _round(proj.get("today_s")),
        "race_day_s": _round(proj.get("race_day_s")),
        "goal_s": _round(proj.get("goal_s")),
        "gap_s": _round(proj.get("gap_s")),
        "range_s": [round(rng[0]), round(rng[1])] if isinstance(rng, (list, tuple)) and len(rng) == 2 else None,
        "confidence": proj.get("confidence"),
        "stale": bool(proj.get("stale")),
        # Evidence facts for the coach's goal-context line (format_projection_evidence).
        "signals": proj.get("signals"),
        "n_signals": proj.get("n_signals"),
        "newest_evidence_days": proj.get("newest_evidence_days"),
        "newest_before_block": bool(proj.get("newest_before_block")),
        "spread_pct": proj.get("spread_pct"),
    }


def ctl_plan(rows: list[dict], info: dict, ctl_now: Optional[float]) -> list[dict]:
    """Weekly CTL path at the required ramp from the latest week up to the target peak (build phase only)."""
    ramp, build, target = info.get("required_ramp_rate"), info.get("build_weeks"), info.get("target_peak_ctl")
    anchor = next((r for r in reversed(rows) if r.get("ctl") is not None), None)
    if ramp is None or not build or not target or anchor is None or not isinstance(anchor.get("week"), date):
        return []
    start_ctl = ctl_now if ctl_now else anchor["ctl"]
    if ramp <= 0 or start_ctl >= target:
        return []                   # already at / above the target peak: nothing to ramp
    weeks = min(math.ceil(build), MAX_PLAN_WEEKS)
    return [
        {"week": _iso(anchor["week"] + timedelta(weeks=i)), "ctl": round(min(target, start_ctl + ramp * i), 1)}
        for i in range(weeks + 1)
    ]


def _volume(profile: dict, today: date, baseline: Optional[float]) -> Optional[dict]:
    """Weekly running-volume targets of the current block (identical to the schedule audit's per-week targets)."""
    plan = volume_plan(profile, today, baseline)
    if not plan:
        return None
    return {
        **{k: plan[k] for k in ("block_target_km", "ns_peak_km", "baseline_km", "this_week_km", "first_km",
                                "maintain", "own_block")},
        "first_week": _iso(plan["first_week"]),
        "peak_week": _iso(plan["peak_week"]),
        "plan": [{"week": _iso(p["week"]), "km": p["km"], "phase": p["phase"]} for p in plan["plan"]],
    }


def goal_progress(
    profile: dict,
    today: date,
    rows: list[dict],
    fitness: Optional[dict],
    race_projection: Optional[dict],
    volume_baseline: Optional[float] = None,
) -> dict:
    """{'goal': ..., 'north_star': ... | None} for the trend payload and the goal context.

    `volume_baseline` is the shared recent weekly-km level (north_star_targets.recent_volume_baseline),
    the starting point of the weekly-volume path.
    """
    goal = current_goal(profile, today)
    label = resolve_goal_distance(goal.get("training_goal"))
    fit = fitness or {}
    info = fit.get("trajectory_info") or {}
    peak, ctl_range = resolve_target_peak_ctl(goal.get("training_goal"))
    projection = _projection(race_projection)
    goal_payload = {
        "training_goal": goal.get("training_goal"),
        "label": label,
        "kind": goal.get("kind"),
        "race_date": _iso(race_day(goal)),
        "weeks_to_race": _weeks_to(race_day(goal), today),
        "before_start": bool(goal.get("before_start")),
        "goal_s": _round(goal_target_s(goal.get("training_goal"))),
        "projection": projection,
        "ctl": {
            "current": round(fit["ctl_end"], 1) if as_float(fit.get("ctl_end")) else None,
            "target_peak": info.get("target_peak_ctl") or peak,
            "range": list(info.get("reference_range") or ctl_range),
            "required_ramp": info.get("required_ramp_rate"),
            "phase": info.get("phase"),
            "plan": ctl_plan(rows, info, as_float(fit.get("ctl_end"))),
        },
        "volume": _volume(profile, today, volume_baseline) if label else None,
    }

    ns = north_star(profile)
    if not ns:
        return {"goal": goal_payload, "north_star": None}
    ns_goal = ns["training_goal"]
    ns_target = goal_target_s(ns_goal)
    race_day_s = (projection or {}).get("race_day_s")
    if goal.get("kind") == KIND_NORTH_STAR:
        equiv = race_day_s
    else:
        equiv = north_star_equivalent(race_day_s, goal.get("training_goal"), ns_goal)
    _, ns_range = resolve_target_peak_ctl(ns_goal)

    milestones = []
    for b in blocks(profile):
        if b["kind"] != KIND_SUB_GOAL:
            continue
        r_day = race_day(b)
        if goal.get("kind") == KIND_SUB_GOAL and b["index"] == goal.get("index"):
            status = "active"
        elif r_day and r_day < today:
            status = "done"
        else:
            status = "upcoming"
        result_s = as_float((b.get("result") or {}).get("time_s"))
        milestones.append({
            "training_goal": b["training_goal"],
            "race_date": _iso(r_day),
            "status": status,
            "target_equiv_s": _round(north_star_equivalent(goal_target_s(b["training_goal"]), b["training_goal"], ns_goal)),
            "result_equiv_s": _round(north_star_equivalent(result_s, b["training_goal"], ns_goal)),
        })

    ns_payload = {
        "training_goal": ns_goal,
        "label": resolve_goal_distance(ns_goal),
        "race_name": ns.get("race_name"),
        "race_date": _iso(race_day(ns)),
        "weeks_to_race": _weeks_to(race_day(ns), today),
        "target_s": _round(ns_target),
        "equivalent_s": _round(equiv),
        "gap_s": _round(equiv - ns_target) if equiv and ns_target else None,
        "ctl_range": list(ns_range),
        "milestones": milestones,
    }
    return {"goal": goal_payload, "north_star": ns_payload}


def _format_volume_line(g: dict, v: dict) -> str:
    """'- Weekly volume reference (...): 52 km/week now -> 54 km in week 2026-11-16 -> 72 km by 2027-01-25 ...'."""
    ns_part = "" if v.get("own_block") else f" -> {v.get('ns_peak_km')} km/week north-star peak"
    now = f"{v['baseline_km']:.0f} km/week now (mean of the last complete weeks)" if v.get("baseline_km") else "no recent volume"
    first = f" -> {v['first_km']} km in the week of {v['first_week']}" if v.get("first_km") is not None else ""
    if v.get("maintain"):
        peak = f"; already at or above the {v['block_target_km']} km block target: maintain, no cut needed"
    else:
        by = f" by {v['peak_week']}" if v.get("peak_week") else ""
        peak = (f" -> {v['block_target_km']} km block target{by} (linear reference path, no % cap; "
                f"every {RECOVERY_EVERY_WEEKS}th build week a recovery week at {round(RECOVERY_SHARE * 100)}%)")
    return (f"- Weekly volume reference ({g['label']} block{ns_part}): {now}{first}{peak}. Same per-week path as "
            "the schedule audit; whether its steps are a safe ramp for this runner is your judgement.")


def format_goal_context(progress: dict, profile: dict, today: date) -> str:
    """Goal context for the coach: projection, CTL trajectory and the north-star mapping.

    The goal-plan table (sub goals, results, equivalents) is in the coach instruction on every
    call, so it is referenced here rather than repeated.
    """
    g, ns = progress["goal"], progress["north_star"]
    lines = []
    if north_star(profile):
        lines.append("- Goal-plan table: see GOAL PLAN in your instructions (not repeated here).")
    if not g.get("training_goal"):
        lines.append("No goal set: recommend from the trends only.")
        return "\n".join(lines)

    weeks = f", {g['weeks_to_race']:.0f} weeks away" if g.get("weeks_to_race") is not None else ""
    when = " (upcoming block, not started yet)" if g.get("before_start") else ""
    lines.append(f"- Current block{when}: {g['training_goal']}, race {g.get('race_date') or 'date not set'}{weeks}.")
    p = g.get("projection")
    if p and p.get("race_day_s"):
        rng = f"; range {format_seconds_hms(p['range_s'][0])}-{format_seconds_hms(p['range_s'][1])}" if p.get("range_s") else ""
        gap = f"; gap {format_gap(p['gap_s'])}" if p.get("gap_s") is not None else ""
        evidence = format_projection_evidence(p)
        lines.append(
            f"- Goal projection ({g['label']}): today {format_seconds_hms(p['today_s'])} -> race day "
            f"{format_seconds_hms(p['race_day_s'])}; goal {format_seconds_hms(g.get('goal_s'))}{gap}{rng}"
            f"{'; ' + evidence if evidence else ''}."
        )
    else:
        lines.append("- Goal projection: insufficient recent run data.")
    c = g["ctl"]
    if c.get("current") is not None:
        ramp_val = c.get("required_ramp")
        if c["current"] >= c["target_peak"]:
            ramp = "; already at or above this goal's target peak"
        elif ramp_val:
            ramp = f"; required ramp {ramp_val}/week to reach it before the taper"
        else:
            ramp = ""
        lines.append(
            f"- CTL now {c['current']:.0f}; goal peak-CTL target {c['target_peak']:.0f} "
            f"(range {c['range'][0]:.0f}-{c['range'][1]:.0f}); phase {c.get('phase') or '-'}{ramp}."
        )
    v = g.get("volume")
    if v:
        lines.append(_format_volume_line(g, v))
    if ns:
        ns_weeks = f", {ns['weeks_to_race']:.0f} weeks away" if ns.get("weeks_to_race") is not None else ""
        equiv = (f"; current projection's north-star equivalent {format_seconds_hms(ns['equivalent_s'])} "
                 f"(gap {format_gap(ns['gap_s'])})" if ns.get("equivalent_s") else "")
        caveat = (" Riegel equivalents from short races are optimistic for the marathon without "
                  "marathon-specific volume." if ns.get("label") == "Marathon" and g.get("kind") != KIND_NORTH_STAR else "")
        lines.append(
            f"- North star: {ns['training_goal']}, race {ns.get('race_date')}{ns_weeks}; target "
            f"{format_seconds_hms(ns.get('target_s'))}{equiv}; north-star peak-CTL range "
            f"{ns['ctl_range'][0]:.0f}-{ns['ctl_range'][1]:.0f}.{caveat}"
        )
    return "\n".join(lines)
