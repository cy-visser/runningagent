"""Lap speed-vs-HR regression, threshold lap stats and LT1/LT2 pace estimation."""

from datetime import date, timedelta
from typing import Optional

from .dates import parse_date
from .sports import RUN_SPORTS

# S1 threshold laps
THRESHOLD_LAP_MIN_S = 480
THRESHOLD_LAP_MAX_S = 2400
THRESHOLD_HR_BAND = (0.88, 1.02)
THRESHOLD_AGREEMENT = 0.03   # observed vs TP setting within 3% -> average them
# Lap must be within 10% of the TP threshold speed (drops cool-downs with lagging HR).
THRESHOLD_PACE_BAND = 0.10

# S3 regression
STEADY_LAP_MIN_S = 480
STEADY_MIN_HR = 0.70
MIN_REGRESSION_POINTS = 5
MIN_HR_SPREAD = 0.08
MAX_EXTRAPOLATION = 0.05

HEAT_FEELS_LIKE_C = 20.0
LT_FIT_WEEKS = 4             # rolling window for the weekly HR->pace fit


def is_run(record: dict) -> bool:
    return str(record.get("sport") or "").lower() in RUN_SPORTS


def is_hot(record: dict) -> bool:
    feels = (record.get("weather") or {}).get("feels_like_c")
    return feels is not None and feels > HEAT_FEELS_LIKE_C


def evidence_date(summary: dict) -> Optional[date]:
    return parse_date(summary.get("date"))


def pct_of_lthr(hr: Optional[float], lthr: Optional[float]) -> Optional[float]:
    return hr / lthr if hr and lthr else None


def threshold_lap_stats(
    summaries: list[dict], lthr: Optional[float], tp_speed: Optional[float]
) -> Optional[dict]:
    """Duration-weighted speed and %LTHR of threshold laps (goal-independent).

    Threshold laps: 8-40 min at 88-102% LTHR and, when a TP threshold pace is set,
    within 10% of it. Callers pass only the summaries that may contain them.
    """
    if not lthr:
        return None
    total_s = weighted = hr_weighted = 0.0
    latest: Optional[date] = None
    for s in summaries:
        for lap in s.get("laps", []):
            pct = pct_of_lthr(lap.get("hr"), lthr)
            d = lap.get("duration_s") or 0
            if (pct is None or not lap.get("speed_ms")
                    or not THRESHOLD_LAP_MIN_S <= d <= THRESHOLD_LAP_MAX_S
                    or not THRESHOLD_HR_BAND[0] <= pct <= THRESHOLD_HR_BAND[1]
                    or (tp_speed and abs(lap["speed_ms"] / tp_speed - 1) > THRESHOLD_PACE_BAND)):
                continue
            total_s += d
            weighted += lap["speed_ms"] * d
            hr_weighted += pct * d
            ed = evidence_date(s)
            latest = max(latest, ed) if latest and ed else (ed or latest)
    if not total_s:
        return None
    return {"speed": weighted / total_s, "pct": hr_weighted / total_s, "total_s": total_s, "latest": latest}


def steady_lap_points(summaries: list[dict], lthr: Optional[float]) -> list[tuple[float, float, float, Optional[date]]]:
    """(hr, speed_ms, duration_s, date) for steady laps: >= 8 min and >= 70% LTHR."""
    if not lthr:
        return []
    pts = []
    for s in summaries:
        for lap in s.get("laps", []):
            hr, speed, d = lap.get("hr"), lap.get("speed_ms"), lap.get("duration_s") or 0
            if hr and speed and d >= STEADY_LAP_MIN_S and hr >= STEADY_MIN_HR * lthr:
                pts.append((hr, speed, d, evidence_date(s)))
    return pts


def fit_speed_vs_hr(pts: list[tuple], lthr: float) -> Optional[dict]:
    """Duration-weighted linear fit speed = my + slope * (hr - mx); None when not well-posed."""
    if len(pts) < MIN_REGRESSION_POINTS:
        return None
    hrs = [p[0] for p in pts]
    if (max(hrs) - min(hrs)) < MIN_HR_SPREAD * lthr:
        return None
    w_sum = sum(p[2] for p in pts)
    mx = sum(p[0] * p[2] for p in pts) / w_sum
    my = sum(p[1] * p[2] for p in pts) / w_sum
    sxx = sum(p[2] * (p[0] - mx) ** 2 for p in pts)
    sxy = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts)
    if sxx <= 0 or sxy <= 0:
        return None
    return {"mx": mx, "my": my, "slope": sxy / sxx, "hr_min": min(hrs), "hr_max": max(hrs), "n": len(pts)}


def lt_paces(records: list[dict], week_end: date, lthr: Optional[float], lt1_hr: Optional[float]) -> dict:
    """Pace (s/km) at LT1 HR and at LTHR from a duration-weighted HR->pace fit over steady laps
    (>= 8 min, >= 70% LTHR, hot runs excluded) of the LT_FIT_WEEKS weeks ending `week_end`.

    HRs outside the fitted range are capped at +/- MAX_EXTRAPOLATION * LTHR and flagged.
    """
    out = {"lt1_pace_s": None, "lt2_pace_s": None, "lt1_extrapolated": False, "lt2_extrapolated": False}
    if not lthr:
        return out
    start = (week_end - timedelta(weeks=LT_FIT_WEEKS) + timedelta(days=1)).isoformat()
    window = [r for r in records if is_run(r) and r.get("laps") and not is_hot(r)
              and start <= (r.get("date") or "") <= week_end.isoformat()]
    fit = fit_speed_vs_hr(steady_lap_points(window, lthr), lthr)
    if not fit:
        return out
    margin = MAX_EXTRAPOLATION * lthr
    for key, hr in (("lt1", lt1_hr), ("lt2", lthr)):
        if not hr:
            continue
        capped = max(fit["hr_min"] - margin, min(hr, fit["hr_max"] + margin))
        speed = fit["my"] + fit["slope"] * (capped - fit["mx"])
        if speed > 0:
            out[f"{key}_pace_s"] = 1000.0 / speed
            out[f"{key}_extrapolated"] = not (fit["hr_min"] <= hr <= fit["hr_max"])
    return out
