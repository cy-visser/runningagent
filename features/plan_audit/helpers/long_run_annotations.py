"""Per-week long-run facts, running-volume facts and goal context for the plan audit.

Volume is reported as facts only (km, change vs the prior week, deviation from the block's linear
reference path). There is deliberately no coded ramp limit or ⚠ verdict: the coach judges whether a
ramp is appropriate for this runner (CTL, recent weekly km, background, recovery).
"""

from datetime import date
from typing import Optional

from ....shared.dates import monday_of
from ....shared.long_run_facts import (
    fmt_duration,
    fmt_km,
    format_history,
    format_weekly_km_history,
    week_long_run_facts,
)
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
    """'Long run: 16 km (1:28, 34% of the week's running km) | 9 wk to 5K', or '' (web payload)."""
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


def _week_phase_meta(w: dict) -> str:
    v = w.get("volume")
    if v:
        wk = f", {v['weeks_to_race']} wk to {v['goal_label']}" if v.get("weeks_to_race") is not None else ""
        phase = "recovery week" if v["phase"] == PHASE_RECOVERY else v["phase"]
        return f" ({phase}{wk})"
    info = w.get("long_run") or {}
    phase = info.get("phase")
    if phase in (PHASE_TRANSITION, PHASE_POST_RACE):
        return f" ({phase} week, outside {info['goal_label']} block)"
    if phase == PHASE_RACE_WEEK:
        return f" ({info['goal_label']} race week)"
    if info.get("weeks_to_race") is not None and info.get("goal_label"):
        return f" ({info['weeks_to_race']} wk to {info['goal_label']})"
    return ""


def _week_volume_part(w: dict) -> str:
    km = round(w.get("total_distance_km") or 0.0, 1)
    v = w.get("volume")
    notes = []
    if w.get("vs_prior_pct") is not None:
        notes.append(f"{_signed_pct(w['vs_prior_pct'])} vs prior {w['prior_km']:.1f} km")
    if v:
        detail = ""
        if v["phase"] == PHASE_TAPER:
            detail = f" [{round(v['taper_share'] * 100)}% of {v['block_target_km']} km]"
        elif v["phase"] == PHASE_RECOVERY:
            detail = f" [{round(RECOVERY_SHARE * 100)}% of {v['ramp_km']} km]"
        elif v.get("maintain"):
            detail = " [maintain]"
        if km <= 0:
            tail = f", {NO_RUNS_PLANNED}"
        elif v.get("vs_path_pct") is not None:
            tail = f", {_signed_pct(v['vs_path_pct'])} vs path"
        else:
            tail = ""
        notes.append(f"path {v['target_km']} km{detail}{tail}")
    return f"{km:.1f} km" + (f" ({'; '.join(notes)})" if notes else "")


def format_audit_week_header(w: dict) -> str:
    """Compact one-line week header with volume/ramp/path, TSS, sport split and long-run facts."""
    start_str = w["start_date"].isoformat()
    end_str = w["end_date"].strftime("%b %d")
    km = round(w.get("total_distance_km") or 0.0, 1)
    parts = [_week_volume_part(w), f"TSS {round(w.get('total_tss') or 0.0)}"]

    split = []
    easy, qual = w.get("easy_count") or 0, w.get("quality_count") or 0
    if easy + qual:
        split.append(f"{easy}E/{qual}Q")
    if w.get("bike_count"):
        split.append(f"{w['bike_count']} Bike")
    if w.get("strength_count"):
        split.append(f"{w['strength_count']} Str")
    if w.get("other_sport_count"):
        split.append(f"{w['other_sport_count']} Oth")
    if split:
        parts.append(", ".join(split))

    long_km = w.get("long_km") or 0.0
    info = w.get("long_run") or {}
    if long_km > 0:
        dur = fmt_duration(w.get("long_duration_h"))
        share = f"{round(long_km / km * 100)}%" if km > 0 else ""
        extra = ", ".join(x for x in (dur, share) if x)
        parts.append(f"LR {fmt_km(round(long_km, 1))} km" + (f" ({extra})" if extra else ""))
    elif easy + qual == 0 and (info.get("goal_label") or w.get("volume")):
        parts.append("LR none")

    return f"* **{start_str} – {end_str}**{_week_phase_meta(w)}: {' · '.join(parts)}"


def format_goal_context(
    profile: Optional[dict], today: date, ctl: Optional[float] = None, long_runs: Optional[list[dict]] = None
) -> str:
    """Compact audit context: dynamic training facts not already in `<runner_profile>`."""
    ctx = block_context(profile, today)
    label = ctx["label"]
    if not label and ctl is None and not long_runs:
        return ""
    lines = ["**Audit Context:**"]
    if ctl is not None:
        lines.append(f"- Current CTL: {ctl:.1f}")
    n = len(long_runs or [])
    if n:
        weekly = format_weekly_km_history(long_runs or []) or "no completed runs"
        history = format_history(long_runs or []) or "no completed runs"
        lines.append(f"- Last {n} complete weeks (oldest first): weekly km `{weekly}` | longest runs `{history}`")
    if label:
        volume = volume_rule_summary(ctx)
        if volume:
            lines.append(f"- Volume reference ({label} block): {volume}.")
    return "\n".join(lines) if len(lines) > 1 else ""
