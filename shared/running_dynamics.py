"""Running dynamics extraction, late-run mechanical fatigue detection, and pace-normalized form trends.

All metrics are computed strictly from active running telemetry (`Cadence >= 130 spm`, `Speed >= 5 km/h`,
positive sensor readings) to avoid TrainingPeaks' zero-contaminated channel averages on runs with stops or
walk breaks. `Vertical Ratio` is derived to 0.01% precision from `VerticalOscillation / StepLength` whenever
both channels exist, avoiding TrainingPeaks' 1% integer rounding.
"""

from __future__ import annotations

from datetime import date, timedelta
import math
from statistics import median
from typing import Any, Optional

from .dates import parse_date
from .sports import RUN_SPORTS
from .units import as_float, fmt_clock, fmt_pace, pace_seconds
from .workout_structure import (
    COOLDOWN_INTENSITY,
    WARMUP_INTENSITY,
    Alignment,
    ExecutedStep,
    lap_km,
    lap_time,
    pa_hr_window,
    series_end,
)

# Bump when stored running-dynamics fields on training_log records change.
DYNAMICS_SCHEMA_VERSION = 1

# Active-running filters (excludes stops, traffic lights, and walk breaks).
MIN_RUN_CADENCE = 130.0
MIN_RUN_SPEED_KPH = 5.0
HALF_CADENCE_MIN, HALF_CADENCE_MAX = 65.0, 105.0
HALF_CADENCE_MIN_SPEED_KPH = 6.0

# Physiological sensor sanity bounds.
GCT_BOUNDS = (140.0, 400.0)
STRIDE_BOUNDS = (0.45, 2.20)
VERT_OSC_BOUNDS = (3.0, 18.0)
VERT_RATIO_BOUNDS = (3.0, 20.0)
BALANCE_BOUNDS = (40.0, 60.0)

# Late-run mechanical drift windows & fatigue thresholds.
DRIFT_MIN_WINDOW_S = 20 * 60
DRIFT_MIN_BLOCK_S = 15 * 60
DRIFT_MIN_REP_S = 120.0
DRIFT_MIN_SEGMENT_PTS = 20
DRIFT_SPEEDUP_GUARD_PCT = 4.0

# Pace-normalized rolling form window (matches LT_FIT_WEEKS = 4).
FORM_FIT_WEEKS = 4
STEADY_FORM_MIN_S = 180.0
MIN_FORM_LAPS = 3
FORM_SPEED_BAND_REL = 0.08
FORM_REGRESSION_SPREAD_REL = 0.05
FORM_EXTRAPOLATION_REL = 0.05

# Speed bands relative to threshold speed (matching pacing.py).
DYNAMICS_BANDS = (
    ("Easy", 0.0, 0.80),
    ("Steady / MP", 0.80, 0.93),
    ("Threshold", 0.93, 1.02),
    ("Fast / 5K+", 1.02, 10.0),
)
FALLBACK_SPEED_BANDS = (
    ("Easy", 0.0, 2.95),
    ("Steady / MP", 2.95, 3.35),
    ("Threshold", 3.35, 3.80),
    ("Fast / 5K+", 3.80, 10.0),
)
MIN_BAND_LAP_S = 60.0

_GCT_LAP_KEYS = ("AverageStanceTime", "AverageGroundContactTime", "groundContactTime", "ContactTime", "gct")
_BAL_LAP_KEYS = ("AverageGroundContactTimeBalance", "groundContactTimeBalance", "gctBalance", "AverageStanceTimeBalance")
_VO_LAP_KEYS = ("AverageVerticalOscillation", "verticalOscillation", "vertOsc")
_SL_LAP_KEYS = ("AverageStepLength", "AverageStrideLength", "strideLength", "stepLength")
_VR_LAP_KEYS = ("AverageVerticalRatio", "verticalRatio")
_GCT_SERIES_KEYS = ("StanceTime", "GroundContactTime", "ContactTime", "GCT")
_BAL_SERIES_KEYS = ("GroundContactTimeBalance", "StanceTimeBalance", "GCTBalance")
_SL_SERIES_KEYS = ("StepLength", "StrideLength")
_VO_SERIES_KEYS = ("VerticalOscillation", "VertOsc")
_VR_SERIES_KEYS = ("VerticalRatio",)


def _first_float(mapping: dict, keys: tuple[str, ...]) -> Optional[float]:
    for key in keys:
        val = as_float(mapping.get(key))
        if val is not None:
            return val
    return None


def _in_bounds(val: Optional[float], bounds: tuple[float, float]) -> Optional[float]:
    if val is None:
        return None
    return val if bounds[0] <= val <= bounds[1] else None


def normalize_cadence(val: Any, speed_kph: Optional[float] = None) -> Optional[float]:
    """Full-stride cadence in spm; doubles single-foot half-cadence when clearly running."""
    c = as_float(val)
    if c is None or c <= 0:
        return None
    if HALF_CADENCE_MIN <= c <= HALF_CADENCE_MAX and (speed_kph is None or speed_kph >= HALF_CADENCE_MIN_SPEED_KPH):
        c *= 2.0
    return c if MIN_RUN_CADENCE <= c <= 240.0 else None


def normalize_gct(val: Any) -> Optional[float]:
    return _in_bounds(as_float(val), GCT_BOUNDS)


def normalize_stride(val: Any) -> Optional[float]:
    """Step length in metres (converts mm -> m when > 20)."""
    s = as_float(val)
    if s is None or s <= 0:
        return None
    if s > 20.0:
        s /= 1000.0
    return _in_bounds(s, STRIDE_BOUNDS)


def normalize_vert_osc(val: Any) -> Optional[float]:
    """Vertical oscillation in centimetres (converts mm -> cm when > 20)."""
    v = as_float(val)
    if v is None or v <= 0:
        return None
    if v > 20.0:
        v /= 10.0
    return _in_bounds(v, VERT_OSC_BOUNDS)


def normalize_balance(val: Any) -> Optional[float]:
    return _in_bounds(as_float(val), BALANCE_BOUNDS)


def derive_vert_ratio(
    vert_osc_cm: Optional[float], stride_m: Optional[float], fallback: Any = None
) -> Optional[float]:
    """Vertical ratio (%) = vert_osc_cm / stride_m (since cm / (m * 100) * 100 = cm / m)."""
    if vert_osc_cm and stride_m and stride_m > 0:
        return _in_bounds(round(vert_osc_cm / stride_m, 2), VERT_RATIO_BOUNDS)
    return _in_bounds(as_float(fallback), VERT_RATIO_BOUNDS)


def has_running_dynamics(dyn: Optional[dict]) -> bool:
    """True when at least one biomechanical metric beyond bare cadence is present."""
    if not isinstance(dyn, dict):
        return False
    return any(dyn.get(k) is not None for k in ("gct_ms", "stride_m", "vert_osc_cm", "vert_ratio_pct"))


def _lap_speed_kph(lap: dict) -> Optional[float]:
    spd = as_float(lap.get("AverageSpeed"))
    if spd is not None and spd > 0:
        return spd if spd > 5.0 else spd * 3.6
    pace = pace_seconds(lap.get("AveragePace"))
    if pace and pace > 0:
        return 3600.0 / pace
    dur, km = lap_time(lap), lap_km(lap)
    return (km / dur * 3600.0) if dur > 0 and km > 0 else None


def extract_lap_dynamics(lap: dict) -> dict[str, float]:
    """Normalized running-dynamics fields for one lap (empty dict on walks or missing data)."""
    if not isinstance(lap, dict):
        return {}
    spd_kph = _lap_speed_kph(lap)
    if spd_kph is not None and spd_kph < MIN_RUN_SPEED_KPH:
        return {}
    raw_cad = as_float(lap.get("AverageCadence"))
    cad = normalize_cadence(raw_cad, spd_kph)
    # If cadence is recorded and clearly below running threshold (e.g. walk break), skip dynamics.
    if raw_cad is not None and raw_cad > 0 and cad is None:
        return {}

    gct = normalize_gct(_first_float(lap, _GCT_LAP_KEYS))
    stride = normalize_stride(_first_float(lap, _SL_LAP_KEYS))
    vo = normalize_vert_osc(_first_float(lap, _VO_LAP_KEYS))
    vr = derive_vert_ratio(vo, stride, _first_float(lap, _VR_LAP_KEYS))
    bal = normalize_balance(_first_float(lap, _BAL_LAP_KEYS))

    out: dict[str, float] = {}
    if cad is not None:
        out["cadence"] = round(cad, 1)
    if gct is not None:
        out["gct_ms"] = round(gct, 1)
    if stride is not None:
        out["stride_m"] = round(stride, 3)
    if vo is not None:
        out["vert_osc_cm"] = round(vo, 2)
    if vr is not None:
        out["vert_ratio_pct"] = round(vr, 2)
    if bal is not None:
        out["gct_balance"] = round(bal, 1)
    return out


def _running_series_points(
    series: Optional[list[dict]], t0: Optional[float] = None, t1: Optional[float] = None
) -> list[dict[str, float]]:
    """Active-running 1-Hz telemetry points with normalized dynamics (stops & walks removed)."""
    out: list[dict[str, float]] = []
    for pt in series or []:
        if not isinstance(pt, dict):
            continue
        t = as_float(pt.get("time"))
        if t0 is not None and (t is None or t < t0):
            continue
        if t1 is not None and (t is None or t >= t1):
            continue
        spd_kph = as_float(pt.get("Speed"))
        if spd_kph is not None and spd_kph < MIN_RUN_SPEED_KPH:
            continue
        raw_cad = as_float(pt.get("Cadence"))
        cad = normalize_cadence(raw_cad, spd_kph)
        if raw_cad is not None and cad is None:
            continue
        gct = normalize_gct(_first_float(pt, _GCT_SERIES_KEYS))
        stride = normalize_stride(_first_float(pt, _SL_SERIES_KEYS))
        vo = normalize_vert_osc(_first_float(pt, _VO_SERIES_KEYS))
        bal = normalize_balance(_first_float(pt, _BAL_SERIES_KEYS))
        if cad is None and gct is None and stride is None and vo is None:
            continue
        item: dict[str, float] = {}
        if t is not None:
            item["t"] = t
        if spd_kph is not None and spd_kph > 0:
            item["speed_ms"] = spd_kph / 3.6
        if cad is not None:
            item["cadence"] = cad
        if gct is not None:
            item["gct_ms"] = gct
        if stride is not None:
            item["stride_m"] = stride
        if vo is not None:
            item["vert_osc_cm"] = vo
        vr = derive_vert_ratio(vo, stride, _first_float(pt, _VR_SERIES_KEYS))
        if vr is not None:
            item["vert_ratio_pct"] = vr
        if bal is not None:
            item["gct_balance"] = bal
        out.append(item)
    return out


def _mean_metric(items: list[dict[str, float]], key: str) -> Optional[float]:
    vals = [p[key] for p in items if key in p]
    return sum(vals) / len(vals) if vals else None


def _weighted_dynamics(laps: list[dict]) -> Optional[dict[str, float]]:
    """Duration-weighted running dynamics across running laps."""
    weights: dict[str, list[tuple[float, float]]] = {
        k: [] for k in ("cadence", "gct_ms", "stride_m", "vert_osc_cm", "vert_ratio_pct", "gct_balance")
    }
    for lap in laps:
        dur = lap_time(lap) if "TotalTimerTime" in lap or "TotalElapsedTime" in lap else (as_float(lap.get("duration_s")) or 0.0)
        if dur <= 0:
            continue
        dyn = extract_lap_dynamics(lap) if any(k in lap for k in (*_GCT_LAP_KEYS, *_SL_LAP_KEYS, *_VO_LAP_KEYS, "AverageCadence")) else lap
        for k in weights:
            val = as_float(dyn.get(k))
            if val is not None:
                weights[k].append((val, dur))

    def wavg(k: str) -> Optional[float]:
        pairs = weights[k]
        total = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / total if total > 0 else None

    cad, gct, stride, vo, bal = (wavg(k) for k in ("cadence", "gct_ms", "stride_m", "vert_osc_cm", "gct_balance"))
    vr = derive_vert_ratio(vo, stride, wavg("vert_ratio_pct"))
    out: dict[str, float] = {}
    if cad is not None:
        out["cadence"] = round(cad, 1)
    if gct is not None:
        out["gct_ms"] = round(gct, 1)
    if stride is not None:
        out["stride_m"] = round(stride, 3)
    if vo is not None:
        out["vert_osc_cm"] = round(vo, 2)
    if vr is not None:
        out["vert_ratio_pct"] = round(vr, 2)
    if bal is not None:
        out["gct_balance"] = round(bal, 1)
    return out or None


def _channels_dynamics(channels: Optional[list[dict]]) -> Optional[dict[str, float]]:
    """Fallback only when no series/laps exist; skips zero-contaminated channels (min == 0)."""
    by_id: dict[str, dict] = {}
    for ch in channels or []:
        if isinstance(ch, dict) and ch.get("identifier"):
            by_id[str(ch["identifier"])] = ch

    def clean_avg(ids: tuple[str, ...]) -> Optional[float]:
        for ident in ids:
            ch = by_id.get(ident)
            if not ch:
                continue
            avg = as_float(ch.get("average"))
            lo = as_float(ch.get("min"))
            if avg is None or avg <= 0:
                continue
            if lo is not None and lo <= 0:
                continue  # zero-contaminated by stops/walk breaks
            return avg
        return None

    cad = normalize_cadence(clean_avg(("Cadence",)))
    gct = normalize_gct(clean_avg(("StanceTime", "GroundContactTime", "ContactTime", "GCT")))
    stride = normalize_stride(clean_avg(("StepLength", "StrideLength")))
    vo = normalize_vert_osc(clean_avg(("VerticalOscillation", "VertOsc")))
    vr = derive_vert_ratio(vo, stride, clean_avg(("VerticalRatio",)))
    bal = normalize_balance(clean_avg(("GroundContactTimeBalance", "StanceTimeBalance", "GCTBalance")))
    out: dict[str, float] = {}
    if cad is not None:
        out["cadence"] = round(cad, 1)
    if gct is not None:
        out["gct_ms"] = round(gct, 1)
    if stride is not None:
        out["stride_m"] = round(stride, 3)
    if vo is not None:
        out["vert_osc_cm"] = round(vo, 2)
    if vr is not None:
        out["vert_ratio_pct"] = round(vr, 2)
    if bal is not None:
        out["gct_balance"] = round(bal, 1)
    return out or None


def extract_session_dynamics(
    series: Optional[list[dict]],
    raw_laps: Optional[list[dict]],
    data_channels: Optional[list[dict]] = None,
) -> Optional[dict[str, float]]:
    """Clean, running-only session running dynamics (series -> laps -> clean dataChannels)."""
    pts = _running_series_points(series)
    if pts:
        cad = _mean_metric(pts, "cadence")
        gct = _mean_metric(pts, "gct_ms")
        stride = _mean_metric(pts, "stride_m")
        vo = _mean_metric(pts, "vert_osc_cm")
        vr = derive_vert_ratio(vo, stride, _mean_metric(pts, "vert_ratio_pct"))
        bal = _mean_metric(pts, "gct_balance")
        out: dict[str, float] = {}
        if cad is not None:
            out["cadence"] = round(cad, 1)
        if gct is not None:
            out["gct_ms"] = round(gct, 1)
        if stride is not None:
            out["stride_m"] = round(stride, 3)
        if vo is not None:
            out["vert_osc_cm"] = round(vo, 2)
        if vr is not None:
            out["vert_ratio_pct"] = round(vr, 2)
        if bal is not None:
            out["gct_balance"] = round(bal, 1)
        if has_running_dynamics(out):
            return out
    lap_dyn = _weighted_dynamics(raw_laps or [])
    if has_running_dynamics(lap_dyn):
        return lap_dyn
    ch_dyn = _channels_dynamics(data_channels)
    if has_running_dynamics(ch_dyn):
        return ch_dyn
    return None


# ------------------------------------------------------------------------------
# Late-run mechanical fatigue detection
# ------------------------------------------------------------------------------

def _segment_stats(pts: list[dict[str, float]]) -> Optional[dict[str, Optional[float]]]:
    if len(pts) < DRIFT_MIN_SEGMENT_PTS:
        return None
    gct = _mean_metric(pts, "gct_ms")
    stride = _mean_metric(pts, "stride_m")
    vo = _mean_metric(pts, "vert_osc_cm")
    vr = derive_vert_ratio(vo, stride, _mean_metric(pts, "vert_ratio_pct"))
    cad = _mean_metric(pts, "cadence")
    speed = _mean_metric(pts, "speed_ms")
    if not any(v is not None for v in (gct, stride, vr)):
        return None
    return {"speed_ms": speed, "cadence": cad, "gct_ms": gct, "stride_m": stride, "vert_ratio_pct": vr}


def _laps_segment_stats(laps: list[dict]) -> Optional[dict[str, Optional[float]]]:
    dyn = _weighted_dynamics(laps)
    if not has_running_dynamics(dyn):
        return None
    dur = sum(lap_time(l) for l in laps)
    km = sum(lap_km(l) for l in laps)
    speed = (km * 1000.0 / dur) if dur > 0 and km > 0 else None
    return {
        "speed_ms": speed,
        "cadence": dyn.get("cadence") if dyn else None,
        "gct_ms": dyn.get("gct_ms") if dyn else None,
        "stride_m": dyn.get("stride_m") if dyn else None,
        "vert_ratio_pct": dyn.get("vert_ratio_pct") if dyn else None,
    }


def _is_fatigue_fade(
    speed_delta_pct: Optional[float],
    gct_delta_ms: Optional[float],
    gct_delta_pct: Optional[float],
    vr_delta_pp: Optional[float],
    cadence_delta: Optional[float],
    stride_delta_pct: Optional[float],
) -> bool:
    """True when late-run mechanics degrade meaningfully without an intentional fast pickup explaining it."""
    if speed_delta_pct is not None and speed_delta_pct > DRIFT_SPEEDUP_GUARD_PCT:
        # Runner sped up noticeably: only flag if stiffness/bounce STILL worsened significantly.
        return bool(
            (gct_delta_ms is not None and gct_delta_ms >= 8.0)
            or (vr_delta_pp is not None and vr_delta_pp >= 0.5)
        )
    strong = 0
    moderate = 0
    if gct_delta_ms is not None:
        if gct_delta_ms >= 14.0 or (gct_delta_pct is not None and gct_delta_pct >= 6.0):
            strong += 1
        elif gct_delta_ms >= 8.0 or (gct_delta_pct is not None and gct_delta_pct >= 3.5):
            moderate += 1
    if vr_delta_pp is not None:
        if vr_delta_pp >= 1.0:
            strong += 1
        elif vr_delta_pp >= 0.5:
            moderate += 1
    if cadence_delta is not None:
        if cadence_delta <= -7.0:
            strong += 1
        elif cadence_delta <= -4.0:
            moderate += 1
    if stride_delta_pct is not None:
        if stride_delta_pct <= -7.0:
            strong += 1
        elif stride_delta_pct <= -4.0:
            moderate += 1
    return strong >= 1 or moderate >= 2


def _build_drift_dict(
    scope: str, early: dict[str, Optional[float]], late: dict[str, Optional[float]]
) -> Optional[dict[str, Any]]:
    spd_e, spd_l = early.get("speed_ms"), late.get("speed_ms")
    speed_delta_pct = round((spd_l - spd_e) / spd_e * 100.0, 1) if spd_e and spd_l else None

    gct_e, gct_l = early.get("gct_ms"), late.get("gct_ms")
    gct_delta_ms = round(gct_l - gct_e, 1) if gct_e is not None and gct_l is not None else None
    gct_delta_pct = ((gct_l - gct_e) / gct_e * 100.0) if gct_e and gct_l else None

    cad_e, cad_l = early.get("cadence"), late.get("cadence")
    cadence_delta = round(cad_l - cad_e, 1) if cad_e is not None and cad_l is not None else None

    sl_e, sl_l = early.get("stride_m"), late.get("stride_m")
    stride_delta_pct = round((sl_l - sl_e) / sl_e * 100.0, 1) if sl_e and sl_l else None

    vr_e, vr_l = early.get("vert_ratio_pct"), late.get("vert_ratio_pct")
    vr_delta_pp = round(vr_l - vr_e, 2) if vr_e is not None and vr_l is not None else None

    if all(v is None for v in (gct_delta_ms, vr_delta_pp, stride_delta_pct)):
        return None
    return {
        "scope": scope,
        "speed_delta_pct": speed_delta_pct,
        "gct_delta_ms": gct_delta_ms,
        "cadence_delta": cadence_delta,
        "stride_delta_pct": stride_delta_pct,
        "vr_delta_pp": vr_delta_pp,
        "fatigue_flag": _is_fatigue_fade(
            speed_delta_pct, gct_delta_ms, gct_delta_pct, vr_delta_pp, cadence_delta, stride_delta_pct
        ),
    }


def _primary_repeated_reps(alignment: Alignment) -> Optional[tuple[str, list[ExecutedStep]]]:
    """Primary repeated active work reps (>= DRIFT_MIN_REP_S, >= 2 reps)."""
    blocks: dict[tuple[int, int], list[ExecutedStep]] = {}
    for e in alignment.steps:
        if e.step.intensity == "active" and e.step.block_reps >= 2 and e.dur_s >= DRIFT_MIN_REP_S:
            blocks.setdefault((e.step.block, e.step.pos), []).append(e)
    candidates = [reps for reps in blocks.values() if len(reps) >= 2]
    if not candidates:
        return None
    best = max(candidates, key=lambda reps: sum(r.dur_s for r in reps))
    label = f"reps ({len(best)}x {best[0].step.name})"
    return label, best


def _longest_work_block(alignment: Alignment) -> Optional[tuple[str, list[ExecutedStep]]]:
    """Longest continuous non-warmup/non-cooldown step/block >= DRIFT_MIN_BLOCK_S."""
    blocks: dict[int, list[ExecutedStep]] = {}
    for e in alignment.steps:
        if e.step.intensity not in (WARMUP_INTENSITY, COOLDOWN_INTENSITY):
            blocks.setdefault(e.step.block, []).append(e)
    best: Optional[tuple[float, str, list[ExecutedStep]]] = None
    for execs in blocks.values():
        dur = sum(e.dur_s for e in execs)
        if dur >= DRIFT_MIN_BLOCK_S and (best is None or dur > best[0]):
            best = (dur, f"block ({execs[0].step.name})", execs)
    return (best[1], best[2]) if best else None


def _window_drift(
    scope: str, series: Optional[list[dict]], laps: list[dict], t0: float, t1: float
) -> Optional[dict[str, Any]]:
    pts = _running_series_points(series, t0, t1)
    if len(pts) >= 2 * DRIFT_MIN_SEGMENT_PTS:
        mid = t0 + (t1 - t0) * 0.50
        late_cut = t0 + (t1 - t0) * (2.0 / 3.0)
        early = _segment_stats([p for p in pts if p.get("t", 0.0) < mid])
        late = _segment_stats([p for p in pts if p.get("t", 0.0) >= late_cut])
        if early and late:
            return _build_drift_dict(scope, early, late)
    inside = [
        l for l in laps
        if isinstance(l, dict)
        and t0 <= ((as_float(l.get("startOffsetSeconds")) or 0.0) + lap_time(l) / 2.0) < t1
        and has_running_dynamics(extract_lap_dynamics(l))
    ]
    if len(inside) >= 4:
        half = len(inside) // 2
        tail = max(1, len(inside) // 3)
        early = _laps_segment_stats(inside[:half])
        late = _laps_segment_stats(inside[-tail:])
        if early and late:
            return _build_drift_dict(scope, early, late)
    return None


def compute_late_run_drift(
    series: Optional[list[dict]],
    raw_laps: Optional[list[dict]],
    alignment: Optional[Alignment] = None,
) -> Optional[dict[str, Any]]:
    """Early-vs-late (or rep-1-vs-last-rep) biomechanical drift for one run."""
    laps = [l for l in (raw_laps or []) if isinstance(l, dict)]
    if alignment is not None:
        rep_group = _primary_repeated_reps(alignment)
        if rep_group:
            scope, reps = rep_group
            early_laps = [l for r in reps[: max(1, len(reps) // 2)] for l in r.laps]
            late_laps = reps[-1].laps
            early = _laps_segment_stats(early_laps)
            late = _laps_segment_stats(late_laps)
            if early and late:
                return _build_drift_dict(scope, early, late)
        work_block = _longest_work_block(alignment)
        if work_block:
            scope, execs = work_block
            drift = _window_drift(scope, series, [l for e in execs for l in e.laps], execs[0].start, execs[-1].end)
            if drift:
                return drift

    window = pa_hr_window(series_end(series, laps), alignment)
    if not window or (window[1] - window[0]) < DRIFT_MIN_WINDOW_S:
        return None
    return _window_drift("session", series, laps, window[0], window[1])


# ------------------------------------------------------------------------------
# Pace-normalized form trends & cadence-vs-stride speed modulation
# ------------------------------------------------------------------------------

def _is_run_record(record: dict) -> bool:
    return str(record.get("sport") or "").lower() in RUN_SPORTS


def _record_steady_rd_laps(records: list[dict], *, min_s: float = STEADY_FORM_MIN_S) -> list[tuple[dict, dict]]:
    out: list[tuple[dict, dict]] = []
    for r in records:
        if not _is_run_record(r):
            continue
        for lap in r.get("laps") or []:
            if not isinstance(lap, dict):
                continue
            dur = as_float(lap.get("duration_s")) or 0.0
            spd = as_float(lap.get("speed_ms"))
            cad = as_float(lap.get("cadence"))
            if dur < min_s or not spd or spd * 3.6 < MIN_RUN_SPEED_KPH:
                continue
            if cad is not None and cad < MIN_RUN_CADENCE:
                continue
            if not has_running_dynamics(lap):
                continue
            out.append((r, lap))
    return out


def _weighted_median(pairs: list[tuple[float, float]]) -> Optional[float]:
    pairs = sorted((v, w) for v, w in pairs if w > 0)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    acc = 0.0
    half = total / 2.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return v
    return pairs[-1][0]


def reference_easy_speed(records: list[dict]) -> Optional[float]:
    """Fixed reference aerobic speed (m/s) across a window so every week compares form at the exact same pace."""
    easy_pairs: list[tuple[float, float]] = []
    all_pairs: list[tuple[float, float]] = []
    for r, lap in _record_steady_rd_laps(records):
        spd, dur = float(lap["speed_ms"]), float(lap["duration_s"])
        all_pairs.append((spd, dur))
        if r.get("kind") == "easy":
            easy_pairs.append((spd, dur))
    return _weighted_median(easy_pairs) if len(easy_pairs) >= MIN_FORM_LAPS else _weighted_median(all_pairs)


def _eval_metric_at_speed(
    pts: list[tuple[float, float, float]], ref_speed: float, bounds: tuple[float, float]
) -> Optional[float]:
    """Duration-weighted linear regression at `ref_speed` when speed spread is wide, else pace-matched mean."""
    if len(pts) < MIN_FORM_LAPS:
        return None
    speeds = [p[0] for p in pts]
    s_min, s_max = min(speeds), max(speeds)
    spread = s_max - s_min
    margin = FORM_EXTRAPOLATION_REL * ref_speed
    if len(pts) >= 4 and spread >= FORM_REGRESSION_SPREAD_REL * ref_speed and (s_min - margin) <= ref_speed <= (s_max + margin):
        w_sum = sum(p[2] for p in pts)
        mx = sum(p[0] * p[2] for p in pts) / w_sum
        my = sum(p[1] * p[2] for p in pts) / w_sum
        sxx = sum(p[2] * (p[0] - mx) ** 2 for p in pts)
        sxy = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts)
        if sxx > 0:
            est = my + (sxy / sxx) * (ref_speed - mx)
            if bounds[0] <= est <= bounds[1]:
                return est

    matched = [p for p in pts if abs(p[0] - ref_speed) / ref_speed <= FORM_SPEED_BAND_REL]
    if len(matched) < MIN_FORM_LAPS:
        matched = [p for p in pts if abs(p[0] - ref_speed) / ref_speed <= 0.12]
    if len(matched) < MIN_FORM_LAPS:
        return None
    w_sum = sum(p[2] for p in matched)
    est = sum(p[1] * p[2] for p in matched) / w_sum
    return est if bounds[0] <= est <= bounds[1] else None


def form_at_speed(
    records: list[dict],
    week_end: date,
    ref_speed_ms: Optional[float],
    weeks: int = FORM_FIT_WEEKS,
) -> Optional[dict[str, Any]]:
    """Pace-normalized running dynamics evaluated at `ref_speed_ms` over the `weeks` ending `week_end`."""
    if not ref_speed_ms or ref_speed_ms <= 0:
        return None
    start = (week_end - timedelta(weeks=weeks) + timedelta(days=1)).isoformat()
    end = week_end.isoformat()
    window = [r for r in records if _is_run_record(r) and start <= (r.get("date") or "") <= end]
    pairs = _record_steady_rd_laps(window)
    if len(pairs) < MIN_FORM_LAPS:
        return None

    def collect(key: str) -> list[tuple[float, float, float]]:
        return [
            (float(lap["speed_ms"]), float(lap[key]), float(lap["duration_s"]))
            for _, lap in pairs
            if as_float(lap.get(key)) is not None
        ]

    gct = _eval_metric_at_speed(collect("gct_ms"), ref_speed_ms, GCT_BOUNDS)
    vo = _eval_metric_at_speed(collect("vert_osc_cm"), ref_speed_ms, VERT_OSC_BOUNDS)
    stride = _eval_metric_at_speed(collect("stride_m"), ref_speed_ms, STRIDE_BOUNDS)
    cad = _eval_metric_at_speed(collect("cadence"), ref_speed_ms, (MIN_RUN_CADENCE, 240.0))
    vr = derive_vert_ratio(vo, stride, _eval_metric_at_speed(collect("vert_ratio_pct"), ref_speed_ms, VERT_RATIO_BOUNDS))
    if gct is None and vr is None:
        return None
    return {
        "ref_pace_s": round(1000.0 / ref_speed_ms, 1),
        "gct_ms": round(gct, 1) if gct is not None else None,
        "vert_ratio_pct": round(vr, 2) if vr is not None else None,
        "vert_osc_cm": round(vo, 2) if vo is not None else None,
        "cadence": round(cad, 1) if cad is not None else None,
        "stride_m": round(stride, 3) if stride is not None else None,
        "laps": len(pairs),
    }


def dynamics_by_band(
    records: list[dict],
    threshold_speed: Optional[float],
    today: date,
    weeks: int = 6,
) -> Optional[dict[str, Any]]:
    """Running mechanics grouped by pace band plus cadence-vs-stride speed-gain decomposition."""
    start = (today - timedelta(weeks=weeks)).isoformat()
    window = [r for r in records if _is_run_record(r) and (r.get("date") or "") >= start]
    pairs = _record_steady_rd_laps(window, min_s=MIN_BAND_LAP_S)
    if not pairs:
        return None

    buckets: dict[str, list[dict]] = {}
    band_defs = DYNAMICS_BANDS if (threshold_speed and threshold_speed > 0) else FALLBACK_SPEED_BANDS
    for _, lap in pairs:
        val = float(lap["speed_ms"]) / threshold_speed if (threshold_speed and threshold_speed > 0) else float(lap["speed_ms"])
        name = next((b for b, lo, hi in band_defs if lo <= val < hi), band_defs[-1][0])
        buckets.setdefault(name, []).append(lap)

    bands_out: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for name, _, _ in band_defs:
        laps = buckets.get(name)
        if not laps:
            continue
        total_s = sum(float(l["duration_s"]) for l in laps)
        if total_s < 180.0:
            continue
        spd = _weighted_median([(float(l["speed_ms"]), float(l["duration_s"])) for l in laps])
        dyn = _weighted_dynamics(laps)
        if not spd or not has_running_dynamics(dyn):
            continue
        row = {
            "band": name,
            "minutes": round(total_s / 60.0),
            "pace_s": round(1000.0 / spd, 1),
            "speed_ms": round(spd, 3),
            "cadence": dyn.get("cadence") if dyn else None,
            "stride_m": dyn.get("stride_m") if dyn else None,
            "gct_ms": dyn.get("gct_ms") if dyn else None,
            "vert_osc_cm": dyn.get("vert_osc_cm") if dyn else None,
            "vert_ratio_pct": dyn.get("vert_ratio_pct") if dyn else None,
        }
        bands_out.append(row)
        by_name[name] = row

    if not bands_out:
        return None

    speed_mod = None
    easy = by_name.get("Easy")
    fast = by_name.get("Threshold") or by_name.get("Fast / 5K+") or by_name.get("Steady / MP")
    if (
        easy
        and fast
        and fast["band"] != easy["band"]
        and easy.get("cadence")
        and fast.get("cadence")
        and easy.get("stride_m")
        and fast.get("stride_m")
    ):
        v_e = easy["cadence"] / 60.0 * easy["stride_m"]
        v_f = fast["cadence"] / 60.0 * fast["stride_m"]
        if v_e > 0 and v_f / v_e >= 1.05:
            dv = math.log(v_f / v_e)
            dc = math.log(fast["cadence"] / easy["cadence"])
            ds = math.log(fast["stride_m"] / easy["stride_m"])
            speed_mod = {
                "from_band": easy["band"],
                "to_band": fast["band"],
                "speed_gain_pct": round((v_f / v_e - 1.0) * 100.0, 1),
                "cadence_from": easy["cadence"],
                "cadence_to": fast["cadence"],
                "cadence_share_pct": round(dc / dv * 100.0),
                "stride_from_m": easy["stride_m"],
                "stride_to_m": fast["stride_m"],
                "stride_share_pct": round(ds / dv * 100.0),
            }

    return {"bands": bands_out, "speed_modulation": speed_mod}


def late_fade_summary(
    records: list[dict], since_date: Optional[date] = None, max_flagged: int = 5
) -> Optional[dict[str, Any]]:
    """Rolls up late-run mechanical drift across runs with `late_drift`."""
    since_iso = since_date.isoformat() if since_date else ""
    checked: list[tuple[dict, dict]] = []
    for r in records:
        if not _is_run_record(r):
            continue
        if since_iso and (r.get("date") or "") < since_iso:
            continue
        ld = r.get("late_drift")
        if isinstance(ld, dict) and any(ld.get(k) is not None for k in ("gct_delta_ms", "vr_delta_pp", "stride_delta_pct")):
            checked.append((r, ld))
    if not checked:
        return None
    gcts = [ld["gct_delta_ms"] for _, ld in checked if ld.get("gct_delta_ms") is not None]
    vrs = [ld["vr_delta_pp"] for _, ld in checked if ld.get("vr_delta_pp") is not None]
    flagged = [
        {
            "date": r.get("date"),
            "title": r.get("title") or "",
            "scope": ld.get("scope") or "session",
            "gct_delta_ms": ld.get("gct_delta_ms"),
            "vr_delta_pp": ld.get("vr_delta_pp"),
            "cadence_delta": ld.get("cadence_delta"),
            "stride_delta_pct": ld.get("stride_delta_pct"),
            "speed_delta_pct": ld.get("speed_delta_pct"),
        }
        for r, ld in sorted(checked, key=lambda x: str(x[0].get("date") or ""), reverse=True)
        if ld.get("fatigue_flag")
    ]
    return {
        "checked": len(checked),
        "faded": len(flagged),
        "median_gct_delta_ms": round(median(gcts), 1) if gcts else None,
        "median_vr_delta_pp": round(median(vrs), 2) if vrs else None,
        "flagged_runs": flagged[:max_flagged],
    }


# ------------------------------------------------------------------------------
# Compact factual text formatters (facts only, no coded verdict emojis)
# ------------------------------------------------------------------------------

def format_dynamics_line(dyn: Optional[dict]) -> str:
    if not has_running_dynamics(dyn):
        return ""
    parts = []
    if dyn.get("cadence") is not None:
        parts.append(f"Cadence {dyn['cadence']:.0f} spm")
    if dyn.get("stride_m") is not None:
        parts.append(f"Stride {dyn['stride_m']:.2f} m")
    if dyn.get("gct_ms") is not None:
        parts.append(f"GCT {dyn['gct_ms']:.0f} ms")
    if dyn.get("vert_osc_cm") is not None:
        parts.append(f"Vert Osc {dyn['vert_osc_cm']:.1f} cm")
    if dyn.get("vert_ratio_pct") is not None:
        parts.append(f"Vert Ratio {dyn['vert_ratio_pct']:.1f}%")
    if dyn.get("gct_balance") is not None:
        parts.append(f"Balance {dyn['gct_balance']:.1f}% L")
    return " · ".join(parts)


def format_late_drift_line(drift: Optional[dict]) -> str:
    if not isinstance(drift, dict):
        return ""
    bits = []
    if drift.get("gct_delta_ms") is not None:
        bits.append(f"GCT {drift['gct_delta_ms']:+.0f} ms")
    if drift.get("vr_delta_pp") is not None:
        bits.append(f"Vert Ratio {drift['vr_delta_pp']:+.2f} pp")
    if drift.get("cadence_delta") is not None:
        bits.append(f"Cadence {drift['cadence_delta']:+.0f} spm")
    if drift.get("stride_delta_pct") is not None:
        bits.append(f"Stride {drift['stride_delta_pct']:+.1f}%")
    if not bits:
        return ""
    spd = f", speed {drift['speed_delta_pct']:+.1f}%" if drift.get("speed_delta_pct") is not None else ""
    tag = " [late-run mechanical fatigue signal]" if drift.get("fatigue_flag") else " [form held]"
    return f"Late-run drift ({drift.get('scope') or 'session'}{spd}): " + ", ".join(bits) + tag


def format_pace_band_table(band_info: Optional[dict]) -> str:
    if not band_info or not band_info.get("bands"):
        return ""
    lines = [
        "**Running mechanics by pace band** (last 6 weeks, running-only laps):",
        "",
        "| Band | Min | Median pace | Cadence | Stride | GCT | Vert Osc | Vert Ratio |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for b in band_info["bands"]:
        cad = f"{b['cadence']:.0f} spm" if b.get("cadence") is not None else "-"
        sl = f"{b['stride_m']:.2f} m" if b.get("stride_m") is not None else "-"
        gct = f"{b['gct_ms']:.0f} ms" if b.get("gct_ms") is not None else "-"
        vo = f"{b['vert_osc_cm']:.1f} cm" if b.get("vert_osc_cm") is not None else "-"
        vr = f"{b['vert_ratio_pct']:.1f}%" if b.get("vert_ratio_pct") is not None else "-"
        lines.append(f"| {b['band']} | {b['minutes']} | {fmt_pace(b['pace_s'])} | {cad} | {sl} | {gct} | {vo} | {vr} |")
    sm = band_info.get("speed_modulation")
    if sm:
        lines.append("")
        lines.append(
            f"- Speed modulation ({sm['from_band']} -> {sm['to_band']}, +{sm['speed_gain_pct']:.1f}% speed): "
            f"{sm['cadence_share_pct']}% from cadence ({sm['cadence_from']:.0f}->{sm['cadence_to']:.0f} spm), "
            f"{sm['stride_share_pct']}% from stride length ({sm['stride_from_m']:.2f}->{sm['stride_to_m']:.2f} m)"
        )
    return "\n".join(lines)


def format_ref_pace(pace_s: Optional[float]) -> str:
    return f"{fmt_clock(pace_s)}/km" if pace_s else ""
