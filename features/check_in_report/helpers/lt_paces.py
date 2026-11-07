from datetime import date, timedelta
from typing import Optional

from ....shared.hr_pace_fit import LT_FIT_WEEKS, lt_paces


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
