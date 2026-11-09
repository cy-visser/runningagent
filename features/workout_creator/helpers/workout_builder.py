"""TrainingPeaks workout builder: coach structure -> native builder, totals and summary.

The coach always writes the builder with exact numbers (rep count, rep length, recovery, targets);
nothing here scales or invents steps. Lengths are written exactly as given. Run pace targets are
converted to % of threshold pace (one decimal), the unit TrainingPeaks stores. Totals follow the
TrainingPeaks builder convention: a timed step is converted to metres at the slow end of its range
(minValue % x threshold speed), rounded per step, and block begin/end are cumulative lengths.
"""

import json
from typing import Any, Optional

from ....shared.athlete_settings import sport_family
from ....shared.sports import BIKE_SPORTS, RUN_SPORTS
from ....shared.units import as_float, fmt_clock

PACE, HR, FTP = "percentOfThresholdPace", "percentOfThresholdHr", "percentOfFtp"
METRICS = (PACE, HR, FTP)
INTENSITY_CLASSES = ("warmUp", "active", "rest", "coolDown", "other")
MAX_REPS = 100
MAX_DISTANCE_M = 100_000
MAX_DURATION_S = 86_400
# Chart geometry only, for steps no threshold pace can convert (~6:00/km).
NOMINAL_SPEED_MPS = 2.78

_TIME_UNITS = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
_DIST_UNITS = {"meter": 1.0, "kilometer": 1000.0, "mile": 1609.344}
_DEFAULT_NAMES = {"warmUp": "Warm up", "active": "Active", "rest": "Recovery", "coolDown": "Cool down",
                  "other": "Other"}


def needs_builder(sport: Optional[str]) -> bool:
    """Run and bike workouts always carry a TrainingPeaks builder."""
    s = (sport or "Run").strip().lower()
    return s in RUN_SPORTS or s in BIKE_SPORTS


def _exact(value: float) -> float | int:
    """Whole numbers as int (as TrainingPeaks stores them), otherwise one decimal."""
    return int(value) if float(value).is_integer() else round(value, 1)


# ------------------------------------------------------------------------------
# Pace <-> % of threshold pace
# ------------------------------------------------------------------------------

def _pace_seconds(text: str) -> Optional[float]:
    """'4:30' (min:sec per km) -> 270.0; None when not a pace."""
    parts = text.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        minutes, seconds = int(parts[0]), float(parts[1])
    except ValueError:
        return None
    total = minutes * 60 + seconds
    return total if 0 <= seconds < 60 and 90 <= total <= 1200 else None


def pace_to_percent(pace: str, threshold_speed: float) -> tuple[int, int]:
    """'4:25-4:35' or '4:30' -> (min %, max %) of threshold pace, whole %; the faster pace is the higher %.

    Raises ValueError on an unreadable pace.
    """
    text = str(pace).lower().replace("/km", "").replace("–", "-").replace("—", "-").replace(" ", "")
    bounds = [_pace_seconds(p) for p in text.split("-")]
    if not 1 <= len(bounds) <= 2 or any(b is None for b in bounds):
        raise ValueError(f"unreadable pace '{pace}' (use 'm:ss' or 'm:ss-m:ss' per km)")
    threshold_pace = 1000.0 / threshold_speed
    pcts = sorted(round(threshold_pace / b * 100.0) for b in bounds)
    return pcts[0], pcts[-1]


def _percent_to_pace(pct: float, threshold_speed: float) -> float:
    return 1000.0 / (threshold_speed * pct / 100.0)


# ------------------------------------------------------------------------------
# Coach structure -> native TrainingPeaks builder
# ------------------------------------------------------------------------------

def _wire_step(raw: Any, metric: str, thr: dict, where: str) -> tuple[Optional[dict], Optional[str]]:
    if not isinstance(raw, dict):
        return None, f"{where} must be an object"
    if raw.get("type") == "repetition":
        return None, f"{where}: repetitions cannot be nested"
    cls = str(raw.get("intensityClass") or "active").strip()
    if cls not in INTENSITY_CLASSES:
        return None, f"{where}: intensityClass must be one of {', '.join(INTENSITY_CLASSES)}"

    has_distance = raw.get("distance_m") not in (None, "")
    has_duration = raw.get("duration_seconds") not in (None, "")
    if has_distance == has_duration:
        return None, f"{where}: give exactly one of distance_m or duration_seconds"
    value = as_float(raw.get("distance_m") if has_distance else raw.get("duration_seconds"))
    limit = MAX_DISTANCE_M if has_distance else MAX_DURATION_S
    if value is None or not 0 < value <= limit:
        return None, f"{where}: {'distance_m' if has_distance else 'duration_seconds'} must be > 0 and <= {limit}"
    length = {"value": _exact(value), "unit": "meter" if has_distance else "second"}

    lo, hi = as_float(raw.get("intensity_min")), as_float(raw.get("intensity_max"))
    if lo is not None and hi is not None:
        pass  # exact stored % values win over a pace hint
    elif raw.get("pace") not in (None, ""):
        if metric != PACE:
            return None, f"{where}: pace targets need primaryIntensityMetric {PACE}; use intensity_min/intensity_max"
        if not thr.get("threshold_speed"):
            return None, (f"{where}: the runner's threshold pace is not available in TrainingPeaks to convert "
                          "the pace; use intensity_min/intensity_max (% of threshold pace)")
        try:
            lo, hi = pace_to_percent(str(raw["pace"]), thr["threshold_speed"])
        except ValueError as e:
            return None, f"{where}: {e}"
    else:
        return None, f"{where}: needs a target: pace or intensity_min + intensity_max"
    if not (0 <= lo <= 300 and 0 <= hi <= 300) or lo > hi:
        return None, f"{where}: intensity_min/intensity_max must be within 0-300 with min <= max"

    targets: list[dict] = [{"minValue": round(lo), "maxValue": round(hi)}]  # whole % (no 88.9 %)
    targets += [t for t in (raw.get("extra_targets") or []) if isinstance(t, dict)]
    name = str(raw.get("name") or _DEFAULT_NAMES[cls]).strip()[:100] or _DEFAULT_NAMES[cls]
    return {
        "type": "step",
        "name": name,
        "length": length,
        "targets": targets,
        "intensityClass": cls,
        "openDuration": bool(raw.get("open_duration")),
    }, None


def parse_coach_structure(raw: Any, sport: Optional[str], thr: dict) -> tuple[Optional[dict], Optional[str]]:
    """Coach `structure` -> (native builder with exact lengths and targets plus geometry, None) or (None, error)."""
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except ValueError:
            return None, "structure is not valid JSON"
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list) or not data["steps"]:
        return None, "structure needs a non-empty `steps` list"
    is_bike = sport_family(sport) == "bike"
    metric = data.get("primaryIntensityMetric") or (FTP if is_bike else PACE)
    if metric not in METRICS:
        return None, f"primaryIntensityMetric must be one of {', '.join(METRICS)}"
    if is_bike and metric == PACE:
        return None, f"bike builders use {FTP} or {HR}"

    blocks: list[dict] = []
    for i, item in enumerate(data["steps"], start=1):
        if isinstance(item, dict) and item.get("type") == "repetition":
            reps = as_float(item.get("reps"))
            if reps is None or not reps.is_integer() or not 1 <= reps <= MAX_REPS:
                return None, f"steps[{i}]: reps must be a whole number from 1 to {MAX_REPS}"
            inner = item.get("steps")
            if not isinstance(inner, list) or not inner:
                return None, f"steps[{i}]: a repetition needs a non-empty `steps` list"
            wire = []
            for j, s in enumerate(inner, start=1):
                step, err = _wire_step(s, metric, thr, f"steps[{i}].steps[{j}]")
                if err:
                    return None, err
                wire.append(step)
            blocks.append({"type": "repetition", "length": {"value": int(reps), "unit": "repetition"}, "steps": wire})
        else:
            step, err = _wire_step(item, metric, thr, f"steps[{i}]")
            if err:
                return None, err
            blocks.append({"type": "step", "length": {"value": 1, "unit": "repetition"}, "steps": [step]})

    native = {
        "structure": blocks,
        "primaryLengthMetric": "duration" if is_bike else "distance",
        "primaryIntensityMetric": metric,
        "primaryIntensityTargetOrRange": "range",
    }
    return with_geometry(native, thr), None


# ------------------------------------------------------------------------------
# Lengths, geometry and totals
# ------------------------------------------------------------------------------

def _block_reps(block: dict) -> int:
    length = block.get("length") or {}
    if length.get("unit") != "repetition":
        return 1
    return max(int(as_float(length.get("value")) or 1), 1)


def _steps(block: dict) -> list[dict]:
    return [s for s in (block.get("steps") or []) if isinstance(s, dict)]


def _target(step: dict) -> tuple[Optional[float], Optional[float]]:
    targets = step.get("targets") or [{}]
    first = targets[0] if isinstance(targets[0], dict) else {}
    return as_float(first.get("minValue")), as_float(first.get("maxValue"))


def step_lengths(step: dict, metric: Optional[str], thr: dict) -> tuple[Optional[float], Optional[float]]:
    """(seconds, metres) of one native step, converted like the TrainingPeaks builder: at the slow end of
    the range (minValue % x threshold speed), metres rounded per step. None when it cannot be converted."""
    length = step.get("length") or {}
    unit = str(length.get("unit") or "").lower()
    value = as_float(length.get("value"))
    if value is None:
        return None, None
    lo, _ = _target(step)
    speed = thr["threshold_speed"] * lo / 100.0 if metric == PACE and thr.get("threshold_speed") and lo else None
    if unit in _TIME_UNITS:
        seconds = value * _TIME_UNITS[unit]
        return seconds, (round(seconds * speed) if speed else None)
    if unit in _DIST_UNITS:
        metres = value * _DIST_UNITS[unit]
        return (metres / speed if speed else None), metres
    return None, None


def _geometry_length(step: dict, metric: Optional[str], thr: dict, by_distance: bool) -> float:
    seconds, metres = step_lengths(step, metric, thr)
    if by_distance:
        return metres if metres is not None else (seconds or 0.0) * NOMINAL_SPEED_MPS
    return seconds if seconds is not None else (metres or 0.0) / NOMINAL_SPEED_MPS


def with_geometry(native: dict, thr: dict) -> dict:
    """Fills block begin/end (cumulative metres for 'distance', seconds for 'duration'), the chart polyline
    (x = fraction of the total length, y = maxValue / highest maxValue, as TrainingPeaks draws it) and the
    keys the MCP requires."""
    metric = native.get("primaryIntensityMetric")
    native.setdefault("primaryLengthMetric", "distance")
    native.setdefault("primaryIntensityTargetOrRange", "range")
    by_distance = native["primaryLengthMetric"] == "distance"
    if by_distance:
        native.setdefault("visualizationDistanceUnit", "kilometer")

    bars: list[tuple[float, float]] = []  # (length, maxValue) per executed step
    cumulative = 0.0
    for block in native.get("structure") or []:
        lengths = [(_geometry_length(s, metric, thr, by_distance), _target(s)[1] or 0.0) for s in _steps(block)]
        block["begin"] = round(cumulative)
        cumulative += sum(length for length, _ in lengths) * _block_reps(block)
        block["end"] = round(cumulative)
        bars += lengths * _block_reps(block)

    total = sum(length for length, _ in bars)
    peak = max((value for _, value in bars), default=0.0)
    polyline: list[list[float]] = []
    x = 0.0
    for length, value in bars:
        x0, x = x, x + length
        y = round(value / peak, 3) if peak else 0
        x0r, x1r = (round(x0 / total, 3), round(x / total, 3)) if total else (0, 0)
        polyline += [[x0r, 0], [x0r, y], [x1r, y], [x1r, 0]]
    native["polyline"] = polyline
    return native


def builder_totals(native: dict, thr: dict) -> dict[str, Optional[float]]:
    """distance_km / duration_minutes / tss_planned from the builder (None where not derivable).

    IF = (sum(t * mid^4) / sum(t))^(1/4) / 100 and TSS = hours * IF^2 * 100, as tp_mcp's compute_if_tss.
    """
    metric = native.get("primaryIntensityMetric")
    seconds_total, metres_total, weighted = 0.0, 0.0, 0.0
    seconds_ok = metres_ok = intensity_ok = True
    for block in native.get("structure") or []:
        reps = _block_reps(block)
        for step in _steps(block):
            seconds, metres = step_lengths(step, metric, thr)
            lo, hi = _target(step)
            if seconds is None:
                seconds_ok = False
            else:
                seconds_total += seconds * reps
                if lo is None or hi is None:
                    intensity_ok = False
                else:
                    weighted += seconds * reps * ((lo + hi) / 2.0) ** 4
            if metres is None:
                metres_ok = False
            else:
                metres_total += metres * reps
    tss = None
    if seconds_ok and intensity_ok and seconds_total > 0:
        intensity_factor = (weighted / seconds_total) ** 0.25 / 100.0
        tss = round(seconds_total / 3600.0 * intensity_factor ** 2 * 100.0)
    return {
        "distance_km": round(metres_total / 1000.0, 2) if metres_ok and metres_total > 0 else None,
        "duration_minutes": round(seconds_total / 60.0) if seconds_ok and seconds_total > 0 else None,
        "tss_planned": tss,
    }


# ------------------------------------------------------------------------------
# Human-readable summary and the coach view of an existing builder
# ------------------------------------------------------------------------------

def _length_text(step: dict) -> str:
    length = step.get("length") or {}
    unit = str(length.get("unit") or "").lower()
    value = as_float(length.get("value")) or 0.0
    if unit in _DIST_UNITS:
        metres = value * _DIST_UNITS[unit]
        return f"{metres / 1000:g} km" if metres >= 1000 else f"{metres:g} m"
    seconds = value * _TIME_UNITS.get(unit, 1.0)
    if seconds < 60:
        return f'{seconds:g}"'
    return f"{seconds / 60:g}'" if seconds % 60 == 0 else fmt_clock(seconds)


def _target_text(step: dict, metric: Optional[str], thr: dict) -> str:
    lo, hi = _target(step)
    if lo is None or hi is None:
        return ""
    if metric == PACE and thr.get("threshold_speed") and lo > 0:
        fast, slow = (fmt_clock(_percent_to_pace(p, thr["threshold_speed"])) for p in (hi, lo))
        return f"{fast}/km" if fast == slow else f"{fast}–{slow}/km"
    base, unit = {HR: (thr.get("lthr"), "bpm"), FTP: (thr.get("ftp"), "W")}.get(metric or "", (None, ""))
    if base:
        low, high = round(base * lo / 100.0), round(base * hi / 100.0)
        return f"{low} {unit}" if low == high else f"{low}–{high} {unit}"
    return f"{lo:g}–{hi:g}%"


def _step_text(step: dict, metric: Optional[str], thr: dict) -> str:
    cls = step.get("intensityClass")
    length = _length_text(step)
    if cls == "warmUp":
        return f"{length} WU"
    if cls == "coolDown":
        return f"{length} CD"
    target = _target_text(step, metric, thr)
    if cls == "rest":
        return f"{length} rec" + (f" @ {target}" if target and metric != PACE else "")
    return f"{length} @ {target}" if target else length


def builder_summary(native: dict, thr: dict) -> str:
    """"15' WU · 5× (12' @ 4:25–4:35/km / 2' rec) · 10' CD"."""
    metric = native.get("primaryIntensityMetric")
    parts = []
    for block in native.get("structure") or []:
        texts = [_step_text(s, metric, thr) for s in _steps(block)]
        if not texts:
            continue
        reps = _block_reps(block)
        inner = " / ".join(texts)
        parts.append(f"{reps}× ({inner})" if reps > 1 and len(texts) > 1 else (f"{reps}× {inner}" if reps > 1 else inner))
    return " · ".join(parts)


def _coach_step(step: dict, metric: Optional[str], thr: dict) -> dict:
    length = step.get("length") or {}
    unit = str(length.get("unit") or "").lower()
    value = as_float(length.get("value")) or 0.0
    out: dict[str, Any] = {"name": step.get("name"), "intensityClass": step.get("intensityClass") or "active"}
    if unit in _DIST_UNITS:
        out["distance_m"] = _exact(value * _DIST_UNITS[unit])
    else:
        out["duration_seconds"] = _exact(value * _TIME_UNITS.get(unit, 1.0))
    lo, hi = _target(step)
    out["intensity_min"], out["intensity_max"] = lo, hi
    if metric == PACE and thr.get("threshold_speed") and lo:
        out["pace"] = _target_text(step, metric, thr).removesuffix("/km")  # read-only hint
    extra = [t for t in (step.get("targets") or [])[1:] if isinstance(t, dict)]
    if extra:
        out["extra_targets"] = extra
    if step.get("openDuration"):
        out["open_duration"] = True
    return out


def coach_structure_from(native: dict, thr: dict) -> dict:
    """An existing TrainingPeaks builder in the coach's format: exact lengths (s / m) and exact stored
    intensity_min/max (plus a read-only `pace` hint), so untouched steps round-trip unchanged."""
    metric = native.get("primaryIntensityMetric")
    steps: list[dict] = []
    for block in native.get("structure") or []:
        inner = [_coach_step(s, metric, thr) for s in _steps(block)]
        reps = _block_reps(block)
        if reps > 1 or len(inner) > 1:
            steps.append({"type": "repetition", "reps": reps, "steps": inner})
        elif inner:
            steps.append(inner[0])
    return {"primaryIntensityMetric": metric, "steps": steps}


def has_builder(native: Any) -> bool:
    return isinstance(native, dict) and bool(native.get("structure"))
