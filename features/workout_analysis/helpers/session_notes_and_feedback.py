PLANNED_NOTES_MAX_CHARS = 800


def planned_notes(meta: dict) -> str:
    """The workout's planned description (coach notes), capped for token efficiency."""
    notes = str(meta.get("description") or "").strip()
    if len(notes) > PLANNED_NOTES_MAX_CHARS:
        notes = notes[:PLANNED_NOTES_MAX_CHARS].rstrip() + "…"
    return notes


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
