"""Plan spec -> dated sessions per week (pure code): normalisation, week merging and code expansion.

Spec (the coach's `stage_training_plan(plan=...)`): {"start_date", "mode", "title", "weeks": [{"week": 1,
"phase": "base", "focus": "...", "days": {"Mon": "E 8", "Tue": ["T 2x15' r2'", "S 30' core-hips"], ...}}]}.
Week n starts on the Monday of start_date's ISO week + (n - 1) weeks. Days before the cutoff (today, or a
start_date later in week 1) are skipped. Every unreadable code is reported, so nothing is staged until
the whole plan builds.
"""

import json
import re
from datetime import date, timedelta
from typing import Any, Optional

from ....shared.dates import iso_date, monday_of, parse_date
from ....shared.goal_plan import snap_new_block_start
from ....shared.session_codes.session_codes import CodeError, build_session, normalize

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_KEYS = {d.lower(): d for d in DAYS} | {
    "monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu", "friday": "Fri",
    "saturday": "Sat", "sunday": "Sun", "tu": "Tue", "tues": "Tue", "weds": "Wed",
    "th": "Thu", "thur": "Thu", "thurs": "Thu",
}
_SESSION_PREFIXES = frozenset({"E", "R", "L", "T", "I", "RP", "M", "P", "H", "RACE", "B", "S", "X", "REST"})
MODES = ("new", "overhaul")
MAX_WEEKS = 52
REST = "REST"
_WEEK_NUM_RE = re.compile(r"^(?:w(?:eek)?\s*)?(-?\d+)$", re.IGNORECASE)


def _error(week: Any, day: Any, code: Any, why: str) -> dict:
    return {"week": week, "day": day, "code": code, "why": why}


def _looks_like_day_typo(lhs: str, rhs: str) -> bool:
    """True when `lhs: rhs` in a header slot is a misspelled weekday + session code (e.g. 'Funday: E 8')."""
    word = lhs.strip()
    first_code = normalize(rhs.replace(";", ",").split(",", 1)[0]).split()
    return bool(word.isalpha() and first_code and first_code[0].upper() in _SESSION_PREFIXES)


def _codes(value: Any) -> list[str]:
    """A day's codes: a string (several separated by ';' or ',') or a list of strings."""
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        for part in str(item if item is not None else "").replace(";", ",").split(","):
            if normalize(part):
                out.append(normalize(part))
    return out


def _add_day_codes(number: int, key: Any, value: Any, days: dict[str, list[str]], errors: list[dict]) -> None:
    day = _DAY_KEYS.get(str(key).strip().lower())
    if not day:
        errors.append(_error(number, key, None, "day must be Mon, Tue, Wed, Thu, Fri, Sat or Sun"))
        return
    codes = _codes(value)
    if any(c.upper() == REST for c in codes) and len(codes) > 1:
        errors.append(_error(number, day, ", ".join(codes), "REST cannot share a day with sessions"))
        return
    days.setdefault(day, []).extend(REST if c.upper() == REST else c for c in codes)


def _parse_week_string(raw: str, errors: list[dict]) -> Optional[dict]:
    """Parses 'W1 | base | Aerobic base; 2x strength | Mon: E 8 | Tue: I 6x1k r2'; S 40' heavy-lower | Sun: L 18'."""
    segs = [s.strip() for s in raw.split("|") if s.strip()]
    if not segs:
        errors.append(_error(None, None, None, "empty week string"))
        return None
    m = _WEEK_NUM_RE.match(segs[0])
    if not m:
        errors.append(_error(segs[0], None, None, "week string must start with week number (e.g. 'W1 | base | ...')"))
        return None
    number = int(m.group(1))
    if not 1 <= number <= MAX_WEEKS:
        errors.append(_error(number, None, None, f"week must be 1 to {MAX_WEEKS}"))
        return None
    meta: list[str] = []
    days: dict[str, list[str]] = {}
    in_days = False
    for seg in segs[1:]:
        lhs, sep, rhs = seg.partition(":")
        key = lhs.strip().lower()
        if sep and key in _DAY_KEYS:
            in_days = True
            _add_day_codes(number, lhs.strip(), rhs, days, errors)
        elif sep and not in_days and key in ("phase", "focus"):
            if key == "phase" and not meta:
                meta.append(rhs.strip())
            else:
                if not meta:
                    meta.append("")
                meta.append(rhs.strip())
        elif sep and not in_days and len(meta) < 2 and not _looks_like_day_typo(lhs, rhs):
            meta.append(seg)
        elif sep:
            in_days = True
            _add_day_codes(number, lhs.strip(), rhs, days, errors)
        elif not in_days:
            meta.append(seg)
        else:
            errors.append(_error(number, seg, None, "day segment must be 'Day: code' (e.g. 'Tue: I 6x1k r2'')"))
    phase = meta[0] if len(meta) >= 1 else ""
    focus = " · ".join(m_item for m_item in meta[1:] if m_item) if len(meta) >= 2 else ""
    return {"week": number, "phase": phase.strip(), "focus": focus.strip(),
            "days": {d: days[d] for d in DAYS if d in days}}


def _week(raw: Any, errors: list[dict]) -> Optional[dict]:
    if isinstance(raw, str):
        return _parse_week_string(raw, errors)
    if not isinstance(raw, dict):
        errors.append(_error(None, None, None, "each week must be a 'W1 | phase | ...' string or an object"))
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
        _add_day_codes(number, key, value, days, errors)
    return {"week": number, "phase": str(raw.get("phase") or "").strip(), "focus": str(raw.get("focus") or "").strip(),
            "days": {d: days[d] for d in DAYS if d in days}}


def normalize_plan(plan: Any, defaults: Optional[dict] = None) -> tuple[dict, list[dict]]:
    """(spec, errors): the coach's plan with readable week numbers and day keys (codes kept as written).

    `defaults` fills start_date / end_date / mode / title when the plan leaves them out (e.g. from fetch_plan_context).
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
    end = parse_date(plan.get("end_date") or defaults.get("end_date"))
    mode = str(plan.get("mode") or defaults.get("mode") or "new").strip().lower()
    if mode not in MODES:
        errors.append(_error(None, None, None, "mode must be 'new' or 'overhaul'"))
    if not start:
        errors.append(_error(None, None, None, "start_date (YYYY-MM-DD) is missing"))
    elif mode == "new" and start.weekday() >= 5:
        weekend_only = (
            len(weeks) == 1 and 1 in weeks and bool(weeks[1]["days"])
            and set(weeks[1]["days"]) <= {"Sat", "Sun"}
        )
        if not weekend_only:
            start = snap_new_block_start(start, end)
    spec: dict[str, Any] = {
        "start_date": iso_date(start) if start else None,
        "mode": mode,
        "title": str(plan.get("title") or defaults.get("title") or "").strip(),
        "weeks": [weeks[n] for n in sorted(weeks)],
    }
    if end and start and end >= start:
        spec["end_date"] = iso_date(end)
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


def end_cutoff_date(spec: dict) -> Optional[date]:
    """Optional last day when `spec['end_date']` falls mid-week inside the plan's final week."""
    end = parse_date(spec.get("end_date"))
    if not end or not spec.get("start_date") or not spec.get("weeks"):
        return None
    last_mon = week_monday(spec, max(w["week"] for w in spec["weeks"]))
    return end if last_mon <= end < last_mon + timedelta(days=6) else None


def effective_plan_end(spec: dict) -> date:
    """Last active calendar day of `spec` (final Sunday, or earlier `end_date` within that week)."""
    return end_cutoff_date(spec) or plan_window(spec)[1]


def cutoff_date(spec: dict, today: date) -> date:
    """The first day the plan may change: today, or a start_date later than today."""
    start = parse_date(spec.get("start_date"))
    return max(today, start) if start else today


def _time_double_day(day_sessions: list[dict], times: Optional[dict]) -> None:
    """On a day with a Run and a Strength session, untimed sessions of those sports get `times[sport]`
    (the runner's preferred order); explicit 'am' / 'mid' / 'pm' codes are kept."""
    sports = {s["sport"] for s in day_sessions}
    if not times or not {"Run", "Strength"} <= sports:
        return
    for s in day_sessions:
        if not s.get("time") and times.get(s["sport"]):
            s["time"] = times[s["sport"]]


def expand_week(
    week: dict,
    monday: date,
    zones: dict,
    cutoff: date,
    times: Optional[dict] = None,
    end_cutoff: Optional[date] = None,
) -> dict:
    """{week, start, phase, focus, sessions, rest (ISO dates), days (ISO dates in scope), skipped, errors}.

    Each session (session_codes.build_session) gets its ISO `date`, `day` label and `write_date` (with the
    time of day for 'am' / 'mid' / 'pm' codes, or from `times` {sport: 'HH:MM'} on a run + strength double
    day); sessions keep the order of the spec within a day.
    """
    sessions: list[dict] = []
    rest: list[str] = []
    errors: list[dict] = []
    skipped = 0
    for offset, label in enumerate(DAYS):
        day = monday + timedelta(days=offset)
        day_sessions: list[dict] = []
        out_of_window = day < cutoff or (end_cutoff is not None and day > end_cutoff)
        for code in week["days"].get(label, []):
            if out_of_window:
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
            day_sessions.append({**session, "date": iso_date(day), "day": label})
        _time_double_day(day_sessions, times)
        for s in day_sessions:
            s["write_date"] = f"{s['date']}T{s['time']}:00" if s.get("time") else s["date"]
        sessions.extend(day_sessions)
    in_scope = [
        iso_date(d)
        for i in range(7)
        if (d := monday + timedelta(days=i)) >= cutoff and (end_cutoff is None or d <= end_cutoff)
    ]
    return {"week": week["week"], "start": iso_date(monday), "phase": week.get("phase") or "",
            "focus": week.get("focus") or "", "sessions": sessions, "rest": rest, "days": in_scope,
            "skipped": skipped, "errors": errors}


def expand_plan(spec: dict, zones: dict, today: date) -> tuple[list[dict], list[dict]]:
    """(expanded weeks, errors over the whole plan). Double days are timed with `spec["times"]`."""
    cutoff = cutoff_date(spec, today)
    end_cutoff = end_cutoff_date(spec)
    weeks = [expand_week(w, week_monday(spec, w["week"]), zones, cutoff, spec.get("times"), end_cutoff)
             for w in spec.get("weeks") or []]
    return weeks, [e for w in weeks for e in w["errors"]]
