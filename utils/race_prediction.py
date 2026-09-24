"""Shared race-time helpers: Riegel, time formatting and CTL-based detraining.

The goal-race projection itself lives in `race_readiness.py`; this module keeps
the small, pure building blocks it relies on.
"""

from datetime import date
from typing import Optional

from .date_helpers import parse_date

RIEGEL_EXPONENT = 1.06

# Detraining correction: time x (CTL_then / CTL_now) ** K, capped. Heuristic;
# only ever penalises (fitness gains since the session are credited elsewhere).
DETRAINING_K = 0.15
MAX_DETRAINING_PENALTY = 1.15


def riegel_predict(time_s: float, from_km: float, to_km: float) -> float:
    """Riegel: T2 = T1 * (D2 / D1) ** 1.06."""
    return time_s * (to_km / from_km) ** RIEGEL_EXPONENT


def format_seconds_hms(seconds: Optional[float]) -> str:
    """Formats seconds as H:MM:SS (>= 1h) or M:SS."""
    if seconds is None:
        return "-"
    total = int(round(abs(seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def ctl_on(daily_pmc: Optional[list[dict]], day: Optional[date]) -> Optional[float]:
    """Returns the CTL on (or nearest before) a given date from PMC daily data."""
    if not daily_pmc or day is None:
        return None
    best_val, best_day = None, None
    for entry in daily_pmc:
        d = parse_date(entry.get("date"))
        if d is None or d > day:
            continue
        if best_day is None or d > best_day:
            best_day, best_val = d, entry.get("ctl")
    try:
        return float(best_val) if best_val is not None else None
    except (TypeError, ValueError):
        return None


def detraining_factor(ctl_then: Optional[float], ctl_now: Optional[float]) -> float:
    """Time multiplier (>= 1.0) for evidence set at a higher CTL than today."""
    if not ctl_then or not ctl_now or ctl_now <= 0 or ctl_now >= ctl_then:
        return 1.0
    return min(MAX_DETRAINING_PENALTY, (ctl_then / ctl_now) ** DETRAINING_K)
