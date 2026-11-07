from datetime import date, timedelta
from typing import Any, Optional

from ..dates import parse_date
from ..sports import is_race_title
from ..health_metrics import HEALTH_BASELINE_DAYS
from .projection_evidence import _num, completed_runs

# Detraining correction: time x (CTL_then / CTL_now) ** K, capped. Heuristic;
# only ever penalises (fitness gains since the session are credited elsewhere).
DETRAINING_K = 0.15
MAX_DETRAINING_PENALTY = 1.15

# S6 health
HEALTH_WINDOW_DAYS = 5
HRV_DROP = 0.07
RHR_RISE = 3.0
SLEEP_DROP_H = 0.75
HEAVY_TSB = -10.0
HEAVY_ATL_CTL = 1.15
RACE_WEEK_DAYS = 7
MAX_HEALTH_PENALTY = 0.02
# A recent race or unusually big day explains suppressed HRV/RHR during its recovery window, even
# when the PMC looks fresh (one session after a taper barely moves ATL/TSB).
HARD_EFFORT_LOOKBACK_DAYS = 21
HARD_EFFORT_TSS_X_CTL = 2.5
RECOVERY_DAYS_BY_KM = ((40.0, 14), (21.0, 10), (10.0, 5), (0.0, 3))


def _fmt_day(d: Optional[date]) -> str:
    return d.strftime("%d %b") if d else "date n/a"


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


def _recovery_days(km: float) -> int:
    return next(days for min_km, days in RECOVERY_DAYS_BY_KM if km >= min_km)


def recent_hard_effort(
    workouts: Optional[list[dict]],
    today: date,
    daily_pmc: Optional[list[dict]] = None,
    race_dates: Any = (),
) -> Optional[dict]:
    """Most recent completed run whose recovery window still covers `today`, or None.

    A run counts when it falls on a goal race date, is titled as a race, or its TSS is
    >= HARD_EFFORT_TSS_X_CTL x the CTL of the day before (an unusually big day). The
    recovery window scales with distance (RECOVERY_DAYS_BY_KM, e.g. 14 days after a marathon).
    """
    race_days = set(race_dates or ())
    for w in completed_runs(workouts, today - timedelta(days=HARD_EFFORT_LOOKBACK_DAYS), today):
        d = parse_date(w.get("date") or w.get("start_time"))
        title = w.get("title") or ""
        tss = _num(w.get("tss_actual")) or _num(w.get("tss")) or 0.0
        ctl_before = ctl_on(daily_pmc, d - timedelta(days=1))
        is_race = d in race_days or is_race_title(title)
        big_day = bool(ctl_before) and tss >= HARD_EFFORT_TSS_X_CTL * ctl_before
        if not (is_race or big_day):
            continue
        km = _num(w.get("distance_actual_km")) or 0.0
        recovery = _recovery_days(km)
        days_ago = (today - d).days
        if days_ago <= recovery:
            return {"title": title, "date": d, "days_ago": days_ago, "recovery_days": recovery,
                    "is_race": is_race, "km": km, "tss": tss}
    return None


def format_effort_fact(effort: Optional[dict]) -> Optional[str]:
    """"last hard effort 'Schoorl 10K' 6 days ago, 10.0 km, TSS 95" (a fact, no verdict)."""
    if not effort:
        return None
    days = effort["days_ago"]
    ago = "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"
    return (f"last hard effort '{effort['title']}' {ago} ({_fmt_day(effort['date'])}), "
            f"{effort['km']:.1f} km, TSS {effort['tss']:.0f}")


def _load_facts(tsb: Optional[float], atl: Optional[float], ctl: Optional[float]) -> list[str]:
    facts = []
    if tsb is not None:
        facts.append(f"TSB {tsb:+.0f}")
    if atl and ctl:
        facts.append(f"ATL:CTL {atl / ctl:.2f}")
    return facts


def health_readiness(
    dated_metrics: Optional[dict[str, list[tuple[date, float]]]],
    today: date,
    days_to_race: Optional[float],
    tsb: Optional[float],
    atl: Optional[float],
    ctl: Optional[float],
    recent_effort: Optional[dict] = None,
) -> dict:
    """S6: 5-day HRV/RHR/sleep vs 28-day baseline; load-aware in build, time-affecting in race week.

    `recent_effort` (from recent_hard_effort) explains poor markers during its recovery window.
    `flag`/`detail` feed the web payload and `penalty`/`confidence_drop` the model; `facts` is the
    verdict-free text for the coach (deltas, the recent hard effort, TSB and ATL:CTL).
    """
    if not dated_metrics:
        return {"flag": "⚪", "markers": 0, "confidence_drop": False, "penalty": 0.0, "detail": "no health data",
                "facts": "no health data"}
    recent_start = today - timedelta(days=HEALTH_WINDOW_DAYS - 1)
    base_start = today - timedelta(days=HEALTH_BASELINE_DAYS)

    def split(key: str) -> tuple[Optional[float], Optional[float]]:
        vals = dated_metrics.get(key) or []
        recent = [v for d, v in vals if d and d >= recent_start]
        base = [v for d, v in vals if d and base_start <= d < recent_start]
        avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        return avg(recent), avg(base)

    parts, markers = [], 0
    hrv_r, hrv_b = split("hrv")
    if hrv_r is not None and hrv_b:
        change = hrv_r / hrv_b - 1
        parts.append(f"HRV {change * 100:+.0f}% vs 28d")
        markers += change <= -HRV_DROP
    rhr_r, rhr_b = split("rhr")
    if rhr_r is not None and rhr_b is not None:
        parts.append(f"RHR {rhr_r - rhr_b:+.0f} bpm")
        markers += (rhr_r - rhr_b) >= RHR_RISE
    sl_r, sl_b = split("sleep")
    if sl_r is not None:
        parts.append(f"sleep {sl_r:.1f}h" + (f" ({(sl_r - sl_b) * 60:+.0f} min)" if sl_b else ""))
        markers += bool(sl_b) and (sl_b - sl_r) >= SLEEP_DROP_H

    if not parts:
        return {"flag": "⚪", "markers": 0, "confidence_drop": False, "penalty": 0.0, "detail": "no health data",
                "facts": "no health data"}

    heavy = (tsb is not None and tsb <= HEAVY_TSB) or (bool(atl) and bool(ctl) and atl / ctl >= HEAVY_ATL_CTL)
    race_week = days_to_race is not None and 0 <= days_to_race <= RACE_WEEK_DAYS
    detail = ", ".join(parts)
    effort_fact = format_effort_fact(recent_effort)
    facts = "; ".join([detail] + ([effort_fact] if effort_fact else []) + _load_facts(tsb, atl, ctl))
    result = _readiness_verdict(markers, race_week, heavy, recent_effort, detail)
    result["facts"] = facts
    return result


def _readiness_verdict(markers: int, race_week: bool, heavy: bool, recent_effort: Optional[dict],
                       detail: str) -> dict:
    """Web flag/detail and model penalty/confidence_drop (never rendered into the coach's text)."""
    if markers >= 2:
        if race_week:
            penalty = min(MAX_HEALTH_PENALTY, MAX_HEALTH_PENALTY * markers / 3)
            return {"flag": "🔴", "markers": markers, "confidence_drop": True, "penalty": penalty,
                    "detail": f"{detail} — poor trend in race week (+{penalty * 100:.1f}% race-day)"}
        if recent_effort:
            e = recent_effort
            ago = "today" if e["days_ago"] == 0 else f"{e['days_ago']} day{'s' if e['days_ago'] != 1 else ''} ago"
            return {"flag": "🟡", "markers": markers, "confidence_drop": False, "penalty": 0.0,
                    "detail": f"{detail} — recovery after '{e['title']}' ({_fmt_day(e['date'])}, {ago}; "
                              f"typically ~{e['recovery_days']} days)"}
        if heavy:
            return {"flag": "🟡", "markers": markers, "confidence_drop": False, "penalty": 0.0,
                    "detail": f"{detail} — training-induced, expected to clear in taper"}
        return {"flag": "🔴", "markers": markers, "confidence_drop": True, "penalty": 0.0,
                "detail": f"{detail} — not explained by training load (illness/stress?)"}
    if markers == 1:
        return {"flag": "🟡", "markers": 1, "confidence_drop": False, "penalty": 0.0, "detail": detail}
    return {"flag": "🟢", "markers": 0, "confidence_drop": False, "penalty": 0.0, "detail": detail}
