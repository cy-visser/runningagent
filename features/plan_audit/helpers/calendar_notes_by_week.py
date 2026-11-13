"""Attaches calendar notes to their ISO week buckets for the plan audit."""

from typing import Optional

from ....shared.calendar_notes import truncate_note
from ....shared.dates import iso_week_key, parse_date

AUDIT_NOTE_MAX_CHARS = 100
_REST_PLACEHOLDERS = frozenset({"rest", "rest day", "off", "day off"})


def add_notes_to_weeks(weeks: dict[str, dict], notes: Optional[list[dict]]) -> None:
    """Appends non-trivial calendar notes to the bucket of their week."""
    for n in notes or []:
        n_date = parse_date(n.get("date"))
        bucket = weeks.get(iso_week_key(n_date)) if n_date else None
        if bucket is None:
            continue
        title = " ".join(str(n.get("title") or "Note").split())
        desc = truncate_note(n.get("description") or "", limit=AUDIT_NOTE_MAX_CHARS)
        if title.lower() in _REST_PLACEHOLDERS and desc.lower() in ("", *_REST_PLACEHOLDERS):
            continue
        tail = f" | {desc}" if desc and desc.lower() != title.lower() else ""
        bucket["notes"].append(f"{n_date.strftime('%a %b %d')}: {title}{tail}")
