"""Structured plan-audit web report payload (`audit_report_data`)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ....shared.north_star_targets import RECOVERY_EVERY_WEEKS
from ....shared.web_report_payload import REPORT_DATA_VERSION, iso_or_none, round_or_none
from .long_run_annotations import format_week_long_run

AUDIT_REPORT_STATE_KEY = "audit_report_data"


def _volume_payload(v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Per-week running-volume reference path for the web calendar, or None (no path that week)."""
    if not v:
        return None
    return {
        "target_km": v["target_km"],
        "block_target_km": v["block_target_km"],
        "phase": v["phase"],
        "vs_path_pct": v.get("vs_path_pct"),
    }


def _volume_reference(weeks: Optional[list[dict[str, Any]]]) -> Optional[dict[str, Any]]:
    """How the weekly km targets are derived (block of the first targeted week), for the calendar caption."""
    v = next((w["volume"] for w in weeks or [] if w.get("volume")), None)
    if not v:
        return None
    return {
        "goal": v.get("goal"),
        "goal_label": v.get("goal_label"),
        "ns_goal": v.get("ns_goal"),
        "own_block": bool(v.get("own_block")),
        "block_target_km": v["block_target_km"],
        "ns_peak_km": v.get("ns_peak_km"),
        "start_km": v.get("start_km"),
        "peak_week": iso_or_none(v.get("peak_week")),
        "recovery_every_weeks": RECOVERY_EVERY_WEEKS,
    }


def audit_report_data(
    q_start: date,
    q_end: date,
    weeks: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Structured plan-audit payload (`audit_report_data`) stored in session state."""
    weeks_payload = [
        {
            "week": iso_or_none(w.get("start_date")),
            "date_range": w.get("date_range"),
            "km": round_or_none(w.get("total_distance_km"), 1) or 0.0,
            "tss": round_or_none(w.get("total_tss"), 0) or 0.0,
            "easy": int(w.get("easy_count") or 0),
            "quality": int(w.get("quality_count") or 0),
            "bike": int(w.get("bike_count") or 0),
            "strength": int(w.get("strength_count") or 0),
            "long_run": format_week_long_run(w) or None,
            "vs_prior_pct": w.get("vs_prior_pct"),
            "volume": _volume_payload(w.get("volume")),
            "notes": list(w.get("notes") or []),
            "sessions": [
                {
                    "date": iso_or_none(s.get("date")),
                    "sport": s.get("sport") or "Run",
                    "title": s.get("title") or (s.get("sport") or "Run"),
                    "category": s.get("category") or "easy",
                    "km": round_or_none(s.get("km"), 1) or 0.0,
                    "minutes": round(float(s.get("minutes") or 0.0)),
                    "tss": round_or_none(s.get("tss"), 0) or 0.0,
                    "completed": bool(s.get("completed")),
                }
                for s in sorted(
                    w.get("session_items") or [],
                    key=lambda item: iso_or_none(item.get("date")) or "",
                )
            ],
        }
        for w in (weeks or [])
    ]
    return {
        "version": REPORT_DATA_VERSION,
        "window": {"start": iso_or_none(q_start), "end": iso_or_none(q_end)},
        "weeks": weeks_payload,
        "volume_reference": _volume_reference(weeks),
    }
