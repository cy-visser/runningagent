"""Formats the multi-week plan audit text summary."""

from typing import Optional

from ....shared.weekly_buckets import format_week_line
from .long_run_annotations import format_week_long_run, format_week_volume


def format_plan_audit_summary(weeks_data: list[dict], goal_context: Optional[str] = None) -> str:
    """Formats a multi-week plan audit breakdown with each week's sessions and notes."""
    lines = ["### Training Plan Audit & Workload Assessment\n"]
    if goal_context:
        lines += [goal_context, ""]

    for w in weeks_data:
        lines.append(format_week_line(w))
        long_run = format_week_long_run(w)
        if long_run:
            lines.append(f"    - 🏃 {long_run}")
        volume = format_week_volume(w)
        if volume:
            lines.append(f"    - 📈 {volume}")
        for s in w.get("sessions", []):
            lines.append(f"    - {s}")
        for note in w.get("notes", []):
            lines.append(f"    - 📝 Note: {note}")
        lines.append("")

    return "\n".join(lines)
