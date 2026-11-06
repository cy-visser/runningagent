"""Structured workout step flattening, device-lap alignment and windowed Pa:Hr/Pw:Hr decoupling."""

from dataclasses import dataclass, field
from typing import Any, Optional

from .athlete_settings import sport_family
from .units import as_float, fmt_clock, to_km

# Every session: skip the first 5 minutes (time HR needs to settle).
PA_HR_SKIP_S = 300
# No decoupling value for windows shorter than this (too noisy).
MIN_DECOUPLING_WINDOW_S = 20 * 60
# Time-series points slower than this are stops/walks and are excluded (km/h).
MIN_RUN_SPEED_KPH = 3.0

# Lap <-> step matching tolerances.
TIME_TOL_ABS_S, TIME_TOL_REL = 10.0, 0.10
DIST_TOL_ABS_M, DIST_TOL_REL = 50.0, 0.05

_TIME_UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
_DIST_UNITS = {"meter": 1.0, "kilometer": 1000.0, "mile": 1609.344}
WARMUP_INTENSITY, COOLDOWN_INTENSITY = "warmup", "cooldown"


@dataclass
class PlannedStep:
    block: int                 # 1-based top-level block index
    block_reps: int            # repetitions of the block
    rep: int                   # 1-based repetition index
    pos: int                   # position within one repetition
    name: str
    intensity: str             # lower-cased intensityClass
    length_s: Optional[float] = None
    length_m: Optional[float] = None
    target_lo: Optional[float] = None
    target_hi: Optional[float] = None
    open_duration: bool = False


@dataclass
class ExecutedStep:
    step: PlannedStep
    laps: list[dict]
    start: float
    end: float
    dur_s: float
    dist_km: Optional[float]
    pace_s: Optional[float]
    hr_avg: Optional[float]
    hr_max: Optional[float]
    power: Optional[float]
    cadence: Optional[float]


@dataclass
class Alignment:
    steps: list[ExecutedStep]
    extra_laps: list[dict] = field(default_factory=list)


def has_structure(structured_workout: Any) -> bool:
    return isinstance(structured_workout, dict) and bool(structured_workout.get("structure"))


def flatten_structure(structured_workout: Any) -> list[PlannedStep]:
    """Expands TP builder blocks (step / repetition) into ordered planned steps."""
    if not has_structure(structured_workout):
        return []
    steps: list[PlannedStep] = []
    for b_idx, block in enumerate(structured_workout["structure"], start=1):
        if not isinstance(block, dict):
            continue
        length = block.get("length") or {}
        reps = int(as_float(length.get("value")) or 1) if length.get("unit") == "repetition" else 1
        inner = [s for s in (block.get("steps") or []) if isinstance(s, dict)]
        for rep in range(1, max(reps, 1) + 1):
            for pos, raw in enumerate(inner):
                steps.append(_planned_step(raw, b_idx, reps, rep, pos))
    return steps


def _planned_step(raw: dict, block: int, reps: int, rep: int, pos: int) -> PlannedStep:
    length = raw.get("length") or {}
    unit = str(length.get("unit") or "").lower()
    value = as_float(length.get("value"))
    targets = raw.get("targets") or [{}]
    target = targets[0] if isinstance(targets[0], dict) else {}
    return PlannedStep(
        block=block, block_reps=reps, rep=rep, pos=pos,
        name=str(raw.get("name") or raw.get("intensityClass") or "Step"),
        intensity=str(raw.get("intensityClass") or "").lower(),
        length_s=value * _TIME_UNITS[unit] if value is not None and unit in _TIME_UNITS else None,
        length_m=value * _DIST_UNITS[unit] if value is not None and unit in _DIST_UNITS else None,
        target_lo=as_float(target.get("minValue")),
        target_hi=as_float(target.get("maxValue")),
        open_duration=bool(raw.get("openDuration")),
    )


def lap_time(lap: dict) -> float:
    return as_float(lap.get("TotalTimerTime")) or as_float(lap.get("TotalElapsedTime")) or 0.0


def lap_km(lap: dict) -> float:
    return to_km(lap.get("TotalDistance")) or 0.0


def _lap_start(lap: dict) -> float:
    return as_float(lap.get("startOffsetSeconds")) or 0.0


def _lap_stop(lap: dict) -> float:
    stop = as_float(lap.get("stopOffsetSeconds"))
    if stop is not None:
        return stop
    return _lap_start(lap) + (as_float(lap.get("TotalElapsedTime")) or lap_time(lap))


def _within(actual: float, target: float, tol_abs: float, tol_rel: float) -> int:
    """-1 = still short, 0 = match, 1 = overshot."""
    tol = max(tol_abs, tol_rel * target)
    if actual < target - tol:
        return -1
    return 0 if actual <= target + tol else 1


def _weighted(laps: list[dict], key: str) -> Optional[float]:
    pairs = [(as_float(l.get(key)), lap_time(l)) for l in laps]
    pairs = [(v, w) for v, w in pairs if v is not None and v > 0 and w > 0]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def _executed(step: PlannedStep, laps: list[dict]) -> ExecutedStep:
    dur = sum(lap_time(l) for l in laps)
    km = sum(lap_km(l) for l in laps)
    if len(laps) == 1 and as_float(laps[0].get("AveragePace")):
        pace = as_float(laps[0].get("AveragePace"))
    else:
        pace = dur / km if km > 0.01 else None
    maxes = [as_float(l.get("MaximumHeartRate")) for l in laps]
    maxes = [m for m in maxes if m]
    return ExecutedStep(
        step=step, laps=laps, start=_lap_start(laps[0]), end=_lap_stop(laps[-1]),
        dur_s=dur, dist_km=km or None, pace_s=pace,
        hr_avg=_weighted(laps, "AverageHeartRate"), hr_max=max(maxes) if maxes else None,
        power=_weighted(laps, "AveragePower"), cadence=_weighted(laps, "AverageCadence"),
    )


def align_laps(steps: list[PlannedStep], laps: list[dict]) -> Optional[Alignment]:
    """Maps consecutive device laps onto planned steps; None when they don't line up."""
    laps = [l for l in (laps or []) if isinstance(l, dict)]
    if not steps or not laps:
        return None
    executed: list[ExecutedStep] = []
    i = 0
    for step in steps:
        taken: list[dict] = []
        while True:
            if i >= len(laps):
                return None
            taken.append(laps[i])
            i += 1
            if step.open_duration:
                break
            if step.length_m is not None:
                state = _within(sum(lap_km(l) for l in taken) * 1000, step.length_m, DIST_TOL_ABS_M, DIST_TOL_REL)
            elif step.length_s is not None:
                state = _within(sum(lap_time(l) for l in taken), step.length_s, TIME_TOL_ABS_S, TIME_TOL_REL)
            else:
                state = 0
            if state == 0:
                break
            if state > 0:
                return None
        executed.append(_executed(step, taken))
    return Alignment(steps=executed, extra_laps=laps[i:])


def series_end(series: Optional[list[dict]], laps: Optional[list[dict]] = None) -> Optional[float]:
    ends = []
    if series:
        ends.append(max(as_float(p.get("time")) or 0.0 for p in series))
    if laps:
        ends.append(max(_lap_stop(l) for l in laps if isinstance(l, dict)))
    return max(ends) if ends else None


def pa_hr_window(
    session_end: Optional[float], alignment: Optional[Alignment] = None
) -> Optional[tuple[float, float]]:
    """(t0, t1) for session decoupling: skip the first PA_HR_SKIP_S and, when the
    structure is aligned, the warm-up / cool-down steps. None if the window is too short."""
    if not session_end:
        return None
    t0, t1 = float(PA_HR_SKIP_S), float(session_end)
    if alignment:
        warm = [e for e in alignment.steps if e.step.intensity == WARMUP_INTENSITY]
        cool = [e for e in alignment.steps if e.step.intensity == COOLDOWN_INTENSITY]
        leading = []
        for e in alignment.steps:
            if e.step.intensity != WARMUP_INTENSITY:
                break
            leading.append(e)
        trailing = []
        for e in reversed(alignment.steps):
            if e.step.intensity != COOLDOWN_INTENSITY:
                break
            trailing.append(e)
        if warm and leading:
            t0 = max(t0, leading[-1].end)
        if cool and trailing:
            t1 = min(t1, trailing[-1].start)
    return (t0, t1) if t1 - t0 >= MIN_DECOUPLING_WINDOW_S else None


def decoupling(
    series: Optional[list[dict]], t0: float, t1: float, sport: Optional[str]
) -> Optional[float]:
    """Friel decoupling in %: EF (speed/HR, or power/HR for bike) first half vs second half."""
    if not series or t1 <= t0:
        return None
    key = "Power" if sport_family(sport) == "bike" else "Speed"
    pts = []
    for p in series:
        t, hr, v = as_float(p.get("time")), as_float(p.get("HeartRate")), as_float(p.get(key))
        if t is None or not hr or not v or v <= 0 or not (t0 <= t < t1):
            continue
        if key == "Speed" and v < MIN_RUN_SPEED_KPH:
            continue
        pts.append((t, hr, v))
    mid = (t0 + t1) / 2
    halves = ([p for p in pts if p[0] < mid], [p for p in pts if p[0] >= mid])
    if any(len(h) < 10 for h in halves):
        return None
    ef = [(sum(v for _, _, v in h) / len(h)) / (sum(hr for _, hr, _ in h) / len(h)) for h in halves]
    return round((ef[0] - ef[1]) / ef[0] * 100.0, 1)


def lap_decoupling(laps: list[dict], t0: float, t1: float, sport: Optional[str]) -> Optional[float]:
    """Fallback when no time series: the same formula on time-weighted lap averages."""
    inside = [l for l in laps or [] if isinstance(l, dict) and t0 <= (_lap_start(l) + _lap_stop(l)) / 2 < t1]
    mid = (t0 + t1) / 2
    halves = ([l for l in inside if (_lap_start(l) + _lap_stop(l)) / 2 < mid],
              [l for l in inside if (_lap_start(l) + _lap_stop(l)) / 2 >= mid])
    if not all(halves):
        return None
    efs = []
    for h in halves:
        hr = _weighted(h, "AverageHeartRate")
        if sport_family(sport) == "bike":
            out = _weighted(h, "AveragePower")
        else:
            dur, km = sum(lap_time(l) for l in h), sum(lap_km(l) for l in h)
            out = km / dur if dur > 0 and km > 0 else None
        if not hr or not out:
            return None
        efs.append(out / hr)
    return round((efs[0] - efs[1]) / efs[0] * 100.0, 1)


def windowed_decoupling(
    series: Optional[list[dict]], laps: Optional[list[dict]], t0: float, t1: float, sport: Optional[str]
) -> tuple[Optional[float], str]:
    """(value, source) using the time series, else laps."""
    value = decoupling(series, t0, t1, sport)
    if value is not None:
        return value, "series"
    value = lap_decoupling(laps or [], t0, t1, sport)
    return value, ("laps" if value is not None else "")


def decoupling_label(sport: Optional[str], t0: float, t1: float, source: str = "series") -> str:
    name = "Pw:Hr" if sport_family(sport) == "bike" else "Pa:Hr"
    via = ", from laps" if source == "laps" else ""
    return f"{name} ({fmt_clock(t0)} → {fmt_clock(t1)}, {round((t1 - t0) / 60)} min{via})"


def session_decoupling(
    series: Optional[list[dict]], laps: Optional[list[dict]], sport: Optional[str],
    alignment: Optional[Alignment] = None,
) -> Optional[str]:
    """'Pa:Hr (15:42 → 1:01:41, 46 min): 6.5%' or '' when not computable; None when no data at all."""
    if not series and not laps:
        return None
    window = pa_hr_window(series_end(series, laps), alignment)
    if not window:
        return ""
    value, source = windowed_decoupling(series, laps, *window, sport)
    if value is None:
        return ""
    return f"{decoupling_label(sport, *window, source)}: {value}%"
