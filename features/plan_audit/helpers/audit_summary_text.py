"""Formats the compact multi-week plan audit text summary."""

from typing import Optional

from ....shared.weekly_buckets import format_week_sessions
from .long_run_annotations import format_audit_week_header


def format_plan_audit_summary(weeks_data: list[dict], goal_context: Optional[str] = None) -> str:
    """Formats a compact multi-week plan audit breakdown with day-grouped sessions and notes."""
    lines = ["### Training Plan Audit"]
    if goal_context:
        lines += ["", goal_context]
    lines.append("")

    for w in weeks_data:
        lines.append(format_audit_week_header(w))
        sessions_line = format_week_sessions(w.get("session_items") or [])
        if sessions_line:
            lines.append(f"  Sessions: {sessions_line}")
        if w.get("notes"):
            lines.append(f"  Notes: {' · '.join(w['notes'])}")
    return "\n".join(lines)
