"""Deterministic, advisory load check for `create_workout` (never blocks a write).

Compares the week with the proposed session against the week as it was (including the workout
being replaced, if any) and only reports risks the change introduces or worsens:
  1. a 3rd or later quality session in the same ISO week,
  2. hard sessions on consecutive days,
  3. a quality session inside the goal race's taper,
  4. quality or long-run work near an injury / illness calendar note.

Weekly running-volume change vs the prior week is returned as a fact (`week.volume_change_pct`),
never as a coded risk: whether a ramp is too steep is the coach's judgement for this runner.
"""

import re
from datetime import date, timedelta
from typing import Any, Optional

from ....shared.dates import iso_date, parse_date
from ....shared.goal_plan import KIND_SUB_GOAL, current_goal, race_day
from ....shared.goal_projection.goal_trajectory import resolve_taper_weeks
from ....shared.dates import monday_of
from ....shared.north_star_targets import pct_change
from ....shared.sports import NON_TRAINING_SPORTS, RUN_SPORTS, is_quality_title
from ....shared.weekly_buckets import build_week_buckets
MAX_QUALITY_PER_WEEK = 2
NOTE_WINDOW_DAYS = 7
LONG_RUN_RE = re.compile(r"\blong\b", re.IGNORECASE)
HEALTH_NOTE_RE = re.compile(
    r"\b(injur\w*|pain\w*|sore\w*|niggle|strain\w*|sprain\w*|tendon\w*|tendin\w*|achilles|shin|knee|"
    r"calf|hamstring|ill|illness|sick\w*|flu|cold|covid|fever|infection)\b",
    re.IGNORECASE,
)
PREFLIGHT_SPORTS = RUN_SPORTS | {"race"}


def applies_to(sport: str) -> bool:
    """The rules concern running load: only run and race sessions are checked."""
    return (sport or "").strip().lower() in PREFLIGHT_SPORTS


def preflight_window(target: date) -> tuple[date, date]:
    """Prior ISO week through the target ISO week."""
    week_start = monday_of(target)
    return week_start - timedelta(days=7), week_start + timedelta(days=6)


def _is_quality_run(w: dict) -> bool:
    sport = (w.get("sport") or "").strip().lower()
    return sport in PREFLIGHT_SPORTS and (sport == "race" or is_quality_title(w.get("title") or ""))


def _taper_risk(profile: dict, target: date, is_quality: bool) -> Optional[str]:
    if not is_quality:
        return None
    goal = current_goal(profile, target)
    rd = race_day(goal) if goal.get("training_goal") else None
    if not rd or not target < rd:
        return None
    # A profile taper override applies to the final goal race (single goal / north star) only.
    override = None if goal.get("kind") == KIND_SUB_GOAL else profile.get("taper_weeks")
    weeks = resolve_taper_weeks(goal.get("training_goal"), override)
    taper_start = rd - timedelta(days=round(weeks * 7))
    if target >= taper_start:
        return (
            f"Quality session inside the {weeks:g}-week taper for {goal['training_goal']} "
            f"(race {iso_date(rd)}, taper from {iso_date(taper_start)})."
        )
    return None


def preflight_risks(
    *,
    target: date,
    sport: str,
    title: str,
    distance_km: Optional[float],
    duration_minutes: Optional[float],
    tss_planned: Optional[float],
    workouts: list[dict],
    notes: list[dict],
    profile: dict,
    replaced_workout_id: Optional[str] = None,
) -> dict[str, Any]:
    """Risks (with their numbers) the proposed session introduces or worsens, and the week it lands in."""
    prior_start, week_end = preflight_window(target)
    week_start = prior_start + timedelta(days=7)
    training = [w for w in workouts or [] if (w.get("sport") or "") not in NON_TRAINING_SPORTS]
    replaced_id = str(replaced_workout_id or "")
    original = next((w for w in training if replaced_id and str(w.get("id") or "") == replaced_id), None)
    others = [w for w in training if w is not original]
    proposed = {
        "id": "proposed",
        "date": iso_date(target),
        # Count a 'Race' entry as running volume.
        "sport": "Run" if (sport or "").strip().lower() == "race" else sport,
        "title": title,
        "type": "planned",
        "distance_planned_km": distance_km,
        "duration_planned": (duration_minutes / 60.0) if duration_minutes else None,
        "tss_planned": tss_planned,
    }
    is_quality = _is_quality_run({"sport": sport, "title": title})
    is_long = bool(LONG_RUN_RE.search(title or ""))

    # What the replaced workout already was on this day: problems it already had aren't new.
    same_day_original = original is not None and parse_date(
        original.get("date") or original.get("start_time")) == target
    was_quality = same_day_original and _is_quality_run(original)
    was_long = same_day_original and bool(LONG_RUN_RE.search(original.get("title") or ""))

    before = build_week_buckets(others, prior_start, week_end)
    baseline = build_week_buckets(others + ([original] if original else []), prior_start, week_end)
    after = build_week_buckets(others + [proposed], prior_start, week_end)
    key_prior, key_week = sorted(after)
    prior, week, week_before = after[key_prior], after[key_week], before[key_week]
    week_baseline = baseline[key_week]

    risks: list[str] = []
    if (is_quality and week["quality_count"] > MAX_QUALITY_PER_WEEK
            and week["quality_count"] > week_baseline["quality_count"]):
        risks.append(
            f"{week['quality_count']} quality sessions in the week of {week['date_range']} "
            f"(max {MAX_QUALITY_PER_WEEK})."
        )
    if is_quality and not was_quality:
        for w in others:
            d = parse_date(w.get("date") or w.get("start_time"))
            if d and abs((d - target).days) == 1 and _is_quality_run(w):
                risks.append(f"Hard session on a consecutive day: '{w.get('title')}' on {iso_date(d)}.")
    prior_km, week_km = prior["total_distance_km"], week["total_distance_km"]
    volume_increased = bool(applies_to(sport) and week_km > week_baseline["total_distance_km"] + 1e-9)
    taper = _taper_risk(profile or {}, target, is_quality and not was_quality)
    if taper:
        risks.append(taper)
    if (is_quality and not was_quality) or (is_long and not (was_long or was_quality)):
        for n in notes or []:
            d = parse_date(n.get("date"))
            text = f"{n.get('title') or ''} {n.get('description') or ''}"
            if d and abs((d - target).days) <= NOTE_WINDOW_DAYS and HEALTH_NOTE_RE.search(text):
                risks.append(f"Calendar note on {iso_date(d)}: '{(n.get('title') or '').strip()}'.")

    return {
        "risks": risks,
        "week": {
            "week": week["date_range"],
            "running_km_before": round(week_before["total_distance_km"], 1),
            "running_km_after": round(week_km, 1),
            "prior_week_running_km": round(prior_km, 1),
            "volume_change_pct": pct_change(week_km, prior_km),
            "volume_increased": volume_increased,
            "quality_sessions_after": week["quality_count"],
        },
        "window": {"start": iso_date(prior_start), "end": iso_date(week_end), "week_start": iso_date(week_start)},
    }
