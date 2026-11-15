"""Firestore cache serialization and live refresh for the 12-week Race Predictor."""

from __future__ import annotations

from datetime import date, timedelta
import logging
from typing import Any, Optional

from google.adk.tools import ToolContext

from ...integrations import firestore
from ...integrations.trainingpeaks import tp_calls
from ..dates import get_now_utc, iso_date, parse_date
from ..goal_distance import DISTANCE_PROFILES, resolve_goal_distance
from ..goal_plan import (
    KIND_NORTH_STAR,
    KIND_SUB_GOAL,
    active_race_goal,
    blocks,
    goal_key,
    north_star,
    race_day,
)
from ..health_metrics import HEALTH_BASELINE_DAYS, extract_health_metrics_dated
from ..parallel_fetch import gather_labeled
from ..race_equivalents import goal_target_s, north_star_equivalent
from ..runner_identity import profile_user_id
from .goal_trajectory import summarize_fitness
from .projection_evidence import PROJECTION_WINDOW_DAYS
from .race_projection import build_goal_projection

logger = logging.getLogger(__name__)

RACE_PROJECTION_SCHEMA_VERSION = 1
PMC_LOOKBACK_DAYS = 90


def _round_int(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    try:
        return round(float(val))
    except (TypeError, ValueError):
        return None


def _sub_goal_position(profile: dict, active_block: dict) -> tuple[Optional[int], Optional[int]]:
    """1-based `(step, total_sub_goals)` when `active_block` is a sub-goal, else `(None, None)`."""
    if active_block.get("kind") != KIND_SUB_GOAL:
        return None, None
    sub_blocks = [b for b in blocks(profile) if b["kind"] == KIND_SUB_GOAL]
    for pos, b in enumerate(sub_blocks, start=1):
        if b["index"] == active_block.get("index"):
            return pos, len(sub_blocks)
    return None, len(sub_blocks) or None


def build_race_projection_cache_doc(
    profile: dict,
    race_projection: Optional[dict],
    today: date,
    *,
    trigger: str,
    trigger_workout: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Builds the Firestore-ready document for `users/{user_id}/cache/race_projection`, or None if no active goal."""
    goal, goal_label, status = active_race_goal(profile, today)
    if status != "ok" or not goal_label:
        return None

    r_day = race_day(goal)
    weeks_remaining = round(max(0.0, (r_day - today).days / 7.0), 1) if r_day else None
    step, total_subs = _sub_goal_position(profile, goal)

    proj_wrap = race_projection or {}
    proj = proj_wrap.get("projection")
    km = DISTANCE_PROFILES[goal_label]["km"]

    projection_payload: Optional[dict[str, Any]] = None
    if isinstance(proj, dict):
        today_s = _round_int(proj.get("today_s"))
        race_day_s = _round_int(proj.get("race_day_s"))
        rng = proj.get("range_s")
        projection_payload = {
            "goal_label": goal_label,
            "today_s": today_s,
            "race_day_s": race_day_s,
            "today_pace_s_per_km": round(today_s / km, 1) if today_s and km > 0 else None,
            "race_pace_s_per_km": round(race_day_s / km, 1) if race_day_s and km > 0 else None,
            "goal_s": _round_int(proj.get("goal_s")),
            "gap_s": _round_int(proj.get("gap_s")),
            "range_s": (
                [round(rng[0]), round(rng[1])]
                if isinstance(rng, (list, tuple)) and len(rng) == 2
                else None
            ),
            "confidence": proj.get("confidence"),
            "stale": bool(proj.get("stale")),
            "readiness": proj.get("readiness"),
            "durability": proj.get("durability"),
            "signals": list(proj.get("signals") or []),
            "drivers": [
                {"driver": str(d[0]), "evidence": str(d[1]), "implied": str(d[2])}
                for d in (proj.get("drivers") or [])
                if isinstance(d, (list, tuple)) and len(d) == 3
            ],
        }

    ns_payload: Optional[dict[str, Any]] = None
    ns = north_star(profile)
    if ns and goal.get("kind") != KIND_NORTH_STAR:
        ns_goal = ns.get("training_goal")
        ns_target = goal_target_s(ns_goal)
        race_day_val = (projection_payload or {}).get("race_day_s")
        equiv = north_star_equivalent(race_day_val, goal.get("training_goal"), ns_goal)
        ns_payload = {
            "training_goal": ns_goal,
            "goal_label": resolve_goal_distance(ns_goal),
            "race_name": ns.get("race_name"),
            "race_date": parse_date(ns.get("timeline")).isoformat() if parse_date(ns.get("timeline")) else ns.get("timeline"),
            "target_s": _round_int(ns_target),
            "equivalent_s": _round_int(equiv),
            "gap_s": _round_int(equiv - ns_target) if equiv and ns_target else None,
        }

    key_count = (
        proj.get("key_sessions_count")
        if isinstance(proj, dict) and proj.get("key_sessions_count") is not None
        else int(proj_wrap.get("key_sessions_count") or 0)
    )

    return {
        "version": RACE_PROJECTION_SCHEMA_VERSION,
        "updated_at": get_now_utc().isoformat(),
        "as_of_date": iso_date(today),
        "trigger": trigger,
        "trigger_workout": trigger_workout,
        "goal_key": goal_key(goal),
        "active_goal": {
            "kind": goal.get("kind"),
            "training_goal": goal.get("training_goal"),
            "race_name": goal.get("race_name"),
            "race_date": r_day.isoformat() if r_day else goal.get("timeline"),
            "start_date": parse_date(goal.get("goal_set_date")).isoformat()
            if parse_date(goal.get("goal_set_date"))
            else goal.get("goal_set_date"),
            "goal_label": goal_label,
            "planned": bool(goal.get("planned")),
            "before_start": bool(goal.get("before_start")),
            "weeks_remaining": weeks_remaining,
            "sub_goal_step": step,
            "sub_goal_total": total_subs,
        },
        "north_star": ns_payload,
        "window_weeks": PROJECTION_WINDOW_DAYS // 7,
        "key_sessions_count": key_count,
        "projection": projection_payload,
    }


async def save_projection_to_cache(
    profile: dict,
    race_projection: Optional[dict],
    today: date,
    *,
    trigger: str,
    trigger_workout: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Best-effort write of the active goal's race projection to Firestore (`users/{user_id}/cache/race_projection`)."""
    user_id = profile_user_id(profile)
    if not user_id:
        return None
    doc = build_race_projection_cache_doc(
        profile, race_projection, today, trigger=trigger, trigger_workout=trigger_workout
    )
    if not doc:
        return None
    try:
        await firestore.save_race_projection(user_id, doc)
    except Exception as exc:
        logger.warning("Ignoring Firestore race-projection cache write error for %s: %s", user_id, exc)
    return doc


async def recompute_and_cache_race_projection(
    tool_context: ToolContext,
    profile: dict,
    today: date,
    *,
    trigger: str,
    settings_raw: Any = None,
    trigger_workout: Optional[dict[str, Any]] = None,
    refresh_analysis_cache: bool = False,
) -> Optional[dict[str, Any]]:
    """Fetches 12-week workouts, PMC, recovery metrics and training log, computes the projection, and caches it."""
    _, goal_label, status = active_race_goal(profile, today)
    user_id = profile_user_id(profile)
    if status != "ok" or not goal_label or not user_id:
        return None

    window_start = iso_date(today - timedelta(days=PROJECTION_WINDOW_DAYS))
    pmc_start = iso_date(today - timedelta(days=PMC_LOOKBACK_DAYS))
    metrics_start = iso_date(today - timedelta(days=HEALTH_BASELINE_DAYS))
    today_str = iso_date(today)

    fetches: dict[str, Any] = {
        "workouts": tp_calls.fetch_workouts(tool_context, window_start, today_str),
        "fitness PMC": tp_calls.run_tp_tool(
            tool_context, "tp_get_fitness", start_date=pmc_start, end_date=today_str
        ),
        "recovery metrics": tp_calls.run_tp_tool(
            tool_context, "tp_get_metrics", start_date=metrics_start, end_date=today_str
        ),
        "training records": firestore.list_training_records(user_id, window_start, today_str),
    }
    if settings_raw is None:
        fetches["athlete settings"] = tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings")

    raw = await gather_labeled(fetches)
    if raw.get("workouts") is None:
        logger.warning("Skipping race-projection cache refresh: TrainingPeaks workouts unavailable")
        return None

    resolved_settings = settings_raw if settings_raw is not None else raw.get("athlete settings")
    dated_metrics = (
        extract_health_metrics_dated(raw["recovery metrics"]) if raw.get("recovery metrics") else None
    )
    fitness_data = summarize_fitness(raw.get("fitness PMC"), profile, today)
    race_projection = await build_goal_projection(
        tool_context,
        goal_label,
        profile,
        raw["workouts"],
        fitness_data,
        resolved_settings,
        dated_metrics,
        today,
        refresh_cache=refresh_analysis_cache,
        training_records=raw.get("training records"),
    )
    return await save_projection_to_cache(
        profile,
        race_projection,
        today,
        trigger=trigger,
        trigger_workout=trigger_workout,
    )
