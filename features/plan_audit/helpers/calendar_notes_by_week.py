"""Attaches calendar notes to their ISO week buckets for the plan audit."""

from typing import Optional

from ....shared.calendar_notes import truncate_note
from ....shared.dates import format_display_date, iso_week_key, parse_date


def add_notes_to_weeks(weeks: dict[str, dict], notes: Optional[list[dict]]) -> None:
    """Appends every calendar note to the bucket of its week."""
    for n in notes or []:
        n_date = parse_date(n.get("date"))
        bucket = weeks.get(iso_week_key(n_date)) if n_date else None
        if bucket is None:
            continue
        title = n.get("title") or "Note"
        desc = truncate_note(n.get("description") or "")
        bucket["notes"].append(f"{format_display_date(n_date)}: {title}" + (f" | {desc}" if desc else ""))
