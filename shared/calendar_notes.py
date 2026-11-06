"""Shared calendar note truncation helper."""

# Calendar notes can hold multi-page race plans; keep enough context to signal travel/illness/plans.
NOTE_DESC_MAX_CHARS = 240


def truncate_note(text: str, limit: int = NOTE_DESC_MAX_CHARS) -> str:
    """Collapses whitespace and caps `text` at <= `limit` chars (including the ellipsis)."""
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    cut = compact[: limit - 1].rsplit(" ", 1)[0] or compact[: limit - 1]
    return cut.rstrip(" ,;:-") + "…"
