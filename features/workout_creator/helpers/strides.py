"""Strides in run builders: kept when the coach rewrites a session, added after the warm-up of quality runs.

The coach sometimes rebuilds a session from scratch and drops the strides block of the current builder;
quality runs (tempo / threshold / intervals) should always open with strides after the warm-up. Both are
enforced here, in code, on the parsed native builder (exact % targets), via its exact coach view.
"""

from typing import Any, Optional

from ....shared.sports import RUN_SPORTS
from ....shared.units import as_float
from .workout_builder import PACE, coach_structure_from, parse_coach_structure

# A strides rep: a short fast step (<= 30 s or <= 150 m at >= 100 % of threshold pace), repeated.
STRIDE_MAX_S = 30
STRIDE_MAX_M = 150
STRIDE_MIN_PCT = 100
STRIDE_MIN_REPS = 3
# A quality main-set step: longer than this, centred at or above QUALITY_MID_PCT of threshold pace.
QUALITY_MIN_S = 60
QUALITY_MIN_M = 300
QUALITY_MID_PCT = 89
# Titles never given strides automatically (long runs with race-pace segments are excluded).
EXCLUDED_TITLE_WORDS = ("long run",)

KEPT = "kept"
ADDED = "added"

_TIME = {"second": 1.0, "minute": 60.0, "hour": 3600.0}
_DIST = {"meter": 1.0, "kilometer": 1000.0, "mile": 1609.344}


def default_strides() -> dict:
    """4x (20" stride @ 105-115 % / 40" jog @ 75-80 %) in the coach format."""
    return {"type": "repetition", "reps": 4, "steps": [
        {"name": "Stride", "intensityClass": "active", "duration_seconds": 20,
         "intensity_min": 105, "intensity_max": 115},
        {"name": "Jog", "intensityClass": "rest", "duration_seconds": 40, "intensity_min": 75, "intensity_max": 80},
    ]}


def _length(step: dict) -> tuple[Optional[float], Optional[float]]:
    """(seconds, metres) of a native step as written (only one is set)."""
    length = step.get("length") or {}
    unit, value = str(length.get("unit") or "").lower(), as_float(length.get("value"))
    if value is None:
        return None, None
    if unit in _TIME:
        return value * _TIME[unit], None
    if unit in _DIST:
        return None, value * _DIST[unit]
    return None, None


def _range(step: dict) -> tuple[Optional[float], Optional[float]]:
    first = (step.get("targets") or [{}])[0]
    lo, hi = as_float(first.get("minValue")), as_float(first.get("maxValue"))
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _steps(block: dict) -> list[dict]:
    return [s for s in (block.get("steps") or []) if isinstance(s, dict)]


def _reps(block: dict) -> int:
    length = block.get("length") or {}
    return max(int(as_float(length.get("value")) or 1), 1) if length.get("unit") == "repetition" else 1


def is_strides_block(block: dict) -> bool:
    """A native block of strides: named so, or >= STRIDE_MIN_REPS reps of a short fast active step."""
    names = [str(block.get("name") or "")] + [str(s.get("name") or "") for s in _steps(block)]
    if any("stride" in n.lower() for n in names):
        return True
    if _reps(block) < STRIDE_MIN_REPS:
        return False
    for step in _steps(block):
        if step.get("intensityClass") != "active":
            continue
        seconds, metres = _length(step)
        lo, _ = _range(step)
        short = (seconds is not None and seconds <= STRIDE_MAX_S) or (metres is not None and metres <= STRIDE_MAX_M)
        if short and lo is not None and lo >= STRIDE_MIN_PCT:
            return True
    return False


def strides_index(native: Optional[dict]) -> Optional[int]:
    """Index of the first strides block in a native builder, or None."""
    for i, block in enumerate((native or {}).get("structure") or []):
        if isinstance(block, dict) and is_strides_block(block):
            return i
    return None


def is_quality_run(native: dict, title: Any = None) -> bool:
    """Tempo / threshold / interval builder: structured (a warm-up or recovery step) with a main-set active
    step longer than QUALITY_MIN_S / QUALITY_MIN_M centred at >= QUALITY_MID_PCT of threshold pace.
    Long runs (title) are excluded."""
    if native.get("primaryIntensityMetric") != PACE:
        return False
    if any(word in str(title or "").lower() for word in EXCLUDED_TITLE_WORDS):
        return False
    blocks = [b for b in native.get("structure") or [] if isinstance(b, dict)]
    classes = {s.get("intensityClass") for b in blocks for s in _steps(b)}
    if not classes & {"warmUp", "rest"}:
        return False  # a single steady effort (race, steady run) is not a structured quality session
    for block in blocks:
        if is_strides_block(block):
            continue
        for step in _steps(block):
            if step.get("intensityClass") != "active":
                continue
            seconds, metres = _length(step)
            lo, hi = _range(step)
            long_enough = (seconds or 0) > QUALITY_MIN_S or (metres or 0) > QUALITY_MIN_M
            if long_enough and lo is not None and hi is not None and (lo + hi) / 2 >= QUALITY_MID_PCT:
                return True
    return False


def _after_warmup(steps: list[dict]) -> int:
    for i, step in enumerate(steps):
        if step.get("type") != "repetition" and step.get("intensityClass") == "warmUp":
            return i + 1
    return 0


def _before_cooldown(steps: list[dict]) -> int:
    if steps and steps[-1].get("type") != "repetition" and steps[-1].get("intensityClass") == "coolDown":
        return len(steps) - 1
    return len(steps)


def _was_at_end(current: dict, index: int) -> bool:
    """The current strides block closes the session (only a cool-down after it), e.g. easy run + strides."""
    rest = [b for b in (current.get("structure") or [])[index + 1:] if isinstance(b, dict)]
    return all(s.get("intensityClass") == "coolDown" for b in rest for s in _steps(b))


def ensure_strides(
    change: dict, native: dict, current: Optional[dict], thr: dict
) -> tuple[dict, Optional[str]]:
    """Returns (native builder to stage, KEPT / ADDED / None).

    Runs with a pace builder only, and never when the change says `strides: false` or already has strides.
    An update whose current builder has strides keeps that exact block (after the warm-up, or at the end
    when it closed the session); otherwise a quality run gets default_strides() after the warm-up.
    """
    if str(change.get("sport") or "Run").strip().lower() not in RUN_SPORTS or change.get("strides") is False:
        return native, None
    if native.get("primaryIntensityMetric") != PACE or strides_index(native) is not None:
        return native, None

    kept_at = strides_index(current) if current and current.get("primaryIntensityMetric") == PACE else None
    coach = coach_structure_from(native, thr)
    steps = coach["steps"]
    if kept_at is not None:
        block = coach_structure_from({**current, "structure": [current["structure"][kept_at]]}, thr)["steps"][0]
        position = _before_cooldown(steps) if _was_at_end(current, kept_at) else _after_warmup(steps)
        status = KEPT
    elif is_quality_run(native, change.get("title")):
        block, position, status = default_strides(), _after_warmup(steps), ADDED
    else:
        return native, None

    steps.insert(position, block)
    rebuilt, error = parse_coach_structure(coach, change.get("sport"), thr)
    return (native, None) if error else (rebuilt, status)
