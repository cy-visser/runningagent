"""Versioned Firestore payload builder for the calendar-year Annual Review."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ....shared.web_report_payload import iso_or_none

YEAR_REVIEW_VERSION = 5


def build_year_review_payload(
    *,
    now: datetime,
    year: int,
    start: date,
    end: date,
    is_complete: bool,
    runner_name: str,
    aggregated: dict[str, Any],
    races: list[dict[str, Any]],
    fitness_shift: dict[str, Any],
    peaks: list[dict[str, Any]],
    sync_mode: str = "full",
) -> dict[str, Any]:
    """Assembles the versioned `users/{runner_id}/cache/year_review_{year}` document."""
    clean_races = [
        {
            "date": r["date"],
            "workout_id": r.get("workout_id"),
            "name": r["name"],
            "badge": r.get("badge") or "Race",
            "priority": r.get("priority"),
            "short_label": r.get("short_label") or "Race",
            "distance_label": r.get("distance_label"),
            "distance_km": r.get("distance_km"),
            "duration_s": r.get("duration_s"),
            "pace_s": r.get("pace_s"),
            "avg_hr": r.get("avg_hr"),
            "pct_lthr": r.get("pct_lthr"),
            "pa_hr": r.get("pa_hr"),
            "ctl": r.get("ctl"),
            "is_pr": bool(r.get("is_pr")),
            "goal_text": r.get("goal_text"),
            "goal_gap_s": r.get("goal_gap_s"),
            "note": r.get("note"),
        }
        for r in races
    ]

    kpis = aggregated["kpis"]
    end_iso = iso_or_none(end)
    return {
        "version": YEAR_REVIEW_VERSION,
        "year": int(year),
        "is_complete": bool(is_complete),
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "as_of_date": end_iso,
        "last_computed_date": end_iso,
        "sync_mode": sync_mode,
        "runner_name": runner_name,
        "window": {
            "start": iso_or_none(start),
            "end": end_iso,
            "year_end": f"{int(year):04d}-12-31",
            "weeks": kpis["total_weeks"],
        },
        "coverage": {
            "total_workouts": kpis["total_workouts"],
            "total_runs": kpis["total_runs"],
            "analyzed_runs": fitness_shift["analyzed_runs"],
            "training_log_start": fitness_shift["coverage_start"],
            "training_log_end": fitness_shift["coverage_end"],
        },
        "kpis": kpis,
        "monthly": aggregated["monthly"],
        "weekly": aggregated["weekly"],
        "races": clean_races,
        "fitness_shift": fitness_shift["items"],
        "peaks": peaks,
        "milestones": aggregated["milestones"],
        "mix": aggregated["mix"],
        "heatmap": aggregated["heatmap"],
    }


def build_year_index_entry(payload: dict[str, Any]) -> dict[str, Any]:
    """Compact summary item persisted in `users/{runner_id}/cache/year_review_index`."""
    kpis = payload.get("kpis") or {}
    return {
        "year": int(payload["year"]),
        "total_run_km": float(kpis.get("total_run_km") or 0.0),
        "total_workouts": int(kpis.get("total_workouts") or 0),
        "races_count": len(payload.get("races") or []),
        "is_complete": bool(payload.get("is_complete")),
        "as_of_date": payload.get("as_of_date"),
    }
