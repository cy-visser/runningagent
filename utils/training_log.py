"""Training log: one structured, deterministic record per completed workout.

Pure functions (no I/O). `build_training_record` turns the TrainingPeaks payloads of one
workout into the document stored at users/{id}/training_log/{workout_id}. The record holds
facts only: anything that depends on the current goal is derived when the log is read.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from .classification import RUN_SPORTS, is_quality_title, is_race_title
from .metrics import as_float, pace_seconds
from .race_readiness import is_complete_summary, summarize_analysis
from .structure import (
    Alignment,
    align_laps,
    flatten_structure,
    has_structure,
    pa_hr_window,
    series_end,
    windowed_decoupling,
)

# Goal-independent run classification.
LONG_RUN_KM = 20.0
# A structured step targeting at least this % of threshold (pace or HR) makes the run a quality session.
QUALITY_TARGET_PCT = 87.0
WORK_INTENSITY = "active"


@dataclass(frozen=True)
class WorkoutBundle:
    """Everything needed to build one record; assembled by tools.load_workout_bundle."""

    meta: dict                          # tp_get_workout payload
    analysis: Optional[dict]            # tp_analyze_workout payload (runs only)
    series: Optional[list[dict]]        # time series from the analysis data_file (runs only)
    thresholds: dict                    # {"lthr", "threshold_speed"} in use when recorded
    weather: Optional[dict]             # get_conditions_at() at the start time
    context: dict                       # workout_context() for the workout day


def workout_context(day: Optional[date], daily_pmc: Optional[list[dict]], dated_metrics: Optional[dict]) -> dict:
    """CTL/ATL/TSB and the morning HRV/RHR/sleep of `day` (None where unknown)."""
    ctx: dict[str, Optional[float]] = {k: None for k in ("ctl", "atl", "tsb", "hrv", "rhr", "sleep_h")}
    if day is None:
        return ctx
    iso = day.isoformat()
    for row in daily_pmc or []:
        if str(row.get("date", ""))[:10] == iso:
            ctx.update(ctl=row.get("ctl"), atl=row.get("atl"), tsb=row.get("tsb"))
            break
    for key, out in (("hrv", "hrv"), ("rhr", "rhr"), ("sleep", "sleep_h")):
        values = [v for d, v in (dated_metrics or {}).get(key, []) if d == day]
        if values:
            ctx[out] = values[-1]
    return ctx


def _lap_seconds(lap: dict) -> float:
    return as_float(lap.get("TotalTimerTime")) or as_float(lap.get("TotalElapsedTime")) or 0.0


def _time_weighted(laps: list[dict], key: str) -> Optional[float]:
    pairs = [(as_float(lap.get(key)), _lap_seconds(lap)) for lap in laps]
    pairs = [(v, w) for v, w in pairs if v is not None and w > 0]
    total = sum(w for _, w in pairs)
    return round(sum(v * w for v, w in pairs) / total, 2) if total else None


def _target_pct(interval: dict) -> Optional[float]:
    target = interval.get("target") or {}
    if target.get("lo") is None or target.get("hi") is None:
        return None
    return (target["lo"] + target["hi"]) / 2


def align_structure(structured: Any, raw_laps: list[dict]) -> Optional[Alignment]:
    """Device laps aligned to the planned steps, or None (unstructured or laps don't line up)."""
    return align_laps(flatten_structure(structured), raw_laps) if has_structure(structured) else None


def work_intervals(alignment: Optional[Alignment], metric: Optional[str], lthr: Optional[float]) -> list[dict]:
    """Executed 'active' steps of a structured workout with their planned target."""
    if alignment is None:
        return []
    out = []
    for e in alignment.steps:
        if e.step.intensity != WORK_INTENSITY or e.step.target_lo is None or e.step.target_hi is None:
            continue
        rep = f" {e.step.rep}/{e.step.block_reps}" if e.step.block_reps > 1 else ""
        out.append({
            "step": f"B{e.step.block} {e.step.name}{rep}",
            "target": {"metric": metric, "lo": e.step.target_lo, "hi": e.step.target_hi},
            "duration_s": round(e.dur_s, 1),
            "distance_km": round(e.dist_km, 3) if e.dist_km else None,
            "pace_s": round(e.pace_s, 1) if e.pace_s else None,
            "ngp_s": pace_seconds(_time_weighted(e.laps, "NormalizedGradedPace")),
            "hr": round(e.hr_avg, 1) if e.hr_avg else None,
            "pct_lthr": round(e.hr_avg / lthr, 3) if e.hr_avg and lthr else None,
            "decoupling": _time_weighted(e.laps, "PacePulseDecoupling"),
        })
    return out


def classify_kind(title: str, distance_km: Optional[float], intervals: list[dict]) -> str:
    """'race' | 'long' | 'quality' | 'easy' from title, distance and structured targets (goal-independent)."""
    title = title or ""
    if is_race_title(title):
        return "race"
    if (distance_km or 0.0) >= LONG_RUN_KM or "long" in title.lower():
        return "long"
    if is_quality_title(title) or any((_target_pct(i) or 0.0) >= QUALITY_TARGET_PCT for i in intervals):
        return "quality"
    return "easy"


def _planned(metrics: dict) -> dict:
    hours = as_float(metrics.get("duration_planned"))
    return {
        "distance_km": as_float(metrics.get("distance_planned_km")),
        "duration_s": round(hours * 3600) if hours else None,
        "tss": as_float(metrics.get("tss_planned")),
    }


def _compliance_pct(actual_km, actual_s, planned: dict) -> Optional[float]:
    if actual_km and planned.get("distance_km"):
        return round(actual_km / planned["distance_km"] * 100, 1)
    if actual_s and planned.get("duration_s"):
        return round(actual_s / planned["duration_s"] * 100, 1)
    return None


def _athlete(meta: dict) -> dict:
    return {"rpe": as_float(meta.get("rpe")), "feeling": as_float(meta.get("feeling")),
            "comment": meta.get("new_comment") or None}


def build_training_record(b: WorkoutBundle, now: datetime) -> Optional[dict]:
    """Full record for a run whose laps cover >= 90% of the distance, a light record for
    other completed sports, None when the workout is incomplete or still syncing."""
    meta = b.meta or {}
    metrics = meta.get("metrics") or {}
    hours = as_float(metrics.get("duration_actual"))
    if not meta.get("id") or not hours:
        return None
    sport = str(meta.get("sport") or "")
    duration_s = round(hours * 3600)
    distance_km = as_float(metrics.get("distance_actual_km"))
    planned = _planned(metrics)
    record = {
        "recorded_at": now.isoformat(timespec="seconds"),
        "workout_id": str(meta["id"]),
        "date": str(meta.get("date") or "")[:10] or None,
        "sport": sport,
        "title": meta.get("title") or "",
        "kind": None,
        "distance_km": distance_km,
        "duration_s": duration_s,
        "tss": as_float(metrics.get("tss_actual")),
        "if": as_float(metrics.get("if_actual")),
        "planned": planned,
        "compliance_pct": _compliance_pct(distance_km, duration_s, planned),
        "context": b.context,
        "weather": b.weather,
        "athlete": _athlete(meta),
    }
    if sport.lower() not in RUN_SPORTS:
        return record

    analysis = b.analysis
    if not analysis:
        return None                                     # analysis fetch failed: retry later
    summary = summarize_analysis(analysis, {
        "id": meta["id"], "date": record["date"], "title": record["title"],
        "distance_actual_km": distance_km, "duration_actual": hours,
    })
    if summary is None or not summary["laps"]:
        record["kind"] = classify_kind(record["title"], distance_km, [])
        return record                                   # no lap data (e.g. manual entry): light run record
    if not is_complete_summary(summary):
        return None                                     # laps still syncing
    lthr = b.thresholds.get("lthr")
    raw_laps = [lap for lap in (analysis.get("lapData") or []) if isinstance(lap, dict)]
    totals = analysis.get("totals") or {}
    avg_hr = as_float(totals.get("Avg heart rate")) or _time_weighted(raw_laps, "AverageHeartRate")
    ngp_s = pace_seconds(totals.get("NGP"))
    if not ngp_s and distance_km:
        ngp_s = duration_s / distance_km
    structured = meta.get("structured_workout")
    alignment = align_structure(structured, raw_laps)
    intervals = work_intervals(alignment, (structured or {}).get("primaryIntensityMetric"), lthr)
    window = pa_hr_window(series_end(b.series, raw_laps), alignment)
    session_dec = windowed_decoupling(b.series, raw_laps, *window, sport)[0] if window else None
    record.update({
        "kind": classify_kind(record["title"], distance_km, intervals),
        "thresholds": {"lthr": lthr, "threshold_speed": b.thresholds.get("threshold_speed")},
        "avg_hr": avg_hr,
        "pct_lthr": round(avg_hr / lthr, 3) if avg_hr and lthr else None,
        "pa_hr": summary.get("pa_hr"),
        "session_decoupling": session_dec,
        "ef": round(60000.0 / ngp_s / avg_hr, 3) if ngp_s and avg_hr else None,
        "work_intervals": intervals,
        "laps": summary["laps"],
    })
    return record
