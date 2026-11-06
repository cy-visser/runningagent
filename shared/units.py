"""Numeric coercion and distance/pace/duration unit conversions."""

from typing import Any, Optional

# Unit heuristics for MCP values that arrive without (reliable) units.
METERS_IF_ABOVE = 100.0        # distances above this are metres (no lap is 100+ km)
PACE_SECONDS_IF_ABOVE = 30.0   # paces above this are s/km (nobody runs 30 min/km)
_KM_PER_UNIT = {"m": 0.001, "km": 1.0, "mi": 1.609344}


def as_float(value: Any) -> Optional[float]:
    """Best-effort float from a raw MCP value; placeholders like '--', None and bools -> None."""
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_km(value: Any, unit: Optional[str] = None) -> Optional[float]:
    """Distance in km from a value in m/km/mi; guesses metres vs km when `unit` is unknown."""
    v = as_float(value)
    if v is None:
        return None
    factor = _KM_PER_UNIT.get(str(unit or "").strip().lower())
    if factor is not None:
        return v * factor
    return v / 1000.0 if v > METERS_IF_ABOVE else v


def pace_seconds(value: Any) -> Optional[float]:
    """Pace in s/km from a value in s/km or decimal min/km; None when not positive."""
    v = as_float(value)
    if not v or v <= 0:
        return None
    return v if v > PACE_SECONDS_IF_ABOVE else v * 60.0


def format_seconds_hms(seconds: Optional[float]) -> str:
    """Formats seconds as H:MM:SS (>= 1h) or M:SS."""
    if seconds is None:
        return "-"
    total = int(round(abs(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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


def fmt_num(value: Optional[float], fmt: str = "{:.0f}", suffix: str = "") -> str:
    return fmt.format(value) + suffix if value is not None else "-"
