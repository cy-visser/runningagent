"""Shared schema version and primitive coercion helpers for web UI report payloads."""

from datetime import date
from typing import Any, Optional

REPORT_DATA_VERSION = 1


def iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else (text or None)


def round_or_none(value: Any, digits: int = 1) -> Optional[float]:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return round(num, digits)
