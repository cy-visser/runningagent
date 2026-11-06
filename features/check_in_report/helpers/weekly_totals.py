from datetime import date
from typing import Optional

from ....shared.weekly_buckets import format_week_line

VOLUME_GROWTH_LIMIT_PCT = 10.0


def annotate_week_progression(weeks: list[dict], window_start: date, window_end: date) -> list[dict]:
    """Marks weeks only partly inside the window and adds running-volume growth vs the prior week.

    `partial`: the week is not fully inside [window_start, window_end]; `in_progress`: it is the
    current week (ends after window_end), as opposed to a past week clipped by the window start.
    Growth is only computed between two complete weeks (a partial week would fake a drop or
    spike) and when the prior week had running volume. Mutates and returns `weeks`.
    """
    prev: Optional[dict] = None
    for w in weeks:
        w["in_progress"] = w["end_date"] > window_end
        w["partial"] = w["start_date"] < window_start or w["in_progress"]
        w["growth_pct"] = None
        if prev and not prev["partial"] and not w["partial"] and prev["total_distance_km"] > 0:
            w["growth_pct"] = (w["total_distance_km"] / prev["total_distance_km"] - 1) * 100
        prev = w
    return weeks


def _week_progression(w: dict) -> str:
    """Pre-computed run split and week-over-week volume growth (check-in weekly totals)."""
    out = ""
    runs = w.get("easy_count", 0) + w.get("quality_count", 0)
    if runs:
        easy_pct = round(100 * w.get("easy_count", 0) / runs)
        out += f" | Split: {easy_pct}% easy / {100 - easy_pct}% quality (by runs)"
    if w.get("in_progress"):
        out += " | Current week (in progress): no growth comparison"
    elif w.get("partial"):
        out += " | Partial week (only partly in window): no growth comparison"
    elif w.get("growth_pct") is not None:
        growth = w["growth_pct"]
        flag = f" ⚠️ > {VOLUME_GROWTH_LIMIT_PCT:g}%" if growth > VOLUME_GROWTH_LIMIT_PCT else ""
        out += f" | Volume vs prior week: {growth:+.1f}%{flag}"
    return out


def format_weekly_totals(weeks: Optional[list[dict]]) -> str:
    """Pre-computed weekly totals (no LLM arithmetic needed)."""
    if not weeks:
        return "No completed training in this window."
    return "\n".join(format_week_line(w) + _week_progression(w) for w in weeks)
