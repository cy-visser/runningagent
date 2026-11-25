"""Calendar-year (Jan 1 – Dec 31) KPI, monthly/weekly trajectory, sport mix, and heatmap aggregation."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Optional

from ....shared.dates import iso_date, monday_of, parse_date
from ....shared.sports import (
    BIKE_SPORTS,
    NON_TRAINING_SPORTS,
    RUN_SPORTS,
    STRENGTH_SPORTS,
    is_quality_title,
    is_race_title,
)
from ....shared.units import as_float
from ....shared.workout_status import is_workout_completed

_MONTH_ABBR = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def calendar_year_window(year: int, today: date) -> tuple[date, date, bool]:
    """Returns `(start, end, is_complete)` for calendar year `year` (`Jan 1 – Dec 31`).

    `is_complete` is True only once `today > date(year, 12, 31)` so Dec 31 workouts are never finalized early.
    """
    start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    is_complete = today > year_end
    end = year_end if is_complete else min(today, year_end)
    return start, end, is_complete


def _sport_bucket(sport: Optional[str]) -> Optional[str]:
    raw = str(sport or "").strip()
    if raw in NON_TRAINING_SPORTS:
        return None
    low = raw.lower()
    if low in RUN_SPORTS or low == "race":
        return "running"
    if low in BIKE_SPORTS:
        return "cycling"
    if low in STRENGTH_SPORTS:
        return "strength"
    return "other"


def _heatmap_level(km: float) -> int:
    if km <= 0:
        return 0
    if km < 7.0:
        return 1
    if km < 13.0:
        return 2
    if km < 20.0:
        return 3
    return 4


def _longest_streak(flags: list[bool]) -> int:
    best = cur = 0
    for active in flags:
        if active:
            cur += 1
            if cur > best:
                best = cur
        else:
            cur = 0
    return best


def _week_mondays(start: date, end: date) -> list[date]:
    """All Monday dates whose Mon–Sun week overlaps `[start, end]`."""
    first = monday_of(start)
    last = monday_of(end)
    out: list[date] = []
    cur = first
    while cur <= last:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def aggregate_year(
    *,
    year: int,
    workouts: list[dict[str, Any]],
    records: list[dict[str, Any]],
    daily_pmc: list[dict[str, Any]],
    races: list[dict[str, Any]],
    start: date,
    end: date,
    is_complete: bool,
) -> dict[str, Any]:
    """Computes KPIs, 12-month Jan–Dec series, elapsed weekly series, milestones, mix, and Jan–Dec heatmap."""
    start_iso, end_iso = iso_date(start), iso_date(end)
    year_end = date(year, 12, 31)
    records_by_id = {str(r.get("workout_id") or ""): r for r in (records or []) if r.get("workout_id")}
    race_by_date: dict[str, dict[str, Any]] = {}
    for r in races or []:
        race_by_date.setdefault(str(r["date"]), r)

    # Filter to completed training workouts strictly within [Jan 1, end].
    completed: list[dict[str, Any]] = []
    for w in workouts or []:
        d_str = str(w.get("date") or "")[:10]
        if not (start_iso <= d_str <= end_iso):
            continue
        if not is_workout_completed(w):
            continue
        if _sport_bucket(w.get("sport")) is None:
            continue
        completed.append(w)

    # Daily PMC lookup strictly within [Jan 1, end].
    pmc_by_day: dict[str, dict[str, float]] = {}
    for row in daily_pmc or []:
        d_str = str(row.get("date") or "")[:10]
        if start_iso <= d_str <= end_iso:
            ctl = as_float(row.get("ctl"))
            if ctl is not None:
                pmc_by_day[d_str] = {
                    "ctl": round(ctl, 1),
                    "tss": as_float(row.get("tss")) or 0.0,
                }

    sport_hours = {"running": 0.0, "cycling": 0.0, "strength": 0.0, "other": 0.0}
    sport_sessions = {"running": 0, "cycling": 0, "strength": 0, "other": 0}
    run_mix_counts = {"easy": 0, "quality": 0, "long_race": 0}

    day_run_km: dict[str, float] = {}
    total_run_km = 0.0
    total_tss = 0.0
    longest_run: Optional[dict[str, Any]] = None

    # Elapsed Mon–Sun weeks overlapping [Jan 1, end].
    elapsed_week_starts = _week_mondays(start, end)
    weekly_map: dict[str, dict[str, Any]] = {
        iso_date(ws): {
            "week": iso_date(ws),
            "km": 0.0,
            "runs": 0,
            "sessions": 0,
            "tss": 0.0,
            "long_km": 0.0,
            "ctl": None,
            "ctl_peak_date": None,
            "partial": (not is_complete) and ((ws + timedelta(days=6)) > end),
            "races": [],
        }
        for ws in elapsed_week_starts
    }

    # Always pre-seed all 12 calendar months Jan–Dec for `year`.
    monthly_map: dict[str, dict[str, Any]] = {}
    for m in range(1, 13):
        mkey = f"{year:04d}-{m:02d}"
        m_last = date(year, m, calendar.monthrange(year, m)[1])
        is_future = (not is_complete) and (date(year, m, 1) > end)
        is_partial = (not is_complete) and (not is_future) and (end < m_last)
        monthly_map[mkey] = {
            "month": mkey,
            "label": _MONTH_ABBR[m],
            "km": 0.0,
            "runs": 0,
            "hours": 0.0,
            "tss": 0.0,
            "ctl": None,
            "ctl_peak_date": None,
            "partial": is_partial,
            "future": is_future,
            "races": [],
        }

    for w in completed:
        bucket = _sport_bucket(w.get("sport"))
        if bucket is None:
            continue
        d_str = str(w.get("date") or "")[:10]
        w_date = parse_date(d_str)
        if not w_date:
            continue
        hours = as_float(w.get("duration_actual")) or 0.0
        tss = as_float(w.get("tss_actual")) or 0.0
        sport_hours[bucket] += hours
        sport_sessions[bucket] += 1
        total_tss += tss

        wk_key = iso_date(monday_of(w_date))
        m_key = d_str[:7]
        if wk_key in weekly_map:
            weekly_map[wk_key]["sessions"] += 1
            weekly_map[wk_key]["tss"] += tss
        if m_key in monthly_map:
            monthly_map[m_key]["hours"] += hours
            monthly_map[m_key]["tss"] += tss

        if bucket == "running":
            km = as_float(w.get("distance_actual_km")) or 0.0
            total_run_km += km
            day_run_km[d_str] = day_run_km.get(d_str, 0.0) + km
            if wk_key in weekly_map:
                weekly_map[wk_key]["km"] += km
                weekly_map[wk_key]["runs"] += 1
                if km > weekly_map[wk_key]["long_km"]:
                    weekly_map[wk_key]["long_km"] = km
            if m_key in monthly_map:
                monthly_map[m_key]["km"] += km
                monthly_map[m_key]["runs"] += 1
            if km > 0 and (longest_run is None or km > longest_run["km"]):
                longest_run = {
                    "km": round(km, 1),
                    "date": d_str,
                    "title": str(w.get("title") or "Long Run").strip() or "Long Run",
                }

            rec = records_by_id.get(str(w.get("id") or ""))
            kind = (rec or {}).get("kind")
            if kind in ("race", "long"):
                run_mix_counts["long_race"] += 1
            elif kind == "quality":
                run_mix_counts["quality"] += 1
            elif kind == "easy":
                run_mix_counts["easy"] += 1
            else:
                title = str(w.get("title") or "")
                if d_str in race_by_date or is_race_title(title) or km >= 20.0 or "long" in title.lower():
                    run_mix_counts["long_race"] += 1
                elif is_quality_title(title):
                    run_mix_counts["quality"] += 1
                else:
                    run_mix_counts["easy"] += 1

    # Attach peak (max) CTL and peak date to elapsed weeks and non-future months.
    for ws in elapsed_week_starts:
        wk_key = iso_date(ws)
        wk_end = min(ws + timedelta(days=6), end)
        wk_start = max(ws, start)
        best_ctl: Optional[float] = None
        best_day: Optional[str] = None
        cur = wk_start
        while cur <= wk_end:
            cand = iso_date(cur)
            if cand in pmc_by_day:
                val = pmc_by_day[cand]["ctl"]
                if best_ctl is None or val > best_ctl:
                    best_ctl = val
                    best_day = cand
            cur += timedelta(days=1)
        weekly_map[wk_key]["ctl"] = best_ctl
        weekly_map[wk_key]["ctl_peak_date"] = best_day

    for m in range(1, 13):
        m_key = f"{year:04d}-{m:02d}"
        if monthly_map[m_key]["future"]:
            continue
        m_start = date(year, m, 1)
        m_end = min(date(year, m, calendar.monthrange(year, m)[1]), end)
        best_ctl = None
        best_day = None
        cur = m_start
        while cur <= m_end:
            cand = iso_date(cur)
            if cand in pmc_by_day:
                val = pmc_by_day[cand]["ctl"]
                if best_ctl is None or val > best_ctl:
                    best_ctl = val
                    best_day = cand
            cur += timedelta(days=1)
        monthly_map[m_key]["ctl"] = best_ctl
        monthly_map[m_key]["ctl_peak_date"] = best_day

    # Pin races onto weekly & monthly series (oldest first).
    for r in sorted(races or [], key=lambda x: x["date"]):
        r_date = parse_date(r["date"])
        if not r_date or not (start <= r_date <= end):
            continue
        pin = {
            "date": r["date"],
            "name": r["name"],
            "short_label": r.get("short_label") or "Race",
            "duration_s": r.get("duration_s"),
            "is_pr": bool(r.get("is_pr")),
            "badge": r.get("badge") or "Race",
        }
        wk_key = iso_date(monday_of(r_date))
        m_key = r["date"][:7]
        if wk_key in weekly_map:
            weekly_map[wk_key]["races"].append(pin)
        if m_key in monthly_map:
            monthly_map[m_key]["races"].append(pin)

    weekly = [
        {
            **row,
            "km": round(row["km"], 1),
            "tss": round(row["tss"], 1),
            "long_km": round(row["long_km"], 1),
        }
        for row in weekly_map.values()
    ]
    monthly = [
        {
            **row,
            "km": round(row["km"], 1),
            "hours": round(row["hours"], 1),
            "tss": round(row["tss"], 1),
        }
        for row in monthly_map.values()
    ]

    pmc_dates = sorted(pmc_by_day.keys())
    ctl_start = pmc_by_day[pmc_dates[0]]["ctl"] if pmc_dates else None
    ctl_end = pmc_by_day[pmc_dates[-1]]["ctl"] if pmc_dates else None
    ctl_delta = round(ctl_end - ctl_start, 1) if (ctl_start is not None and ctl_end is not None) else None
    ctl_delta_pct = (
        round((ctl_delta / ctl_start) * 100)
        if (ctl_delta is not None and ctl_start and ctl_start > 0)
        else None
    )
    ctl_peak_day = max(pmc_dates, key=lambda d: pmc_by_day[d]["ctl"]) if pmc_dates else None
    ctl_peak = pmc_by_day[ctl_peak_day]["ctl"] if ctl_peak_day else None

    active_flags = [w["sessions"] > 0 for w in weekly]
    active_weeks = sum(active_flags)
    total_weeks_elapsed = max(1, len(weekly))
    longest_streak = _longest_streak(active_flags)
    peak_week = max(weekly, key=lambda w: w["km"]) if weekly else None
    elapsed_months = [m for m in monthly if not m.get("future")]
    peak_month = max(elapsed_months, key=lambda m: m["km"]) if elapsed_months else None

    total_hours = sum(sport_hours.values())
    total_runs = sport_sessions["running"]
    total_workouts = len(completed)
    elapsed_weeks_float = max(1.0, ((end - start).days + 1) / 7.0)

    sport_mix = []
    for key, label in (
        ("running", "Running"),
        ("cycling", "Cycling / Cross"),
        ("strength", "Strength & Mobility"),
        ("other", "Other"),
    ):
        hrs = round(sport_hours[key], 1)
        cnt = sport_sessions[key]
        if cnt == 0 and hrs == 0:
            continue
        pct = round((sport_hours[key] / total_hours) * 100) if total_hours > 0 else 0
        sport_mix.append({"key": key, "label": label, "hours": hrs, "sessions": cnt, "pct": pct})

    run_mix_total = sum(run_mix_counts.values())
    run_mix = {
        "easy_pct": round(run_mix_counts["easy"] / run_mix_total * 100) if run_mix_total else 0,
        "quality_pct": round(run_mix_counts["quality"] / run_mix_total * 100) if run_mix_total else 0,
        "long_race_pct": round(run_mix_counts["long_race"] / run_mix_total * 100) if run_mix_total else 0,
        "easy_runs": run_mix_counts["easy"],
        "quality_runs": run_mix_counts["quality"],
        "long_race_runs": run_mix_counts["long_race"],
    }

    # Full calendar-year Jan 1 – Dec 31 daily heatmap (column-major Mon..Sun).
    # level: -1 = outside calendar year padding, -2 = future day remaining in current year, 0..4 = volume bucket.
    full_year_weeks = _week_mondays(start, year_end)
    heatmap_weeks: list[dict[str, Any]] = []
    run_days = 0
    for ws in full_year_weeks:
        days_list = []
        for offset in range(7):
            d = ws + timedelta(days=offset)
            d_iso = iso_date(d)
            if d < start or d > year_end:
                level = -1
                km = 0.0
                race = None
            elif d > end:
                level = -2
                km = 0.0
                race = None
            else:
                km = round(day_run_km.get(d_iso, 0.0), 1)
                if km > 0:
                    run_days += 1
                level = _heatmap_level(km)
                race = race_by_date.get(d_iso)
            days_list.append({
                "date": d_iso,
                "km": km,
                "level": level,
                "is_race": bool(race),
                "race_name": race["name"] if race else None,
            })
        heatmap_weeks.append({"week": iso_date(ws), "days": days_list})

    kpis = {
        "total_run_km": round(total_run_km, 1),
        "avg_weekly_run_km": round(total_run_km / elapsed_weeks_float, 1),
        "total_runs": total_runs,
        "total_workouts": total_workouts,
        "total_hours": round(total_hours, 1),
        "run_hours": round(sport_hours["running"], 1),
        "bike_hours": round(sport_hours["cycling"], 1),
        "strength_hours": round(sport_hours["strength"], 1),
        "ctl_start": ctl_start,
        "ctl_end": ctl_end,
        "ctl_delta": ctl_delta,
        "ctl_delta_pct": ctl_delta_pct,
        "ctl_peak": ctl_peak,
        "ctl_peak_date": ctl_peak_day,
        "total_tss": round(total_tss),
        "active_weeks": active_weeks,
        "total_weeks": total_weeks_elapsed,
        "active_weeks_pct": round(active_weeks / total_weeks_elapsed * 100),
        "longest_streak_weeks": longest_streak,
        "peak_week_km": peak_week["km"] if peak_week and peak_week["km"] > 0 else None,
        "peak_week_date": peak_week["week"] if peak_week and peak_week["km"] > 0 else None,
    }

    milestones = {
        "longest_run": longest_run,
        "peak_week": (
            {"km": peak_week["km"], "date": peak_week["week"]}
            if peak_week and peak_week["km"] > 0
            else None
        ),
        "peak_month": (
            {"km": peak_month["km"], "label": peak_month["label"], "month": peak_month["month"]}
            if peak_month and peak_month["km"] > 0
            else None
        ),
    }

    return {
        "kpis": kpis,
        "monthly": monthly,
        "weekly": weekly,
        "milestones": milestones,
        "mix": {"sports": sport_mix, "run_breakdown": run_mix},
        "heatmap": {
            "weeks": heatmap_weeks,
            "run_days": run_days,
            "longest_streak_weeks": longest_streak,
        },
    }
