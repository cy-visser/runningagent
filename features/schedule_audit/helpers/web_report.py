"""Structured schedule-audit web report payload (`audit_report_data`)."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ....shared.web_report_payload import REPORT_DATA_VERSION, iso_or_none, round_or_none
from .long_run_annotations import format_week_long_run

AUDIT_REPORT_STATE_KEY = "audit_report_data"


def audit_report_data(
    q_start: date,
    q_end: date,
    weeks: Optional[list[dict[str, Any]]],
) -> dict[str, Any]:
    """Structured schedule-audit payload (`audit_report_data`) stored in session state."""
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
    }
