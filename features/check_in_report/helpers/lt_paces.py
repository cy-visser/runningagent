from datetime import date, timedelta
from typing import Optional

from ....shared.hr_pace_fit import LT_FIT_WEEKS, lt_paces
from ....shared.progress_verdicts import (
    VERDICT_DECLINING,
    VERDICT_IMPROVING,
    VERDICT_STABLE,
)


def checkin_lt_paces(records: list[dict], today: date, lthr: Optional[float],
                     lt1_hr: Optional[float]) -> Optional[dict]:
    """Check-in LT1/LT2: the LT_FIT_WEEKS fit ending today vs the previous, non-overlapping one.

    None when the current window has no usable fit (no LTHR, too few steady laps).
    """
    now = lt_paces(records, today, lthr, lt1_hr)
    if now["lt1_pace_s"] is None and now["lt2_pace_s"] is None:
        return None
    prev = lt_paces(records, today - timedelta(weeks=LT_FIT_WEEKS), lthr, lt1_hr)
    return {"lt1_hr": lt1_hr, "lthr": lthr, "now": now, "prev": prev}


def lt_verdict(now_s: Optional[float], prev_s: Optional[float]) -> Optional[str]:
    """Pace verdict with the progress_summary rule: < 1% change is stable, faster is improving."""
    if now_s is None or not prev_s:
        return None
    change = now_s - prev_s
    if abs(change / prev_s) < 0.01:
        return VERDICT_STABLE
    return VERDICT_IMPROVING if change < 0 else VERDICT_DECLINING
