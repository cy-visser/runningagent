"""Structure-aware workout analysis: planned (TrainingPeaks workout builder) vs executed.

Pure functions only (no I/O):
- flatten the TP `structured_workout` into ordered planned steps,
- convert %-of-threshold targets into real units (pace / bpm / watts),
- align device laps to planned steps (one or more laps per step),
- compute windowed aerobic decoupling (Pa:Hr / Pw:Hr) from the time series,
  skipping the first minutes of every session and, for structured sessions,
  the warm-up and cool-down steps.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from .classification import BIKE_SPORTS
from .metrics import as_float, coerce_mcp_payload, to_km

# Every session: skip the first 5 minutes (time HR needs to settle).
PA_HR_SKIP_S = 300
# No decoupling value for windows shorter than this (too noisy).
MIN_DECOUPLING_WINDOW_S = 20 * 60
# Per-block decoupling is reported for work blocks at least this long.
MIN_BLOCK_S = 8 * 60
# Time-series points slower than this are stops/walks and are excluded (km/h).
MIN_RUN_SPEED_KPH = 3.0

# Lap <-> step matching tolerances.
TIME_TOL_ABS_S, TIME_TOL_REL = 10.0, 0.10
DIST_TOL_ABS_M, DIST_TOL_REL = 50.0, 0.05

_TIME_UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
_DIST_UNITS = {"meter": 1.0, "kilometer": 1000.0, "mile": 1609.344}
_WARMUP, _COOLDOWN = "warmup", "cooldown"

# TP zone groups: workoutTypeId 3 = run, 2 = bike, 0 = default.
_TYPE_IDS = {"run": (3, 0), "bike": (2, 0)}


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


# ------------------------------------------------------------------ helpers
def sport_family(sport: Optional[str]) -> str:
    return "bike" if (sport or "").strip().lower() in BIKE_SPORTS else "run"


def fmt_clock(seconds: Optional[float]) -> str:
    """Seconds -> 'M:SS' or 'H:MM:SS'."""
    if seconds is None:
        return "-"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace(pace_s: Optional[float]) -> str:
    return f"{fmt_clock(pace_s)}/km" if pace_s else "-"


def _fmt_length(step: PlannedStep) -> str:
    if step.open_duration:
        return "open (lap button)"
    if step.length_m is not None:
        return f"{step.length_m / 1000:.2f} km" if step.length_m >= 1000 else f"{int(step.length_m)} m"
    if step.length_s is not None:
        return f"{int(step.length_s)}s" if step.length_s < 60 else fmt_clock(step.length_s)
    return "-"


# ------------------------------------------------------------------ structure
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


# ------------------------------------------------------------------ thresholds & targets
def sport_thresholds(settings_raw: Any, sport: Optional[str]) -> dict[str, Optional[float]]:
    """Threshold speed (m/s), LTHR (bpm) and FTP (W) from tp_get_athlete_settings for the sport."""
    payload = coerce_mcp_payload(settings_raw) if settings_raw else {}
    settings = payload.get("settings", payload) if isinstance(payload, dict) else {}
    type_ids = _TYPE_IDS[sport_family(sport)]

    def pick(groups: Any) -> Optional[float]:
        if not isinstance(groups, list):
            return None
        by_type = {g.get("workoutTypeId"): g for g in groups if isinstance(g, dict)}
        for type_id in type_ids:
            value = as_float((by_type.get(type_id) or {}).get("threshold"))
            if value and value > 0:
                return value
        return None

    return {
        "threshold_speed": pick(settings.get("speedZones")),
        "lthr": pick(settings.get("heartRateZones")),
        "ftp": pick(settings.get("powerZones")),
    }


def target_range(step: PlannedStep, metric: Optional[str], thr: dict) -> Optional[tuple[str, float, float]]:
    """(kind, low, high) in real units: kind 'pace' (s/km, low=fast), 'hr' (bpm) or 'power' (W)."""
    lo, hi = step.target_lo, step.target_hi
    if lo is None or hi is None:
        return None
    metric = metric or ""
    if metric == "percentOfThresholdPace" and thr.get("threshold_speed"):
        thr_pace = 1000.0 / thr["threshold_speed"]
        return ("pace", round(thr_pace / (hi / 100.0)), round(thr_pace / (lo / 100.0)))
    if metric == "percentOfThresholdHr" and thr.get("lthr"):
        return ("hr", round(thr["lthr"] * lo / 100.0), round(thr["lthr"] * hi / 100.0))
    if metric == "percentOfFtp" and thr.get("ftp"):
        return ("power", round(thr["ftp"] * lo / 100.0), round(thr["ftp"] * hi / 100.0))
    return None


def format_target(step: PlannedStep, metric: Optional[str], thr: dict) -> str:
    rng = target_range(step, metric, thr)
    if rng:
        kind, lo, hi = rng
        if kind == "pace":
            return f"{fmt_clock(lo)}–{fmt_pace(hi)}"
        return f"{int(lo)}–{int(hi)} {'bpm' if kind == 'hr' else 'W'}"
    if step.target_lo is None:
        return "no target"
    label = {"percentOfThresholdPace": "% thr pace", "percentOfThresholdHr": "% LTHR",
             "percentOfFtp": "% FTP"}.get(metric or "", f"% ({metric})")
    return f"{step.target_lo:g}–{step.target_hi:g}{label}"


def target_check(ex: ExecutedStep, metric: Optional[str], thr: dict) -> str:
    """'✓', 'fast (-10s/km)', 'slow (+5s/km)', 'high (+4 bpm)', ... or '' when unknown."""
    rng = target_range(ex.step, metric, thr)
    if not rng:
        return ""
    kind, lo, hi = rng
    if kind == "pace":
        if ex.pace_s is None:
            return ""
        if ex.pace_s < lo - 0.5:
            return f"fast (-{round(lo - ex.pace_s)}s/km)"
        if ex.pace_s > hi + 0.5:
            return f"slow (+{round(ex.pace_s - hi)}s/km)"
        return "✓"
    actual, unit = (ex.hr_avg, "bpm") if kind == "hr" else (ex.power, "W")
    if actual is None:
        return ""
    if actual < lo:
        return f"low (-{round(lo - actual)} {unit})"
    if actual > hi:
        return f"high (+{round(actual - hi)} {unit})"
    return "✓"


# ------------------------------------------------------------------ lap alignment
def _lap_time(lap: dict) -> float:
    return as_float(lap.get("TotalTimerTime")) or as_float(lap.get("TotalElapsedTime")) or 0.0


def _lap_km(lap: dict) -> float:
    return to_km(lap.get("TotalDistance")) or 0.0


def _lap_start(lap: dict) -> float:
    return as_float(lap.get("startOffsetSeconds")) or 0.0


def _lap_stop(lap: dict) -> float:
    stop = as_float(lap.get("stopOffsetSeconds"))
    if stop is not None:
        return stop
    return _lap_start(lap) + (as_float(lap.get("TotalElapsedTime")) or _lap_time(lap))


def _within(actual: float, target: float, tol_abs: float, tol_rel: float) -> int:
    """-1 = still short, 0 = match, 1 = overshot."""
    tol = max(tol_abs, tol_rel * target)
    if actual < target - tol:
        return -1
    return 0 if actual <= target + tol else 1


def _weighted(laps: list[dict], key: str) -> Optional[float]:
    pairs = [(as_float(l.get(key)), _lap_time(l)) for l in laps]
    pairs = [(v, w) for v, w in pairs if v is not None and v > 0 and w > 0]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def _executed(step: PlannedStep, laps: list[dict]) -> ExecutedStep:
    dur = sum(_lap_time(l) for l in laps)
    km = sum(_lap_km(l) for l in laps)
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
                state = _within(sum(_lap_km(l) for l in taken) * 1000, step.length_m, DIST_TOL_ABS_M, DIST_TOL_REL)
            elif step.length_s is not None:
                state = _within(sum(_lap_time(l) for l in taken), step.length_s, TIME_TOL_ABS_S, TIME_TOL_REL)
            else:
                state = 0
            if state == 0:
                break
            if state > 0:
                return None
        executed.append(_executed(step, taken))
    return Alignment(steps=executed, extra_laps=laps[i:])


# ------------------------------------------------------------------ decoupling
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
        warm = [e for e in alignment.steps if e.step.intensity == _WARMUP]
        cool = [e for e in alignment.steps if e.step.intensity == _COOLDOWN]
        leading = []
        for e in alignment.steps:
            if e.step.intensity != _WARMUP:
                break
            leading.append(e)
        trailing = []
        for e in reversed(alignment.steps):
            if e.step.intensity != _COOLDOWN:
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
            dur, km = sum(_lap_time(l) for l in h), sum(_lap_km(l) for l in h)
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


# ------------------------------------------------------------------ formatting
def _block_intensity(steps: list[ExecutedStep]) -> float:
    pairs = [((e.step.target_lo + e.step.target_hi) / 2, e.dur_s) for e in steps
             if e.step.target_lo is not None and e.step.target_hi is not None and e.dur_s > 0]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else 0.0


def _step_label(step: PlannedStep) -> str:
    if step.block_reps > 1:
        return f"B{step.block} {step.name} {step.rep}/{step.block_reps}"
    return f"B{step.block} {step.name}"


def format_planned_structure(steps: list[PlannedStep], metric: Optional[str], thr: dict) -> str:
    """Plan-only view (laps could not be aligned)."""
    lines, seen = [], set()
    for s in steps:
        if (s.block, s.pos) in seen:
            continue
        seen.add((s.block, s.pos))
        reps = f"{s.block_reps}× " if s.block_reps > 1 else ""
        lines.append(f"- B{s.block}: {reps}{s.name} {_fmt_length(s)} @ {format_target(s, metric, thr)}")
    return "\n".join(lines)


def format_structured_execution(
    structured_workout: dict,
    laps: Optional[list[dict]],
    thr: dict,
    series: Optional[list[dict]],
    sport: Optional[str],
    alignment: Optional[Alignment] = None,
) -> str:
    """Planned-vs-executed section for a TP structured workout."""
    metric = structured_workout.get("primaryIntensityMetric")
    steps = flatten_structure(structured_workout)
    if not steps:
        return ""
    is_bike = sport_family(sport) == "bike"
    thr_bits = []
    if thr.get("threshold_speed") and not is_bike:
        thr_bits.append(f"threshold pace {fmt_pace(1000 / thr['threshold_speed'])}")
    if thr.get("lthr"):
        thr_bits.append(f"LTHR {int(thr['lthr'])} bpm")
    if thr.get("ftp") and is_bike:
        thr_bits.append(f"FTP {int(thr['ftp'])} W")
    header = "### Planned structure & execution" + (f" ({', '.join(thr_bits)})" if thr_bits else "")

    if alignment is None:
        alignment = align_laps(steps, laps or [])
    if alignment is None:
        return (f"{header}\nDevice laps do not line up with the planned steps; planned structure:\n"
                f"{format_planned_structure(steps, metric, thr)}")

    actual_col = "Power" if is_bike else "Pace"
    lines = [header, f"| Step | Planned | Target | {actual_col} | HR avg/max | Cad | Check |",
             "|---|---|---|---|---|---|---|"]
    for e in alignment.steps:
        actual = f"{round(e.power)} W" if is_bike and e.power else fmt_pace(e.pace_s)
        hr = f"{round(e.hr_avg)}/{round(e.hr_max)}" if e.hr_avg and e.hr_max else (f"{round(e.hr_avg)}" if e.hr_avg else "-")
        cad = f"{round(e.cadence)}" if e.cadence else "-"
        lines.append(f"| {_step_label(e.step)} | {_fmt_length(e.step)} | {format_target(e.step, metric, thr)} "
                     f"| {actual} | {hr} | {cad} | {target_check(e, metric, thr)} |")
    for lap in alignment.extra_laps:
        lines.append(f"Extra lap (not in plan): {lap.get('Name') or 'lap'} {fmt_clock(_lap_time(lap))}, {_lap_km(lap):.2f} km")

    # Repeated blocks: rep-to-rep consistency and HR drift.
    blocks: dict[int, list[ExecutedStep]] = {}
    for e in alignment.steps:
        blocks.setdefault(e.step.block, []).append(e)
    rep_lines = []
    for b, execs in blocks.items():
        if execs[0].step.block_reps < 2:
            continue
        positions: dict[int, list[ExecutedStep]] = {}
        for e in execs:
            positions.setdefault(e.step.pos, []).append(e)
        desc = " / ".join(
            f"{p[0].step.name} {_fmt_length(p[0].step)} @ {format_target(p[0].step, metric, thr)}" for p in positions.values()
        )
        rep_lines.append(f"- B{b} {execs[0].step.block_reps}× ({desc}):")
        for p in positions.values():
            parts = []
            if is_bike:
                vals = [e.power for e in p if e.power]
                if vals:
                    parts.append(f"power {', '.join(str(round(v)) for v in vals)} W (spread {round(max(vals) - min(vals))} W)")
            else:
                vals = [e.pace_s for e in p if e.pace_s]
                if vals:
                    parts.append(f"pace {', '.join(fmt_clock(v) for v in vals)} (spread {round(max(vals) - min(vals))}s)")
            hrs = [e.hr_avg for e in p if e.hr_avg]
            if len(hrs) >= 2:
                parts.append(f"HR {' → '.join(str(round(h)) for h in hrs)} ({round(hrs[-1] - hrs[0]):+d} bpm first→last)")
            checks = [target_check(e, metric, thr) for e in p]
            if any(checks):
                parts.append(f"{sum(c == '✓' for c in checks)}/{len(p)} in target")
            rep_lines.append(f"  - {p[0].step.name}: " + " | ".join(parts))
    if rep_lines:
        lines += ["", "**Repeated blocks:**", *rep_lines]

    # Per-block decoupling for work blocks >= MIN_BLOCK_S (the first minutes are always skipped).
    block_rows = []
    for b, execs in blocks.items():
        if all(e.step.intensity in (_WARMUP, _COOLDOWN) for e in execs):
            continue
        t0, t1 = max(execs[0].start, float(PA_HR_SKIP_S)), execs[-1].end
        if t1 - t0 < MIN_BLOCK_S:
            continue
        value, source = windowed_decoupling(series, [l for e in execs for l in e.laps], t0, t1, sport)
        if value is not None:
            block_rows.append((b, execs, t0, t1, value, source))
    if block_rows:
        key_block = max(block_rows, key=lambda r: _block_intensity(r[1]))[0] if len(block_rows) > 1 else None
        lines += ["", "**Decoupling per work block** (EF first vs second half):"]
        for b, execs, t0, t1, value, source in block_rows:
            reps = f"{execs[0].step.block_reps}× " if execs[0].step.block_reps > 1 else ""
            names = "/".join(dict.fromkeys(e.step.name for e in execs))
            key = " [key block]" if b == key_block else ""
            lines.append(f"- B{b} {reps}{names}: {decoupling_label(sport, t0, t1, source)}: {value}%{key}")
    return "\n".join(lines)
