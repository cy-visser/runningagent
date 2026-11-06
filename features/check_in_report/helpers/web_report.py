from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ....shared.goal_distance import DEFAULT_PEAK_CTL, DEFAULT_PEAK_RANGE
from ....shared.web_report_payload import (
    REPORT_DATA_VERSION,
    iso_or_none as _iso,
    round_or_none as _opt_round,
)
from .goal_trajectory import MAX_RAMP_PER_WEEK, SAFE_RAMP_PER_WEEK

CHECKIN_REPORT_STATE_KEY = "checkin_report_data"


def _ramp_tier(required_ramp: Optional[float]) -> Optional[str]:
    if required_ramp is None:
        return None
    if required_ramp <= SAFE_RAMP_PER_WEEK:
        return "safe"
    if required_ramp <= MAX_RAMP_PER_WEEK:
        return "aggressive"
    return "high_risk"


def _build_recovery_payload(
    dated_metrics: Optional[dict[str, list[tuple[date, float]]]],
    q_start: date,
    q_end: date,
) -> Optional[dict[str, Any]]:
    if not dated_metrics:
        return None

    by_day: dict[str, dict[str, Any]] = {}
    in_window: dict[str, list[float]] = {"hrv": [], "rhr": [], "sleep": []}
    for key, out_key, digits in (("hrv", "hrv", 1), ("rhr", "rhr", 1), ("sleep", "sleep_h", 2)):
        for day, val in dated_metrics.get(key) or []:
            if day is None or val is None or not (q_start <= day <= q_end):
                continue
            iso = day.isoformat()
            row = by_day.setdefault(iso, {"date": iso, "hrv": None, "rhr": None, "sleep_h": None})
            rounded = _opt_round(val, digits)
            if rounded is not None:
                row[out_key] = rounded
                in_window[key].append(float(val))

    series = [by_day[k] for k in sorted(by_day)]
    sleep_vals = in_window["sleep"]
    hrv_vals = in_window["hrv"]
    rhr_vals = in_window["rhr"]
    return {
        "sleep_avg_h": round(sum(sleep_vals) / len(sleep_vals), 2) if sleep_vals else None,
        "hrv_latest": round(hrv_vals[-1], 1) if hrv_vals else None,
        "rhr_latest": round(rhr_vals[-1], 1) if rhr_vals else None,
        "series": series,
    }


def _build_lt_payload(lt: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Current vs previous 4-week LT1/LT2 paces (s/km) and HR anchors, or None."""
    if not lt:
        return None
    now, prev = lt.get("now") or {}, lt.get("prev") or {}
    return {
        "lt1_pace_s": _opt_round(now.get("lt1_pace_s"), 0),
        "lt2_pace_s": _opt_round(now.get("lt2_pace_s"), 0),
        "lt1_prev_s": _opt_round(prev.get("lt1_pace_s"), 0),
        "lt2_prev_s": _opt_round(prev.get("lt2_pace_s"), 0),
        "lt1_hr": _opt_round(lt.get("lt1_hr"), 0),
        "lthr": _opt_round(lt.get("lthr"), 0),
        "lt1_extrapolated": bool(now.get("lt1_extrapolated")),
        "lt2_extrapolated": bool(now.get("lt2_extrapolated")),
    }


def checkin_report_data(
    q_start: date,
    q_end: date,
    fitness_data: Optional[dict[str, Any]],
    race_projection: Optional[dict[str, Any]],
    weekly_totals: Optional[list[dict[str, Any]]],
    dated_metrics: Optional[dict[str, list[tuple[date, float]]]],
    lt_paces: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Structured check-in payload (`checkin_report_data`) stored in session state."""
    fit = fitness_data or {}
    info = fit.get("trajectory_info") or {}

    ctl_current = _opt_round(fit.get("ctl_end"), 1) or 0.0
    atl_current = _opt_round(fit.get("atl_end"), 1) or 0.0
    tsb_current = _opt_round(fit.get("tsb_end"), 1) or 0.0
    target_peak = _opt_round(info.get("target_peak_ctl"), 1) or DEFAULT_PEAK_CTL
    raw_range = info.get("reference_range") or list(DEFAULT_PEAK_RANGE)
    ctl_range = [
        _opt_round(raw_range[0], 1) or DEFAULT_PEAK_RANGE[0],
        _opt_round(raw_range[1], 1) or DEFAULT_PEAK_RANGE[1],
    ]
    phase = info.get("phase")
    pre_taper = _opt_round(info.get("pre_taper_ctl"), 1)
    progress_ctl = pre_taper if (phase == "taper" and pre_taper is not None) else ctl_current
    pct = min(100, max(0, int((progress_ctl / target_peak) * 100))) if target_peak > 0 else 100
    req_ramp = _opt_round(info.get("required_ramp_rate"), 2)

    pmc_series = []
    for entry in sorted(fit.get("history") or [], key=lambda d: str(d.get("date") or "")):
        day_str = _iso(entry.get("date"))
        ctl_v = _opt_round(entry.get("ctl"), 1)
        atl_v = _opt_round(entry.get("atl"), 1)
        tsb_v = _opt_round(entry.get("tsb"), 1)
        if day_str and ctl_v is not None and atl_v is not None and tsb_v is not None:
            pmc_series.append({"date": day_str, "ctl": ctl_v, "atl": atl_v, "tsb": tsb_v})

    proj_wrap = race_projection or {}
    proj = proj_wrap.get("projection")
    projection_payload: Optional[dict[str, Any]] = None
    if isinstance(proj, dict):
        rng = proj.get("range_s")
        projection_payload = {
            "goal_label": proj.get("goal_label") or proj_wrap.get("goal_label"),
            "today_s": round(proj["today_s"]) if proj.get("today_s") is not None else None,
            "race_day_s": round(proj["race_day_s"]) if proj.get("race_day_s") is not None else None,
            "goal_s": round(proj["goal_s"]) if proj.get("goal_s") is not None else None,
            "gap_s": round(proj["gap_s"]) if proj.get("gap_s") is not None else None,
            "range_s": [round(rng[0]), round(rng[1])] if isinstance(rng, (list, tuple)) and len(rng) == 2 else None,
            "confidence": proj.get("confidence"),
            "stale": bool(proj.get("stale")),
            "readiness": proj.get("readiness"),
        }
    elif proj_wrap.get("goal_label"):
        projection_payload = {
            "goal_label": proj_wrap.get("goal_label"),
            "today_s": None,
            "race_day_s": None,
            "goal_s": None,
            "gap_s": None,
            "range_s": None,
            "confidence": None,
            "stale": False,
            "readiness": None,
        }

    weeks_payload = [
        {
            "week": _iso(w.get("start_date")),
            "date_range": w.get("date_range"),
            "km": _opt_round(w.get("total_distance_km"), 1) or 0.0,
            "tss": _opt_round(w.get("total_tss"), 1) or 0.0,
            "easy": int(w.get("easy_count") or 0),
            "quality": int(w.get("quality_count") or 0),
            "growth_pct": _opt_round(w.get("growth_pct"), 1),
            "partial": bool(w.get("partial")),
            "in_progress": bool(w.get("in_progress")),
        }
        for w in (weekly_totals or [])
    ]

    return {
        "version": REPORT_DATA_VERSION,
        "window": {"start": _iso(q_start), "end": _iso(q_end)},
        "ctl": {
            "current": ctl_current,
            "target": target_peak,
            "range": ctl_range,
            "pct": pct,
            "weeks_remaining": _opt_round(info.get("weeks_remaining"), 1),
            "required_ramp": req_ramp,
            "ramp_tier": _ramp_tier(req_ramp),
            "phase": phase,
            "pre_taper_ctl": pre_taper,
            "atl": atl_current,
            "tsb": tsb_current,
        },
        "pmc": pmc_series,
        "projection": projection_payload,
        "weeks": weeks_payload,
        "recovery": _build_recovery_payload(dated_metrics, q_start, q_end),
        "lt": _build_lt_payload(lt_paces),
    }
