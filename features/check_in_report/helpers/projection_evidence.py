import asyncio
from datetime import date, timedelta
import logging
from typing import Any, Optional

from google.adk.tools import ToolContext

from ....integrations import firestore
from ....integrations.trainingpeaks import tp_calls
from ....shared.analysis_summary import (
    ANALYSIS_SCHEMA_VERSION,
    is_complete_summary,
    summarize_analysis,
)
from ....shared.athlete_settings import extract_thresholds
from ....shared.dates import parse_date
from ....shared.goal_distance import DISTANCE_PROFILES, parse_target_time_minutes
from ....shared.goal_plan import current_goal, goal_race_dates
from ....shared.parallel_fetch import result_or_none
from ....shared.runner_identity import profile_user_id
from ....shared.sports import RUN_SPORTS, is_quality_title, is_race_title

logger = logging.getLogger(__name__)

PROJECTION_WINDOW_DAYS = 56
MAX_ANALYSES = 8
# Runs this long are long runs whatever the goal (their MP blocks are not threshold work).
ABSOLUTE_LONG_KM = 20.0


def _num(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_run(workout: dict, goal_label: str) -> str:
    """Returns 'race', 'long', 'quality' or 'easy' from title and distance.

    Precedence: race > clearly long (titled 'long' or >= ABSOLUTE_LONG_KM) >
    quality title > goal-relative long distance > easy.
    """
    title = str(workout.get("title") or "")
    km = _num(workout.get("distance_actual_km")) or 0.0
    long_km = DISTANCE_PROFILES[goal_label]["long_km"]
    if is_race_title(title):
        return "race"
    if km >= ABSOLUTE_LONG_KM or "long" in title.lower():
        return "long"
    if is_quality_title(title):
        return "quality"
    if km >= long_km:
        return "long"
    return "easy"


def completed_runs(workouts: Optional[list[dict]], start: date, end: date) -> list[dict]:
    """Completed run workouts within [start, end], newest first."""
    runs = []
    for w in workouts or []:
        if str(w.get("sport", "")).lower() not in RUN_SPORTS:
            continue
        d = parse_date(w.get("date") or w.get("start_time"))
        if d is None or d < start or d > end:
            continue
        if not ((_num(w.get("distance_actual_km")) or 0) > 0 or (_num(w.get("duration_actual")) or 0) > 0):
            continue
        runs.append(w)
    return sorted(runs, key=lambda w: str(w.get("date") or ""), reverse=True)


def select_for_analysis(runs: list[dict], goal_label: str, max_n: int = MAX_ANALYSES) -> list[dict]:
    """Picks the most informative recent runs to analyse: races, quality, long runs."""
    buckets: dict[str, list[dict]] = {"race": [], "quality": [], "long": []}
    for w in runs:
        kind = classify_run(w, goal_label)
        if kind in buckets:
            buckets[kind].append(w)
    picked = buckets["race"][:2] + buckets["quality"][:4] + buckets["long"][:3]
    # Fill any spare slots with the remaining candidates, newest first.
    leftovers = [w for k in ("quality", "long", "race") for w in buckets[k] if w not in picked]
    picked += sorted(leftovers, key=lambda w: str(w.get("date") or ""), reverse=True)
    return picked[:max_n]


async def cache_read(user_id: Optional[str], workout_id: str) -> Optional[dict]:
    """Returns a valid cached workout summary, or None (cache miss / unavailable)."""
    if not user_id or not workout_id:
        return None
    try:
        cached = await firestore.get_cached_workout_analysis(user_id, workout_id)
    except Exception as e:  # Firestore unavailable (e.g. local runs) -> just analyse
        logger.info("Workout analysis cache read failed for %s: %s", workout_id, e)
        return None
    if (isinstance(cached, dict) and cached.get("version") == ANALYSIS_SCHEMA_VERSION
            and is_complete_summary(cached)):
        return cached
    return None


async def cache_write(user_id: Optional[str], workout_id: str, summary: dict) -> None:
    if not user_id or not workout_id:
        return
    try:
        await firestore.save_workout_analysis(user_id, workout_id, summary)
    except Exception as e:
        logger.info("Workout analysis cache write failed for %s: %s", workout_id, e)


async def load_workout_summaries(
    tool_context: ToolContext,
    workouts: list[dict],
    user_id: Optional[str],
    refresh: bool = False,
) -> list[dict]:
    """Cache-first workout summaries: reads Firestore, analyses only misses, saves new ones.

    Completed workouts don't change, so each tp_analyze_workout call is made once
    per workout; `refresh` bypasses the cache (e.g. after a schema/lap fix in TP).
    """
    ids = [str(w.get("id") or "") for w in workouts]
    cached = (
        [None] * len(workouts) if refresh
        else await asyncio.gather(*(cache_read(user_id, wid) for wid in ids))
    )
    misses = [i for i, c in enumerate(cached) if c is None and ids[i]]
    raws = await asyncio.gather(
        *(tp_calls.run_tp_tool(tool_context, "tp_analyze_workout", workout_id=ids[i]) for i in misses),
        return_exceptions=True,
    )
    summaries: list[Optional[dict]] = list(cached)
    writes = []
    for i, raw in zip(misses, raws):
        raw = result_or_none(raw, f"analysis {ids[i]}")
        summary = summarize_analysis(raw, workouts[i]) if raw else None
        summaries[i] = summary
        if is_complete_summary(summary):
            writes.append(cache_write(user_id, ids[i], summary))
    if writes:
        await asyncio.gather(*writes)
    logger.info(
        "Workout summaries: %d cached, %d analysed", len(workouts) - len(misses), len(misses)
    )
    return [s for s in summaries if s]
