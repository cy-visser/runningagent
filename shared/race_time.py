"""Personal-record race times and structured shoe-rotation helpers for runner profiles."""

from __future__ import annotations

import re
from typing import Any, Optional

from .units import format_seconds_hms

# (stored key, display label, compact label for prompts)
PR_DISTANCES: tuple[tuple[str, str, str], ...] = (
    ("5k", "5K", "5K"),
    ("10k", "10K", "10K"),
    ("10_mile", "10 Mile", "10mi"),
    ("half_marathon", "Half Marathon", "HM"),
    ("marathon", "Marathon", "Marathon"),
)
# Stored key -> identifier-safe field name used by the onboarding answer schema.
_PR_ANSWER_FIELDS = {"5k": "five_k", "10k": "ten_k", "10_mile": "ten_mile"}

# (stored key, display label)
SHOE_SLOTS: tuple[tuple[str, str], ...] = (
    ("easy", "Easy"),
    ("tempo", "Tempo/Threshold"),
    ("interval", "Interval"),
    ("long_run", "Long run"),
    ("race", "Race"),
)

_TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,3}):(\d{2})$")


def parse_race_time(raw: Any) -> tuple[str, int]:
    """Parses 'MM:SS' or 'H:MM:SS' into `(normalised, seconds)`; raises ValueError when invalid."""
    text = str(raw or "").strip()
    match = _TIME_RE.match(text)
    if not match:
        raise ValueError(f"Race time must be MM:SS or H:MM:SS, got {raw!r}.")
    hours = int(match.group(1) or 0)
    minutes, seconds = int(match.group(2)), int(match.group(3))
    if seconds >= 60 or (match.group(1) is not None and minutes >= 60):
        raise ValueError(f"Race time {raw!r} has minutes or seconds out of range.")
    total = hours * 3600 + minutes * 60 + seconds
    if total <= 0:
        raise ValueError("Race time must be greater than zero.")
    return format_seconds_hms(total), total


def normalize_personal_records(raw: Any) -> Optional[dict[str, Any]]:
    """Normalises PRs (stored keys or onboarding field names) to `{key: {time, time_s, date} | None}`.

    Invalid times are dropped; returns None when no record is left.
    """
    if not isinstance(raw, dict):
        return None
    records: dict[str, Any] = {}
    for key, _, _ in PR_DISTANCES:
        entry = raw.get(key) or raw.get(_PR_ANSWER_FIELDS.get(key, key))
        if not isinstance(entry, dict) or not str(entry.get("time") or "").strip():
            records[key] = None
            continue
        try:
            time_text, time_s = parse_race_time(entry.get("time"))
        except ValueError:
            records[key] = None
            continue
        date_text = str(entry.get("date") or "").strip()[:10] or None
        records[key] = {"time": time_text, "time_s": time_s, "date": date_text}
    return records if any(records.values()) else None


def normalize_shoe_rotation(raw: Any) -> Optional[dict[str, Optional[str]]]:
    """Normalises shoe slots to `{slot: str | None}`; None when every slot is empty."""
    if not isinstance(raw, dict):
        return None
    slots = {key: (str(raw.get(key) or "").strip() or None) for key, _ in SHOE_SLOTS}
    return slots if any(slots.values()) else None


def format_personal_records(records: Any) -> str:
    """'5K 19:45 (2026-04-12), HM 1:27:48' for prompts; empty string when nothing is set."""
    if not isinstance(records, dict):
        return ""
    parts = []
    for key, _, short in PR_DISTANCES:
        entry = records.get(key)
        if isinstance(entry, dict) and entry.get("time"):
            date_text = f" ({entry['date']})" if entry.get("date") else ""
            parts.append(f"{short} {entry['time']}{date_text}")
    return ", ".join(parts)


def format_shoe_rotation(shoes: Any) -> str:
    """'Easy Superblast 2; Race Metaspeed Sky Paris' for prompts; empty string when nothing is set."""
    if not isinstance(shoes, dict):
        return ""
    return "; ".join(f"{label} {shoes[key]}" for key, label in SHOE_SLOTS if shoes.get(key))
