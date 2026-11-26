"""Start-of-year vs. current fitness/recovery shift and calendar-year peak performances."""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any, Optional

from ....shared.dates import iso_date, parse_date
from ....shared.hr_pace_fit import is_run, lt_paces
from ....shared.units import as_float, fmt_clock, format_seconds_hms

SHIFT_WINDOW_WEEKS = 8
MIN_LT_SPAN_DAYS = 42  # require >= 6 weeks between earliest and latest LT fit to show a shift

# TrainingPeaks Run peak types -> (display label, exact distance in metres, profile.personal_records key).
PEAK_DISTANCES: tuple[tuple[str, str, float, Optional[str]], ...] = (
    ("speed1K", "1 km", 1000.0, None),
    ("speed5K", "5 km", 5000.0, "5k"),
    ("speed10K", "10 km", 10000.0, "10k"),
    ("speedHalfMarathon", "Half Marathon", 21097.5, "half_marathon"),
    ("speedMarathon", "Marathon", 42195.0, "marathon"),
)

_MIN_RUN_SPEED_MS = 0.8
_MAX_RUN_SPEED_MS = 10.0


def _verdict(change: float, first: float, higher_is_better: bool, *, rel_tol: float = 0.015) -> tuple[str, str]:
    """Returns `(arrow, verdict)` where verdict is 'improving' | 'stable' | 'declining'."""
    if abs(change) < 1e-9 or (first and abs(change / first) < rel_tol):
        return "→", "stable"
    arrow = "↑" if change > 0 else "↓"
    improving = change > 0 if higher_is_better else change < 0
    return arrow, ("improving" if improving else "declining")


def _dated_window_avg(dated: list[tuple[date, float]], start: date, end: date) -> Optional[float]:
    vals = [v for d, v in dated if start <= d <= end and v is not None]
    return mean(vals) if len(vals) >= 3 else None


def compute_fitness_shift(
    *,
    records: list[dict[str, Any]],
    weekly: list[dict[str, Any]],
    dated_metrics: dict[str, list[tuple[date, float]]],
    start: date,
    today: date,
    lthr: Optional[float],
    lt1_hr: Optional[float],
) -> dict[str, Any]:
    """Computes start-of-year vs. current shifts for LT2, LT1, RHR, HRV, and weekly volume."""
    items: list[dict[str, Any]] = []
    analyzed_runs = [r for r in (records or []) if is_run(r) and r.get("laps")]
    analyzed_dates = sorted(d for r in analyzed_runs if (d := parse_date(r.get("date"))) is not None)

    # 1. Rolling 4-week LT2 & LT1 pace across the year from training_log records.
    lt1_points: list[tuple[date, float]] = []
    lt2_points: list[tuple[date, float]] = []
    if lthr and analyzed_runs:
        for w in weekly:
            w_start = parse_date(w.get("week"))
            if not w_start:
                continue
            w_end = min(w_start + timedelta(days=6), today)
            fit = lt_paces(analyzed_runs, w_end, lthr, lt1_hr)
            if fit.get("lt2_pace_s"):
                lt2_points.append((w_end, float(fit["lt2_pace_s"])))
            if fit.get("lt1_pace_s"):
                lt1_points.append((w_end, float(fit["lt1_pace_s"])))

    for key, label, pts in (
        ("lt2_pace_s", "Pace @ LT2 (Threshold)", lt2_points),
        ("lt1_pace_s", "Pace @ LT1 (Aerobic Z2)", lt1_points),
    ):
        if len(pts) >= 2 and (pts[-1][0] - pts[0][0]).days >= MIN_LT_SPAN_DAYS:
            n = min(4, max(1, len(pts) // 3))
            first = mean(v for _, v in pts[:n])
            latest = mean(v for _, v in pts[-n:])
            change = latest - first
            arrow, verdict = _verdict(change, first, higher_is_better=False, rel_tol=0.008)
            items.append({
                "key": key,
                "label": label,
                "start": f"{fmt_clock(first)}/km",
                "latest": f"{fmt_clock(latest)}/km",
                "delta": f"{change:+.0f} s/km",
                "arrow": arrow,
                "verdict": verdict,
            })

    # 2. Resting HR & HRV (early vs latest non-overlapping windows in the calendar year, up to 8 weeks each).
    elapsed_days = (today - start).days + 1
    if elapsed_days >= SHIFT_WINDOW_WEEKS * 7:
        win_days = min(SHIFT_WINDOW_WEEKS * 7, elapsed_days // 2)
        early_end = start + timedelta(days=win_days - 1)
        late_start = today - timedelta(days=win_days - 1)

        rhr_series = (dated_metrics or {}).get("rhr") or []
        rhr_first = _dated_window_avg(rhr_series, start, early_end)
        rhr_latest = _dated_window_avg(rhr_series, late_start, today)
        if rhr_first is not None and rhr_latest is not None:
            diff = rhr_latest - rhr_first
            arrow, verdict = _verdict(diff, rhr_first, higher_is_better=False, rel_tol=0.015)
            items.append({
                "key": "rhr",
                "label": "Resting Heart Rate",
                "start": f"{rhr_first:.0f} bpm",
                "latest": f"{rhr_latest:.0f} bpm",
                "delta": f"{diff:+.0f} bpm",
                "arrow": arrow,
                "verdict": verdict,
            })

        hrv_series = (dated_metrics or {}).get("hrv") or []
        hrv_first = _dated_window_avg(hrv_series, start, early_end)
        hrv_latest = _dated_window_avg(hrv_series, late_start, today)
        if hrv_first is not None and hrv_latest is not None and hrv_first > 0:
            pct = (hrv_latest / hrv_first - 1.0) * 100.0
            arrow, verdict = _verdict(hrv_latest - hrv_first, hrv_first, higher_is_better=True, rel_tol=0.025)
            items.append({
                "key": "hrv",
                "label": "HRV (Morning Avg)",
                "start": f"{hrv_first:.0f} ms",
                "latest": f"{hrv_latest:.0f} ms",
                "delta": f"{pct:+.0f}%",
                "arrow": arrow,
                "verdict": verdict,
            })

    # 3. Avg Weekly Volume (first 8 complete weeks vs last 8 complete weeks).
    complete_weeks = [w for w in weekly if not w.get("partial")]
    if len(complete_weeks) >= 8:
        n = min(SHIFT_WINDOW_WEEKS, len(complete_weeks) // 2)
        vol_first = mean(float(w.get("km") or 0.0) for w in complete_weeks[:n])
        vol_latest = mean(float(w.get("km") or 0.0) for w in complete_weeks[-n:])
        if vol_first > 0 or vol_latest > 0:
            diff = vol_latest - vol_first
            arrow, verdict = _verdict(diff, vol_first, higher_is_better=True, rel_tol=0.05)
            delta_str = (
                f"{(diff / vol_first) * 100:+.0f}%"
                if vol_first >= 5.0
                else f"{diff:+.0f} km/wk"
            )
            items.append({
                "key": "weekly_km",
                "label": "Avg Weekly Volume",
                "start": f"{vol_first:.0f} km/wk",
                "latest": f"{vol_latest:.0f} km/wk",
                "delta": delta_str,
                "arrow": arrow,
                "verdict": verdict,
            })

    return {
        "items": items,
        "analyzed_runs": len(analyzed_runs),
        "coverage_start": iso_date(analyzed_dates[0]) if analyzed_dates else None,
        "coverage_end": iso_date(analyzed_dates[-1]) if analyzed_dates else None,
    }


def _rank_key(rec: dict[str, Any]) -> tuple[int, float]:
    """0-indexed rank key (`rank == 0` is #1 in TrainingPeaks — never treat 0 as falsy)."""
    raw_rank = rec.get("rank")
    rank = int(raw_rank) if raw_rank is not None else 999
    return (rank, -(as_float(rec.get("value")) or 0.0))


def _top_peak(payload: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("isError"):
        return None
    recs = payload.get("records")
    if not isinstance(recs, list) or not recs:
        return None
    valid = [r for r in recs if isinstance(r, dict) and as_float(r.get("value"))]
    if not valid:
        return None
    valid.sort(key=_rank_key)
    return valid[0]


def _dates_within_one_day(a_iso: Optional[str], b_iso: Optional[str]) -> bool:
    da, db = parse_date(a_iso), parse_date(b_iso)
    return bool(da and db and abs((da - db).days) <= 1)


def format_peak_performances(
    year_peaks: dict[str, dict[str, Any]],
    profile: Optional[dict[str, Any]],
    start: date,
    today: date,
) -> list[dict[str, Any]]:
    """Extracts true #1 calendar-year fastest efforts per distance and compares strictly against `profile.personal_records`."""
    start_iso, end_iso = iso_date(start), iso_date(today)
    prs = (profile or {}).get("personal_records")
    prs = prs if isinstance(prs, dict) else {}
    out: list[dict[str, Any]] = []
    for pr_type, label, dist_m, pr_key in PEAK_DISTANCES:
        top_yr = _top_peak(year_peaks.get(pr_type))
        if not top_yr:
            continue
        speed_ms = as_float(top_yr.get("value"))
        if not speed_ms or not (_MIN_RUN_SPEED_MS <= speed_ms <= _MAX_RUN_SPEED_MS):
            continue
        p_date = parse_date(top_yr.get("date"))
        p_iso = iso_date(p_date) if p_date else None
        if p_iso and not (start_iso <= p_iso <= end_iso):
            continue

        pr_entry = prs.get(pr_key) if pr_key else None
        pr_entry = pr_entry if isinstance(pr_entry, dict) else None
        profile_pr_time = str(pr_entry.get("time") or "").strip() or None if pr_entry else None
        profile_pr_date = str(pr_entry.get("date") or "").strip()[:10] or None if pr_entry else None
        is_profile_pr = bool(pr_entry and profile_pr_date and _dates_within_one_day(p_iso, profile_pr_date))

        wid_yr = str(top_yr.get("workout_id") or "")
        time_s = round(dist_m / speed_ms)
        pace_s = round(1000.0 / speed_ms, 1)
        out.append({
            "pr_type": pr_type,
            "distance": label,
            "time_s": time_s,
            "time": format_seconds_hms(time_s),
            "pace_s": pace_s,
            "pace": f"{fmt_clock(pace_s)}/km",
            "date": p_iso,
            "workout_id": wid_yr or None,
            "workout_title": str(top_yr.get("workout_title") or "").strip() or None,
            "all_time_pr": is_profile_pr,
            "profile_pr_time": profile_pr_time,
            "profile_pr_date": profile_pr_date,
        })
    return out
