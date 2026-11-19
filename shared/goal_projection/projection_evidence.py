import asyncio
from datetime import date
import logging
from typing import Any, Optional

from google.adk.tools import ToolContext

from ...integrations.trainingpeaks import tp_calls
from ..analysis_summary import (
    ANALYSIS_SCHEMA_VERSION,
    is_complete_summary,
    summarize_analysis,
)
from ..dates import parse_date
from ..goal_distance import DISTANCE_PROFILES
from ..parallel_fetch import result_or_none
from ..sports import RUN_SPORTS, is_quality_title, is_race_title

logger = logging.getLogger(__name__)

PROJECTION_WINDOW_DAYS = 84   # 12 weeks of training history
MAX_ANALYSES = 14             # uncached key-session cap across 12 weeks (cached/logged runs are free)
# Runs this long are long runs whatever the goal (their MP blocks are not threshold work).
ABSOLUTE_LONG_KM = 20.0

# Quality-km thresholds (excludes <60s strides and Zone 2 easy runs <92% LT2 speed).
QUALITY_MIN_LAP_S = 60.0
QUALITY_MIN_KM = 0.5
QUALITY_STEP_TARGET_PCT = 87.0
QUALITY_HR_RATIO = 0.88
QUALITY_SPEED_RATIO = 0.92
QUALITY_GOAL_SPEED_RATIO = 0.95


def _num(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _interval_target_mid(interval: dict) -> Optional[float]:
    target = interval.get("target") or {}
    lo, hi = _num(target.get("lo")), _num(target.get("hi"))
    if lo is None or hi is None:
        return None
    return (lo + hi) / 2.0


def quality_distance_km(
    laps: Optional[list[dict]],
    *,
    title: str = "",
    distance_km: Optional[float] = None,
    lthr: Optional[float] = None,
    threshold_speed: Optional[float] = None,
    goal_speed: Optional[float] = None,
    work_intervals: Optional[list[dict]] = None,
    is_race: bool = False,
) -> float:
    """Kilometres of quality work in a run (races, structured >=87% steps, or >=60s quality laps)."""
    total_km = _num(distance_km) or 0.0
    if is_race or is_race_title(title):
        return round(total_km, 2) if total_km > 0 else 0.0

    interval_km = 0.0
    for iv in work_intervals or []:
        dur = _num(iv.get("duration_s")) or 0.0
        mid = _interval_target_mid(iv)
        if dur < QUALITY_MIN_LAP_S or mid is None or mid < QUALITY_STEP_TARGET_PCT:
            continue
        dkm = _num(iv.get("distance_km"))
        if dkm is None:
            pace_s = _num(iv.get("ngp_s")) or _num(iv.get("pace_s"))
            dkm = (dur / pace_s) if pace_s and pace_s > 0 else 0.0
        interval_km += max(0.0, dkm)

    lap_km = 0.0
    for lap in laps or []:
        dur = _num(lap.get("duration_s")) or 0.0
        if dur < QUALITY_MIN_LAP_S:
            continue  # neuromuscular strides (<60s) on an easy run do not make it a quality session
        hr = _num(lap.get("hr"))
        speed = _num(lap.get("speed_ms"))
        dkm = _num(lap.get("distance_km"))
        if dkm is None and speed and speed > 0:
            dkm = speed * dur / 1000.0
        if not dkm or dkm <= 0:
            continue
        hr_qual = bool(lthr and hr and hr >= QUALITY_HR_RATIO * lthr)
        thr_qual = bool(threshold_speed and speed and speed >= QUALITY_SPEED_RATIO * threshold_speed)
        goal_qual = bool(goal_speed and speed and speed >= QUALITY_GOAL_SPEED_RATIO * goal_speed)
        if hr_qual or thr_qual or goal_qual:
            lap_km += dkm

    best = max(interval_km, lap_km)
    if best <= 0 and is_quality_title(title) and not laps and not work_intervals and total_km > 0:
        # Manual or lap-less workout explicitly titled as a quality session.
        return round(total_km * 0.5, 2)
    return round(best, 2)


def has_quality_kms(
    laps: Optional[list[dict]],
    *,
    title: str = "",
    distance_km: Optional[float] = None,
    lthr: Optional[float] = None,
    threshold_speed: Optional[float] = None,
    goal_speed: Optional[float] = None,
    work_intervals: Optional[list[dict]] = None,
    is_race: bool = False,
) -> bool:
    """True when a completed run contains meaningful quality kilometres (>= 0.5 km or race)."""
    q_km = quality_distance_km(
        laps,
        title=title,
        distance_km=distance_km,
        lthr=lthr,
        threshold_speed=threshold_speed,
        goal_speed=goal_speed,
        work_intervals=work_intervals,
        is_race=is_race,
    )
    if q_km >= QUALITY_MIN_KM:
        return True
    total_km = _num(distance_km) or 0.0
    return total_km > 0 and (is_race or is_race_title(title))


def _record_has_quality(record: Optional[dict]) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("kind") in ("quality", "race"):
        return True
    thr = record.get("thresholds") or {}
    return has_quality_kms(
        record.get("laps"),
        title=str(record.get("title") or ""),
        distance_km=record.get("distance_km"),
        lthr=_num(thr.get("lthr")),
        threshold_speed=_num(thr.get("threshold_speed")),
        work_intervals=record.get("work_intervals"),
    )


def classify_run(workout: dict, goal_label: str, record: Optional[dict] = None) -> str:
    """Returns 'race', 'long', 'quality' or 'easy' from title, distance and recorded intervals/laps.

    Precedence: race > clearly long (titled 'long' or >= ABSOLUTE_LONG_KM) >
    quality (title or recorded quality intervals/laps) > goal-relative long distance > easy.
    """
    title = str(workout.get("title") or (record or {}).get("title") or "")
    km = _num(workout.get("distance_actual_km")) or _num(workout.get("distance_km")) or 0.0
    long_km = DISTANCE_PROFILES[goal_label]["long_km"]
    if is_race_title(title) or (record or {}).get("kind") == "race":
        return "race"
    if km >= ABSOLUTE_LONG_KM or "long" in title.lower():
        return "long"
    if is_quality_title(title) or _record_has_quality(record):
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


def select_for_analysis(
    runs: list[dict],
    goal_label: str,
    max_n: int = MAX_ANALYSES,
    records_by_id: Optional[dict[str, dict]] = None,
) -> list[dict]:
    """Picks the most informative runs in the 12-week window to analyse: races, quality, long runs."""
    records_by_id = records_by_id or {}
    buckets: dict[str, list[dict]] = {"race": [], "quality": [], "long": []}
    for w in runs:
        wid = str(w.get("id") or "")
        kind = classify_run(w, goal_label, records_by_id.get(wid))
        if kind in buckets:
            buckets[kind].append(w)
    picked = buckets["race"][:3] + buckets["quality"][:7] + buckets["long"][:4]
    # Fill any spare slots with the remaining key candidates, newest first.
    leftovers = [w for k in ("quality", "long", "race") for w in buckets[k] if w not in picked]
    picked += sorted(leftovers, key=lambda w: str(w.get("date") or ""), reverse=True)
    return picked[:max_n]


def summary_from_training_record(record: Optional[dict]) -> Optional[dict]:
    """Converts a complete training-log run record into a projection workout summary."""
    if not isinstance(record, dict) or str(record.get("sport") or "").lower() not in RUN_SPORTS:
        return None
    if not record.get("laps"):
        return None
    summary = {
        "version": ANALYSIS_SCHEMA_VERSION,
        "workout_id": str(record.get("workout_id") or ""),
        "date": record.get("date"),
        "title": record.get("title") or "",
        "distance_km": _num(record.get("distance_km")),
        "duration_s": _num(record.get("duration_s")),
        "pa_hr": _num(record.get("pa_hr")),
        "laps": record["laps"],
        "weather": record.get("weather"),
        "work_intervals": record.get("work_intervals"),
        "kind": record.get("kind"),
    }
    return summary if is_complete_summary(summary) else None


async def load_workout_summaries(
    tool_context: ToolContext,
    workouts: list[dict],
    refresh: bool = False,
    training_records: Optional[list[dict]] = None,
    goal_label: Optional[str] = None,
) -> list[dict]:
    """Training-log-first workout summaries across the 12-week window.

    Any run already recorded in `training_records` (from `analyze_workout` or trend gap-fill) is
    included at zero TrainingPeaks API cost; `workouts` (from `select_for_analysis`) fills any
    remaining key sessions via `tp_analyze_workout`.
    """
    records_by_id = {
        str(r.get("workout_id")): r
        for r in (training_records or [])
        if isinstance(r, dict) and r.get("workout_id")
    }
    by_id: dict[str, dict] = {}
    if not refresh:
        for wid, rec in records_by_id.items():
            s = summary_from_training_record(rec)
            if s:
                by_id[wid] = s

    pending = [w for w in workouts if str(w.get("id") or "") and str(w.get("id")) not in by_id]
    ids = [str(w.get("id")) for w in pending]
    raws = await asyncio.gather(
        *(tp_calls.run_tp_tool(tool_context, "tp_analyze_workout", workout_id=wid) for wid in ids),
        return_exceptions=True,
    )
    for w, wid, raw in zip(pending, ids, raws):
        raw = result_or_none(raw, f"analysis {wid}")
        summary = summarize_analysis(raw, w) if raw else None
        if summary and wid:
            by_id[wid] = summary

    out = list(by_id.values())
    if goal_label:
        for s in out:
            wid = str(s.get("workout_id") or "")
            rec = records_by_id.get(wid)
            s["session_kind"] = classify_run(
                s | {"distance_actual_km": s.get("distance_km")}, goal_label, rec
            )
    out.sort(key=lambda s: str(s.get("date") or ""), reverse=True)
    logger.info(
        "Workout summaries: %d from training_log, %d analysed live",
        len(out) - len(pending), len(pending),
    )
    return out
