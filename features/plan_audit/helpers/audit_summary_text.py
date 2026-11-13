"""Formats the compact multi-week plan audit text summary."""

from collections import Counter
from datetime import date
from typing import Optional

from .long_run_annotations import format_audit_week_header

_SPORT_SHORT = {
    "run": "Run",
    "running": "Run",
    "bike": "Bike",
    "cycling": "Bike",
    "strength": "Str",
    "gym": "Str",
}


def _sport_label(sport: Optional[str]) -> str:
    raw = (sport or "Run").strip()
    return _SPORT_SHORT.get(raw.lower(), raw)


def _format_session_item(item: dict, multi_day: bool, dup_sport_days: set[tuple[date, str]]) -> str:
    sport_raw = (item.get("sport") or "Run").strip()
    sport = _sport_label(sport_raw)
    time_str = f"@{item['time']}" if multi_day and item.get("time") else ""
    km = round(float(item.get("km") or 0.0), 1)
    minutes = round(float(item.get("minutes") or 0.0))
    metric = f" {km:g}km" if km > 0 else (f" {minutes}'" if minutes > 0 else "")
    tss = round(float(item.get("tss") or 0.0))
    tss_str = f" TSS {tss}" if tss > 0 else ""
    need_id = (
        not item.get("completed")
        and bool(item.get("id"))
        and (item["date"], sport_raw.lower()) in dup_sport_days
    )
    id_str = f" [{item['id']}]" if need_id else ""
    return f"{sport}{time_str} '{item.get('title') or sport_raw}'{metric}{tss_str}{id_str}"


def _format_week_sessions(items: list[dict]) -> str:
    if not items:
        return ""
    ordered = sorted(items, key=lambda s: (s["date"], s.get("time") or ""))
    planned_counts = Counter(
        (s["date"], (s.get("sport") or "Run").strip().lower())
        for s in ordered
        if not s.get("completed")
    )
    dup_sport_days = {k for k, n in planned_counts.items() if n >= 2}
    by_day: dict[date, list[dict]] = {}
    for s in ordered:
        by_day.setdefault(s["date"], []).append(s)
    day_parts = []
    for day, day_items in by_day.items():
        multi_day = len(day_items) >= 2
        rendered = "; ".join(_format_session_item(s, multi_day, dup_sport_days) for s in day_items)
        day_parts.append(f"{day.strftime('%a')}: {rendered}")
    return " | ".join(day_parts)


def format_plan_audit_summary(weeks_data: list[dict], goal_context: Optional[str] = None) -> str:
    """Formats a compact multi-week plan audit breakdown with day-grouped sessions and notes."""
    lines = ["### Training Plan Audit"]
    if goal_context:
        lines += ["", goal_context]
    lines.append("")

    for w in weeks_data:
        lines.append(format_audit_week_header(w))
        sessions_line = _format_week_sessions(w.get("session_items") or [])
        if sessions_line:
            lines.append(f"  Sessions: {sessions_line}")
        if w.get("notes"):
            lines.append(f"  Notes: {' · '.join(w['notes'])}")
    return "\n".join(lines)
