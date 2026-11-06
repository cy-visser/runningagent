from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ....shared.web_report_payload import (
    REPORT_DATA_VERSION,
    iso_or_none as _iso,
    round_or_none as _opt_round,
)

TREND_REPORT_STATE_KEY = "trend_report_data"


def trend_report_data(
    start: date,
    today: date,
    rows: Optional[list[dict[str, Any]]],
    progress: Optional[list[dict[str, Any]]],
    levels: Optional[list[dict[str, Any]]],
    outlook: Optional[dict[str, Any]],
    key_run_label: Optional[str] = None,
) -> dict[str, Any]:
    """Structured long-horizon trend payload (`trend_report_data`) stored in session state."""
    weeks_payload = [
        {
            "week": _iso(r.get("week")),
            "complete": bool(r.get("complete")),
            "km": _opt_round(r.get("km"), 1) or 0.0,
            "tss": _opt_round(r.get("tss"), 1) or 0.0,
            "runs": int(r.get("runs") or 0),
            "quality": int(r.get("quality") or 0),
            "long_km": _opt_round(r.get("long_km"), 1) or 0.0,
            "ctl": _opt_round(r.get("ctl"), 1),
            "tsb": _opt_round(r.get("tsb"), 1),
            "hrv": _opt_round(r.get("hrv"), 1),
            "hrv_delta_pct": _opt_round(r.get("hrv_delta_pct"), 1),
            "rhr": _opt_round(r.get("rhr"), 1),
            "rhr_delta": _opt_round(r.get("rhr_delta"), 1),
            "sleep_h": _opt_round(r.get("sleep_h"), 2),
            "lt1_pace_s": _opt_round(r.get("lt1_pace_s"), 0),
            "lt2_pace_s": _opt_round(r.get("lt2_pace_s"), 0),
            "lt2_extrapolated": bool(r.get("lt2_extrapolated")),
            "key_decoupling": _opt_round(r.get("key_decoupling"), 1),
        }
        for r in (rows or [])
    ]

    progress_payload = [
        {
            "label": p.get("label"),
            "first": p.get("first"),
            "latest": p.get("latest"),
            "best": p.get("best"),
            "change": p.get("change"),
            "arrow": p.get("arrow"),
            "verdict": p.get("verdict"),
        }
        for p in (progress or [])
    ]

    levels_payload = [
        {
            "level": int(lv.get("level") or 0),
            "weeks": int(lv.get("weeks") or 0),
            "streak": int(lv.get("streak") or 0),
            "tolerated_share": _opt_round(lv.get("tolerated_share"), 2) or 0.0,
            "hrv_delta_pct": _opt_round(lv.get("hrv_delta_pct"), 1),
            "rhr_delta": _opt_round(lv.get("rhr_delta"), 1),
            "rpe": _opt_round(lv.get("rpe"), 1),
            "proven": bool(lv.get("proven")),
        }
        for lv in (levels or [])
    ]

    out_raw = outlook or {}
    outlook_payload = {
        "proven_km": int(out_raw["proven_km"]) if out_raw.get("proven_km") is not None else None,
        "max_km": _opt_round(out_raw.get("max_km"), 1) or 0.0,
        "current_km": _opt_round(out_raw.get("current_km"), 1) or 0.0,
        "targets": [
            {
                "target": int(t.get("target") or 0),
                "status": t.get("status"),
                "build_weeks": int(t.get("build_weeks") or 0),
            }
            for t in (out_raw.get("targets") or [])
        ],
    }

    return {
        "version": REPORT_DATA_VERSION,
        "window": {"start": _iso(start), "end": _iso(today)},
        "weeks": weeks_payload,
        "progress": progress_payload,
        "levels": levels_payload,
        "outlook": outlook_payload,
        "key_run_label": key_run_label,
    }
