"""Per-week long-run facts, running-volume facts and audit context for the plan audit.

Volume and long runs are reported as measured facts only (km, change vs the prior week, 12-week historical
volume and longest runs, weeks to race). There is deliberately no coded target, cap, or ⚠ verdict: the
coach judges progression toward the goal (and North Star, when set) from this runner's actual data.
"""

from datetime import date
from typing import Optional

from ....shared.goal_plan import block_on_date
from ....shared.long_run_facts import (
    LONG_RUN_HISTORY_WEEKS,
    fmt_duration,
    fmt_km,
    format_history,
    format_volume_history_facts,
    format_weekly_km_history,
    pct_change,
    week_long_run_facts,
)

PHASE_TRANSITION = "transition"
PHASE_RACE_WEEK = "race week"
PHASE_POST_RACE = "post-race"
NO_RUNS_PLANNED = "no runs planned"


def annotate_long_runs(weeks: list[dict], profile: Optional[dict]) -> list[dict]:
    """Adds `long_run` = {goal_label, phase, weeks_to_race} to each week bucket (facts only, no target).

    Each week is placed in the goal block active on its Monday, so an audit window that crosses a
    block boundary labels each week correctly. Mutates and returns `weeks`.
    """
    for w in weeks:
        monday, sunday = w["start_date"], w["end_date"]
        ctx = block_on_date(profile, monday)
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


def _signed_pct(value: Optional[float]) -> str:
    return f"{value:+.0f}%"


def _week_phase_meta(w: dict) -> str:
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
    notes = []
    if w.get("vs_prior_pct") is not None:
        notes.append(f"{_signed_pct(w['vs_prior_pct'])} vs prior {w['prior_km']:.1f} km")
    info = w.get("long_run") or {}
    if km <= 0 and info.get("goal_label") and info.get("phase") not in (PHASE_TRANSITION, PHASE_POST_RACE):
        notes.append(NO_RUNS_PLANNED)
    return f"{km:.1f} km" + (f" ({'; '.join(notes)})" if notes else "")


def format_audit_week_header(w: dict) -> str:
    """Compact one-line week header with volume/ramp, TSS, sport split and long-run facts."""
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
    elif easy + qual == 0 and info.get("goal_label"):
        parts.append("LR none")

    return f"* **{start_str} – {end_str}**{_week_phase_meta(w)}: {' · '.join(parts)}"


def format_goal_context(
    profile: Optional[dict],
    today: date,
    ctl: Optional[float] = None,
    history_entries: Optional[list[dict]] = None,
) -> str:
    """Compact audit context: dynamic training facts not already in `<runner_profile>`."""
    del profile, today  # goal plan & profile fields are already in `<runner_profile>`
    entries = history_entries or []
    if ctl is None and not entries:
        return ""
    lines = ["**Audit Context:**"]
    if ctl is not None:
        lines.append(f"- Current CTL: {ctl:.1f}")
    if entries:
        weekly = format_weekly_km_history(entries) or "no completed runs"
        vol_facts = format_volume_history_facts(entries)
        vol_suffix = f" ({vol_facts})" if vol_facts else ""
        lines.append(f"- Last {len(entries)} complete weeks (oldest first): weekly km `{weekly}`{vol_suffix}")
        recent_lr = entries[-LONG_RUN_HISTORY_WEEKS:]
        lr_text = format_history(recent_lr) or "no completed runs"
        max_lr = max((float(e.get("km") or 0.0) for e in entries), default=0.0)
        max_lr_suffix = f" ({len(entries)}-wk max {fmt_km(round(max_lr, 1))} km)" if max_lr > 0 else ""
        lines.append(
            f"- Longest runs (last {len(recent_lr)} complete weeks, oldest first): `{lr_text}`{max_lr_suffix}"
        )
    return "\n".join(lines) if len(lines) > 1 else ""
