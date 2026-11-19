"""Shared calendar note truncation and week-bucket attachment helpers."""

from typing import Optional

from .dates import iso_week_key, parse_date

# Calendar notes can hold multi-page race plans; keep enough context to signal travel/illness/plans.
NOTE_DESC_MAX_CHARS = 240
WEEK_NOTE_MAX_CHARS = 60
_REST_PLACEHOLDERS = frozenset({"rest", "rest day", "off", "day off"})


def truncate_note(text: str, limit: int = NOTE_DESC_MAX_CHARS) -> str:
    """Collapses whitespace and caps `text` at <= `limit` chars (including the ellipsis)."""
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    cut = compact[: limit - 1].rsplit(" ", 1)[0] or compact[: limit - 1]
    return cut.rstrip(" ,;:-") + "…"


def add_notes_to_weeks(weeks: dict[str, dict], notes: Optional[list[dict]]) -> None:
    """Appends non-trivial calendar notes to the bucket of their ISO week."""
    for n in notes or []:
        n_date = parse_date(n.get("date"))
        bucket = weeks.get(iso_week_key(n_date)) if n_date else None
        if bucket is None:
            continue
        title = " ".join(str(n.get("title") or "Note").split())
        if title.lower().startswith("master goal:"):
            continue  # roadmap goal notes duplicate <runner_profile> GOAL PLAN
        raw_desc = " | ".join(
            seg.strip()
            for seg in str(n.get("description") or "").split("|")
            if seg.strip() and seg.strip().lower() not in _REST_PLACEHOLDERS
        )
        desc = truncate_note(raw_desc, limit=WEEK_NOTE_MAX_CHARS)
        if title.lower() in _REST_PLACEHOLDERS and desc.lower() in ("", *_REST_PLACEHOLDERS):
            continue
        tail = f" | {desc}" if desc and desc.lower() != title.lower() else ""
        bucket["notes"].append(f"{n_date.strftime('%a %b %d')}: {title}{tail}")
