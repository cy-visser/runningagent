"""Compaction and completeness check for `tp_analyze_workout` lap summaries."""

from typing import Any, Optional

from .dates import parse_date
from .tp_payloads import coerce_mcp_payload
from .units import as_float, pace_seconds, to_km

# Bump when the cached workout-summary schema changes; older cache entries are ignored.
ANALYSIS_SCHEMA_VERSION = 1

# Cache only summaries whose laps cover this share of the workout distance
# (guards against caching a workout that is still syncing).
MIN_LAP_COVERAGE = 0.90


def summarize_analysis(raw: Any, workout: dict) -> Optional[dict]:
    """Compacts a tp_analyze_workout response into the cacheable workout summary."""
    payload = coerce_mcp_payload(raw) if raw else {}
    if not payload or payload.get("isError"):
        return None
    totals = payload.get("totals") or {}
    laps_raw = payload.get("lapData") or []
    if not laps_raw and not totals:
        return None

    laps, cum_km = [], 0.0
    for lap in laps_raw:
        if not isinstance(lap, dict):
            continue
        dur = as_float(lap.get("TotalTimerTime")) or as_float(lap.get("TotalMovingTime")) or as_float(lap.get("TotalElapsedTime"))
        if not dur or dur <= 0:
            continue
        dist_km = to_km(lap.get("TotalDistance")) or 0.0
        pace_s = pace_seconds(lap.get("AveragePace"))
        ngp_s = pace_seconds(lap.get("NormalizedGradedPace"))
        ref_pace = ngp_s or pace_s
        speed = 1000.0 / ref_pace if ref_pace else (dist_km * 1000.0 / dur if dist_km else None)
        laps.append({
            "duration_s": round(dur, 1),
            "distance_km": round(dist_km, 3),
            "pace_s": pace_s,
            "ngp_s": ngp_s,
            "speed_ms": round(speed, 4) if speed else None,
            "hr": as_float(lap.get("AverageHeartRate")),
            "decoupling": as_float(lap.get("PacePulseDecoupling")),
            "start_km": round(cum_km, 3),
        })
        cum_km += dist_km

    d = parse_date(workout.get("date") or workout.get("start_time"))
    return {
        "version": ANALYSIS_SCHEMA_VERSION,
        "workout_id": str(workout.get("id") or payload.get("workoutId") or ""),
        "date": d.isoformat() if d else None,
        "title": workout.get("title") or "",
        "distance_km": as_float(workout.get("distance_actual_km")) or as_float(totals.get("Distance")),
        "duration_s": (as_float(workout.get("duration_actual")) or 0) * 3600 or as_float(totals.get("Duration")),
        "pa_hr": as_float(totals.get("Pa:Hr")),
        "laps": laps,
    }


def is_complete_summary(summary: Optional[dict]) -> bool:
    """True when laps cover >= MIN_LAP_COVERAGE of the workout distance (safe to cache)."""
    if not summary or not summary.get("laps"):
        return False
    total = as_float(summary.get("distance_km"))
    if not total:
        return True
    covered = sum(as_float(lap.get("distance_km")) or 0.0 for lap in summary["laps"])
    return covered >= MIN_LAP_COVERAGE * total
