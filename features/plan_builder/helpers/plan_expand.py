"""Plan spec -> dated sessions per week (pure code): normalisation, week merging and code expansion.

Spec (the coach's `stage_training_plan(plan=...)`): {"start_date", "mode", "title", "weeks": [{"week": 1,
"phase": "base", "focus": "...", "days": {"Mon": "E 8", "Tue": ["T 2x15' r2'", "S 30' core-hips"], ...}}]}.
Week n starts on the Monday of start_date's ISO week + (n - 1) weeks. Days before the cutoff (today, or a
start_date later in week 1) are skipped. Every unreadable code is reported, so nothing is staged until
the whole plan builds.
"""

import json
from datetime import date, timedelta
from typing import Any, Optional

from ....shared.dates import iso_date, monday_of, parse_date
from .session_codes import CodeError, build_session, normalize

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_KEYS = {d.lower(): d for d in DAYS} | {
    "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu", "friday": "Fri",
    "saturday": "Sat", "sunday": "Sun", "tues": "Tue", "thur": "Thu", "thurs": "Thu",
}
MODES = ("new", "overhaul")
MAX_WEEKS = 52
REST = "REST"


def _error(week: Any, day: Any, code: Any, why: str) -> dict:
    return {"week": week, "day": day, "code": code, "why": why}


def _codes(value: Any) -> list[str]:
    """A day's codes: a string (several separated by ';' or ',') or a list of strings."""
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        for part in str(item if item is not None else "").replace(";", ",").split(","):
            if normalize(part):
                out.append(normalize(part))
    return out


def _week(raw: Any, errors: list[dict]) -> Optional[dict]:
    if not isinstance(raw, dict):
        errors.append(_error(None, None, None, "each week must be an object with week, phase and days"))
        return None
    try:
        number = int(raw.get("week"))
    except (TypeError, ValueError):
        errors.append(_error(raw.get("week"), None, None, "week needs its number (1 = the first week)"))
        return None
    if not 1 <= number <= MAX_WEEKS:
        errors.append(_error(number, None, None, f"week must be 1 to {MAX_WEEKS}"))
        return None
    days: dict[str, list[str]] = {}
    for key, value in (raw.get("days") or {}).items():
        day = _DAY_KEYS.get(str(key).strip().lower())
        if not day:
            errors.append(_error(number, key, None, "day must be Mon, Tue, Wed, Thu, Fri, Sat or Sun"))
            continue
        codes = _codes(value)
        if any(c.upper() == REST for c in codes) and len(codes) > 1:
            errors.append(_error(number, day, ", ".join(codes), "REST cannot share a day with sessions"))
            continue
        days.setdefault(day, []).extend(REST if c.upper() == REST else c for c in codes)
    return {"week": number, "phase": str(raw.get("phase") or "").strip(), "focus": str(raw.get("focus") or "").strip(),
            "days": {d: days[d] for d in DAYS if d in days}}


def normalize_plan(plan: Any, defaults: Optional[dict] = None) -> tuple[dict, list[dict]]:
    """(spec, errors): the coach's plan with readable week numbers and day keys (codes kept as written).

    `defaults` fills start_date / mode / title when the plan leaves them out (e.g. from fetch_plan_context).
    """
    defaults = defaults or {}
    errors: list[dict] = []
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except ValueError:
            return {}, [_error(None, None, None, "plan is not valid JSON")]
    if not isinstance(plan, dict):
        return {}, [_error(None, None, None, "plan must be an object with start_date and weeks")]
    weeks: dict[int, dict] = {}
    for raw in plan.get("weeks") or []:
        week = _week(raw, errors)
        if week and week["week"] in weeks:
            errors.append(_error(week["week"], None, None, "week number given twice"))
        elif week:
            weeks[week["week"]] = week
    start = parse_date(plan.get("start_date") or defaults.get("start_date"))
    mode = str(plan.get("mode") or defaults.get("mode") or "new").strip().lower()
    if mode not in MODES:
        errors.append(_error(None, None, None, "mode must be 'new' or 'overhaul'"))
    if not start:
        errors.append(_error(None, None, None, "start_date (YYYY-MM-DD) is missing"))
    spec = {
        "start_date": iso_date(start) if start else None,
        "mode": mode,
        "title": str(plan.get("title") or defaults.get("title") or "").strip(),
        "weeks": [weeks[n] for n in sorted(weeks)],
    }
    return spec, errors


def merge_weeks(base: dict, edit: dict) -> dict:
    """The base spec with the edit's weeks replacing (or adding) those week numbers; start / mode kept."""
    weeks = {w["week"]: w for w in base.get("weeks") or []}
    weeks.update({w["week"]: w for w in edit.get("weeks") or []})
    return {**base, "title": edit.get("title") or base.get("title"), "weeks": [weeks[n] for n in sorted(weeks)]}


def week_monday(spec: dict, number: int) -> date:
    return monday_of(parse_date(spec["start_date"])) + timedelta(weeks=number - 1)


def plan_window(spec: dict) -> tuple[date, date]:
    """(Monday of week 1, Sunday of the last week)."""
    last = max((w["week"] for w in spec.get("weeks") or []), default=1)
    return week_monday(spec, 1), week_monday(spec, last) + timedelta(days=6)


def cutoff_date(spec: dict, today: date) -> date:
    """The first day the plan may change: today, or a start_date later than today."""
    start = parse_date(spec.get("start_date"))
    return max(today, start) if start else today


def expand_week(week: dict, monday: date, zones: dict, cutoff: date) -> dict:
    """{week, start, phase, focus, sessions, rest (ISO dates), days (ISO dates in scope), skipped, errors}.

    Each session (session_codes.build_session) gets its ISO `date`, `day` label and `write_date` (with the
    time of day for 'am' / 'pm' codes); sessions keep the order of the spec within a day.
    """
    sessions: list[dict] = []
    rest: list[str] = []
    errors: list[dict] = []
    skipped = 0
    for offset, label in enumerate(DAYS):
        day = monday + timedelta(days=offset)
        for code in week["days"].get(label, []):
            if day < cutoff:
                skipped += code != REST
                continue
            if code == REST:
                rest.append(iso_date(day))
                continue
            try:
                session = build_session(code, zones, week.get("phase"), day)
            except CodeError as e:
                errors.append(_error(week["week"], label, code, str(e)))
                continue
            when = iso_date(day)
            sessions.append({**session, "date": when, "day": label,
                             "write_date": f"{when}T{session['time']}:00" if session.get("time") else when})
    in_scope = [iso_date(monday + timedelta(days=i)) for i in range(7) if monday + timedelta(days=i) >= cutoff]
    return {"week": week["week"], "start": iso_date(monday), "phase": week.get("phase") or "",
            "focus": week.get("focus") or "", "sessions": sessions, "rest": rest, "days": in_scope,
            "skipped": skipped, "errors": errors}


def expand_plan(spec: dict, zones: dict, today: date) -> tuple[list[dict], list[dict]]:
    """(expanded weeks, errors over the whole plan)."""
    cutoff = cutoff_date(spec, today)
    weeks = [expand_week(w, week_monday(spec, w["week"]), zones, cutoff) for w in spec.get("weeks") or []]
    return weeks, [e for w in weeks for e in w["errors"]]
