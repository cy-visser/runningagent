import re

PLANNED_NOTES_MAX_CHARS = 800
STRUCTURED_NOTES_MAX_CHARS = 280
_BUILDER_HEADING_RE = re.compile(r"^(?:warm[- ]?up|main set|cool[- ]?down)\b", re.IGNORECASE)


def planned_notes(meta: dict, *, structured: bool = False) -> str:
    """The workout's planned description (coach notes), stripping redundant builder blocks when `structured`."""
    raw = str(meta.get("description") or "").strip()
    if not raw:
        return ""
    if structured and "\n" in raw:
        # Keep non-builder blocks (Cues, Gear, Fueling, coach notes) when auto-generated Warm-up/Main Set/Cool-down
        # paragraphs merely echo `Planned structure & execution`.
        kept: list[str] = []
        for block in re.split(r"\n\s*\n", raw):
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue
            if _BUILDER_HEADING_RE.match(lines[0]):
                cues = [ln for ln in lines[1:] if re.match(r"^(?:-\s*)?(?:cues?|focus|note|gear|fueling)\s*:", ln, re.I)]
                if cues:
                    kept.extend(cues)
                continue
            kept.append(" ".join(lines))
        raw = " | ".join(kept).strip()
    limit = STRUCTURED_NOTES_MAX_CHARS if structured else PLANNED_NOTES_MAX_CHARS
    if len(raw) > limit:
        raw = raw[:limit].rstrip() + "…"
    return raw


def format_athlete_feedback(meta: dict) -> str:
    """RPE / feeling / comment recorded by the athlete in TrainingPeaks, or ''."""
    parts = []
    if meta.get("rpe") is not None:
        parts.append(f"RPE {meta['rpe']}/10")
    if meta.get("feeling") is not None:
        parts.append(f"Feeling {meta['feeling']}/10")
    calories = (meta.get("metrics") or {}).get("calories")
    if calories:
        parts.append(f"{calories} kcal")
    if meta.get("new_comment"):
        parts.append(f'Comment: "{meta["new_comment"]}"')
    return " | ".join(parts)
