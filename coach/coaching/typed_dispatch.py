"""Typed-prompt pre-dispatch (zero-LLM routing for unambiguous report, schedule & workout prompts).

Supports both short prompts and rich multi-sentence / multi-paragraph briefs using strict lead grammar
plus intent-based tail guards (no arbitrary word-count caps). Action, mutation, event, comparison, or
multi-tool prompts return `None` and stay on normal LLM routing.
"""

import calendar
from datetime import date, timedelta
import re
from typing import Any, Optional

from ...features.schedule_lookup.get_schedule_tool import MAX_SCHEDULE_DAYS
from ...shared.dates import get_today_date, iso_date, monday_of

BIKE_WORKOUT_SKILL = "bike-workout-analysis"
RUN_WORKOUT_SKILL = "workout-analysis"
SCHEDULE_LOOKUP = "schedule-lookup"

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_NAME_PATTERN = (
    r"(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|"
    r"jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)"
)
_DATE_EXPR_PATTERN = (
    rf"(?:today|\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|{_MONTH_NAME_PATTERN}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:[,\s]+\d{{4}})?"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?(?:\s+of)?\s+{_MONTH_NAME_PATTERN}\.?(?:[,\s]+\d{{4}})?)"
)
_CHECKIN_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|let(?:'s|’s|s)\s+)?"
    r"(?:"
    r"(?:do\s+(?:a\s+|my\s+)?)?(?:weekly\s+)?check[- ]?in(?:\s+report)?"
    r"|checking\s+in"
    r"|(?:do\s+(?:a\s+|my\s+)?)?weekly\s+review"
    r"|how\s+(?:was|did|is)\s+my\s+(?:training\s+|running\s+)?week(?:\s+go|\s+going)?"
    r"|am\s+i\s+on\s+track(?:\s+this\s+week)?"
    r")$",
    re.IGNORECASE,
)
_AUDIT_LEAD_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|let(?:'s|’s|s)\s+)?"
    r"(?P<verb>audit|assess|look\s+at|check|review)\b\s+(?P<body>.+)$",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    rf"^(?:(?P<prefix>.*?)\s+)?(?:"
    rf"from\s+(?P<d1>.+?)\s+(?:to|until|through|till|up\s+to|[-–—])\s+(?P<d2>.+?)"
    rf"|between\s+(?P<b1>.+?)\s+and\s+(?P<b2>.+?)"
    rf"|(?:for\s+)?(?P<r1>{_DATE_EXPR_PATTERN})\s*(?:to|until|through|till|up\s+to|[-–—])\s*(?P<r2>{_DATE_EXPR_PATTERN})"
    rf")$",
    re.IGNORECASE,
)
_UNTIL_RE = re.compile(
    rf"^(?:(?P<prefix>.*?)\s+)?(?:until|through|till|up\s+to)\s+(?P<d2>{_DATE_EXPR_PATTERN})$",
    re.IGNORECASE,
)
_MONTH_WINDOW_RE = re.compile(
    rf"^(?:(?P<prefix>.*?)\s+)?(?:"
    rf"(?:for\s+|in\s+)?(?P<rel>this|next)\s+month"
    rf"|(?:for|in)\s+(?P<m>{_MONTH_NAME_PATTERN})(?:\s+(?P<y>\d{{4}}))?"
    rf")$",
    re.IGNORECASE,
)
_NEXT_WEEKS_RE = re.compile(
    r"^(?:(?:(?:for|over)\s+)?(?:the\s+)?|(?P<prefix>.+?)\s+(?:(?:for|over)\s+)?(?:the\s+)?)next\s+(?P<n>\d{1,2})\s+weeks?$",
    re.IGNORECASE,
)
_NEXT_MONTHS_RE = re.compile(
    r"^(?:(?:(?:for|over)\s+)?(?:the\s+)?|(?P<prefix>.+?)\s+(?:(?:for|over)\s+)?(?:the\s+)?)next\s+(?P<n>\d{1,2})\s+months?$",
    re.IGNORECASE,
)
_SCHEDULE_LEAD_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|let(?:'s|’s|s)\s+)?(?:"
    r"(?:pull\s+up|peek\s+at|show(?:\s+me)?)\b\s+(?P<vbody>.+)"
    r"|(?:look\s+at|check)\s+(?P<cbody>(?:my\s+|the\s+|this\s+|next\s+|current\s+|upcoming\s+)?"
    r"(?:training\s+|running\s+)?(?:schedule|calendar|agenda|week|runs|workouts|sessions)\b.*)"
    r"|what(?:'s|’s|\s+is)\s+on\s+(?:my\s+)?(?:training\s+|running\s+)?(?:schedule|calendar|agenda)(?:\s+(?P<qbody>.+))?"
    r"|what\s+(?:runs|workouts|sessions)\s+(?:do\s+i\s+have|are\s+(?:on|planned|scheduled))"
    r"(?:\s+on\s+(?:my\s+)?(?:schedule|calendar|agenda))?(?:\s+(?P<wbody>.+))?"
    r"|(?:my\s+)?(?:training\s+|running\s+)?(?:schedule|calendar|agenda)\s+(?P<nbody>.+)"
    r")$",
    re.IGNORECASE,
)
_WEEK_OF_RE = re.compile(r"^(?:(?P<prefix>.*?)\s+)?(?:for\s+)?(?:the\s+)?week\s+of\s+(?P<wday>.+)$", re.IGNORECASE)
_NEXT_WEEK_RE = re.compile(
    r"(?:(?:my|the|training|running|schedule|calendar|agenda|runs|workouts|sessions|for)\s+)*next\s+week"
)

_UNDATED_AUDIT_WORDS = frozenset({
    "my", "the", "current", "upcoming", "training", "running", "plan", "schedule", "calendar",
})
_UNDATED_AUDIT_TARGETS = frozenset({"plan", "schedule", "calendar"})
_BLOCK_AUDIT_NOUNS = frozenset({"block", "plan", "build", "prep", "cycle", "phase"})
_DATED_AUDIT_TARGETS = _UNDATED_AUDIT_TARGETS | _BLOCK_AUDIT_NOUNS | frozenset({"weeks", "training"})
MIN_INSPECT_AUDIT_DAYS = 21

_SCHEDULE_WORDS = frozenset({
    "my", "the", "this", "current", "upcoming", "training", "running",
    "schedule", "calendar", "agenda", "week", "runs", "workouts", "sessions", "for",
})
_SCHEDULE_TARGETS = frozenset({"schedule", "calendar", "agenda", "week", "runs", "workouts", "sessions"})

_CALENDAR_OBJ = (
    r"(?:my|the|a|an|this|that|it|today|tomorrow|next|"
    r"s&c|strength|run|ride|bike|tempo|intervals?|workout|session|"
    r"(?:mon|tue(?:s)?|wed(?:nes)?|thu(?:rs)?|fri|sat(?:ur)?|sun)(?:day)?)"
)
_HAS_ACTION_OR_EVENT_RE = re.compile(
    r"\b(?:"
    r"stag(?:e|ed|ing)|mov(?:e|ed|ing)|swap(?:ped|ping)?|shift(?:ed|ing)?|"
    rf"push(?:ed|ing)?\s+(?:back|out|{_CALENDAR_OBJ})|"
    r"reschedul\w*|schedule\s+(?:a|an|the)|chang(?:e|ed|ing)|updat(?:e|ed|ing)|edit(?:ed|ing)?|"
    rf"modif(?:y|ied|ying)|replac(?:e|ed|ing)|fix(?:ed|ing)?\s+{_CALENDAR_OBJ}|delet(?:e|ed|ing)|remov(?:e|ed|ing)|drop(?:ped|ping)?\s+{_CALENDAR_OBJ}|"
    r"cancel\w*|skip(?:ped|ping)?|add(?:ed|ing)?|creat(?:e|ed|ing)|insert(?:ed|ing)?|"
    r"appl(?:y|ied|ying)|rebuild\w*|build(?:ing)?\s+(?:a|an|me|my|the|out|new|it)|overhaul(?:ed|ing)?|adjust(?:ed|ing)?|"
    r"rework\w*|redesign\w*|rewrit\w*|new\s+(?:training\s+)?plan|"
    r"bump(?:ed|ing)?|cut(?:ting)?|trim(?:med|ming)?|shorten(?:ed|ing)?|extend(?:ed|ing)?|lengthen(?:ed|ing)?|"
    r"dial(?:ed|ing)?\s+back|scale(?:d|ing)?\s+back|back(?:ed|ing)?\s+off|take\s+(?:a\s+)?rest|"
    r"turn\s+\w+\s+into|make\s+(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|today|tomorrow)\b|"
    r"weather|forecast|rain\w*|wind\w*|heat|humid\w*|temperature|"
    r"injur\w*|hurt\w*|pain\w*|niggle\w*|sore\w*|ach(?:e|es|ing)|"
    r"strain\w*|sprain\w*|tweak\w*|tend[io]n\w*|pulled\s+(?:my|a|the)|"
    r"sick\w*|ill|illness|flu|cold|fever|covid|"
    r"raced|finished\s+(?:my|the)\s+race|new\s+goal"
    r")\b",
    re.IGNORECASE,
)
_OTHER_SKILL_DOMAIN_RE = re.compile(
    r"\b(?:nutrition|fuel\w*|carb\w*|hydrat\w*|sodium|gel|gels)\b",
    re.IGNORECASE,
)
_TAIL_OTHER_REPORT_RE = re.compile(
    r"\b(?:"
    r"check[- ]?in|audit"
    r"|(?:analy[sz]e|review)\s+(?:my\s+|the\s+|today(?:'s|’s)?\s+|yesterday(?:'s|’s)?\s+)?"
    r"(?:run|ride|bike|cycling|workout|session|activity)"
    r"|yesterday(?:'s|’s)?\s+(?:run|ride|bike|workout|session)"
    r"|(?:pull\s+up|show\s+me)\s+(?:my\s+)?(?:schedule|calendar|agenda)"
    r")\b",
    re.IGNORECASE,
)
_TAIL_WINDOW_HINT_RE = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|(?:last|past|next)\s+\d{{1,2}}\s+(?:weeks?|months?)"
    rf"|(?:this|next)\s+month\b"
    rf"|{_MONTH_NAME_PATTERN}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?(?:\s+of)?\s+{_MONTH_NAME_PATTERN}\b)",
    re.IGNORECASE,
)
_WORKOUT_COMPARE_RE = re.compile(
    r"\b(?:compar(?:e|ed|ing|ison)|versus|vs\.?|last\s+week(?:'s|’s)?|"
    r"previous\s+(?:run|ride|bike|workout|session))\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?:[.!?;]+(?:\s+|$)|\n+|\s+[—–]\s+)")
_MONTH_DOT_RE = re.compile(
    r"\b(jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\.(?=\s+\d)",
    re.IGNORECASE,
)
_ANALYZE_LEAD_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|let(?:'s|’s|s)\s+)?"
    r"(?:"
    r"(?P<averb>analy[sz]e|review)\b\s*(?P<rest>.+)"
    r"|(?P<lverb>look\s+at|check)\b\s+(?P<lrest>.+)"
    r"|how\s+(?:was|did)\s+(?P<hrest>.+?)(?:\s+go)?"
    r")$",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTH_DAY_RE = re.compile(
    r"\b(?P<m>[a-z]{3,9})\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?:[,\s]+(?P<y>\d{4}))?\b",
    re.IGNORECASE,
)
_DAY_MONTH_RE = re.compile(
    r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+(?P<m>[a-z]{3,9})\.?(?:[,\s]+(?P<y>\d{4}))?\b",
    re.IGNORECASE,
)
_DISTANCE_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?(?:k|km|mi|m)$", re.IGNORECASE)
_RUN_WORDS = frozenset({"run", "running", "jog"})
_BIKE_WORDS = frozenset({"bike", "biking", "ride", "cycling", "spin", "zwift", "trainer"})
_WORKOUT_NOUNS = _RUN_WORDS | _BIKE_WORDS | frozenset({"workout", "session", "activity"})
_WORKOUT_SKILLS = frozenset({RUN_WORKOUT_SKILL, BIKE_WORKOUT_SKILL})
# Intentionally excludes "race" (post-race goal transitions stay unguarded) and "goal"/"plan"/"block".
_ALLOWED_FILLER = frozenset({
    "my", "the", "a", "an", "of", "on", "from", "for", "today", "todays",
    "yesterday", "yesterdays", "st", "nd", "rd", "th",
    "indoor", "outdoor", "morning", "evening", "afternoon",
    "easy", "recovery", "tempo", "threshold", "interval", "intervals",
    "long", "marathon", "steady", "aerobic", "base", "brick",
    "hill", "hills", "strides", "track", "treadmill",
})


def has_action_or_event_intent(text: Optional[str]) -> bool:
    """True when `text` expresses mutation, staging, plan-building, weather, nutrition, or race/injury/goal intent."""
    if not text:
        return False
    return bool(_HAS_ACTION_OR_EVENT_RE.search(text) or _OTHER_SKILL_DOMAIN_RE.search(text))


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.split(r"[\s,]+", text) if t]


def _resolve_month_day(month_str: str, day_str: str, year_str: Optional[str], today: date) -> Optional[str]:
    month = _MONTHS.get(month_str.lower())
    if not month:
        return None
    day = int(day_str)
    year = int(year_str) if year_str else today.year
    try:
        parsed = date(year, month, day)
        if not year_str and parsed > today:
            parsed = date(today.year - 1, month, day)
        return iso_date(parsed)
    except ValueError:
        return None


def _parse_window_date(raw: str, today: date, *, after: Optional[date] = None) -> Optional[date]:
    """Parses a single window boundary (`YYYY-MM-DD`, `Nov 30th`, `30 Nov`) with forward year rollover."""
    s = raw.strip(" ,.")
    if s.lower() == "today":
        return today
    if _ISO_DATE_RE.fullmatch(s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    for regex in (_MONTH_DAY_RE, _DAY_MONTH_RE):
        dm = regex.fullmatch(s)
        if not dm:
            continue
        month = _MONTHS.get(dm.group("m").lower())
        if not month:
            return None
        day = int(dm.group("d"))
        year_str = dm.group("y")
        try:
            if year_str:
                return date(int(year_str), month, day)
            if after is not None:
                candidate = date(after.year, month, day)
                return date(after.year + 1, month, day) if candidate < after else candidate
            candidate = date(today.year, month, day)
            if candidate < today - timedelta(days=60):
                return date(today.year + 1, month, day)
            if candidate > today + timedelta(days=305):
                return date(today.year - 1, month, day)
            return candidate
        except ValueError:
            return None
    return None


def _valid_prefix(
    prefix: str,
    *,
    targets: frozenset[str],
    allowed_words: Optional[frozenset[str]] = None,
    max_prefix_tokens: Optional[int] = None,
) -> bool:
    if not prefix:
        return True
    p_tokens = _tokens(prefix)
    if max_prefix_tokens is not None and len(p_tokens) > max_prefix_tokens:
        return False
    if allowed_words is not None and any(t not in allowed_words for t in p_tokens):
        return False
    return any(t in targets for t in p_tokens)


def _parse_date_range(
    body: str,
    today: date,
    *,
    max_days: int,
    targets: frozenset[str],
    allowed_words: Optional[frozenset[str]] = None,
    max_prefix_tokens: Optional[int] = None,
) -> Optional[tuple[date, date]]:
    """Shared parser for `from..to`, `between..and`, bare `<d1> to/- <d2>`, `until/through <d2>`, and month windows."""
    rm = _RANGE_RE.match(body)
    if rm:
        start = _parse_window_date(rm.group("d1") or rm.group("b1") or rm.group("r1") or "", today)
        end = _parse_window_date(rm.group("d2") or rm.group("b2") or rm.group("r2") or "", today, after=start) if start else None
        prefix = (rm.group("prefix") or "").strip()
        if (
            start
            and end
            and 0 <= (end - start).days <= max_days
            and _valid_prefix(prefix, targets=targets, allowed_words=allowed_words, max_prefix_tokens=max_prefix_tokens)
        ):
            return start, end

    um = _UNTIL_RE.match(body)
    if um:
        end = _parse_window_date(um.group("d2") or "", today, after=today)
        prefix = (um.group("prefix") or "").strip()
        if (
            end
            and 0 <= (end - today).days <= max_days
            and (not prefix or _valid_prefix(prefix, targets=targets, allowed_words=allowed_words, max_prefix_tokens=max_prefix_tokens))
        ):
            return today, end

    mm = _MONTH_WINDOW_RE.match(body)
    if mm:
        prefix = (mm.group("prefix") or "").strip()
        if not prefix or _valid_prefix(prefix, targets=targets, allowed_words=allowed_words, max_prefix_tokens=max_prefix_tokens):
            if mm.group("rel"):
                if mm.group("rel").lower() == "this":
                    year, month = today.year, today.month
                else:
                    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
            else:
                month = _MONTHS[mm.group("m").lower()]
                if mm.group("y"):
                    year = int(mm.group("y"))
                else:
                    year = today.year + 1 if month < today.month - 1 else today.year
            start = date(year, month, 1)
            end = date(year, month, calendar.monthrange(year, month)[1])
            if 0 <= (end - start).days <= max_days:
                return start, end
    return None


def _parse_next_weeks(
    body: str, *, max_weeks: int, allowed_words: frozenset[str], targets: frozenset[str]
) -> Optional[int]:
    """Shared parser for `[prefix] next N weeks`."""
    nm = _NEXT_WEEKS_RE.match(body)
    if not nm:
        return None
    weeks = int(nm.group("n"))
    p_tokens = _tokens((nm.group("prefix") or "").strip())
    if not (1 <= weeks <= max_weeks) or any(t not in allowed_words for t in p_tokens):
        return None
    if p_tokens and not any(t in targets for t in p_tokens):
        return None
    return weeks


def _add_months(d: date, months: int) -> date:
    """Adds calendar months to `d`, clamping day-of-month to the target month's length."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _parse_next_months(
    body: str, *, max_months: int, allowed_words: frozenset[str], targets: frozenset[str]
) -> Optional[int]:
    """Parser for `[prefix] next N months`."""
    nm = _NEXT_MONTHS_RE.match(body)
    if not nm:
        return None
    months = int(nm.group("n"))
    p_tokens = _tokens((nm.group("prefix") or "").strip())
    if not (1 <= months <= max_months) or any(t not in allowed_words for t in p_tokens):
        return None
    if p_tokens and not any(t in targets for t in p_tokens):
        return None
    return months


def _has_extra_conjunction(body: str, *, extra_words: str = "") -> bool:
    """True when `body` contains multi-clause connectors outside `between <d1> and <d2>`."""
    rm = _RANGE_RE.match(body)
    parts = (
        [rm.group("prefix") or "", rm.group("b1"), rm.group("b2")]
        if rm and rm.group("b1") is not None
        else [body]
    )
    pat = rf"\b(?:and|also|plus|then{f'|{extra_words}' if extra_words else ''})\b"
    return any(re.search(pat, p, re.IGNORECASE) for p in parts if p)


def _infer_typed_audit(lead: str, today: date) -> Optional[dict[str, Any]]:
    if lead.lower() == "plan audit":
        return {"skill": "plan-audit", "args": {}}
    m = _AUDIT_LEAD_RE.match(lead)
    if not m:
        return None
    verb = re.sub(r"\s+", " ", m.group("verb").strip()).lower()
    body = m.group("body").strip()
    if _has_extra_conjunction(body):
        return None

    if verb not in ("audit", "assess"):
        date_range = _parse_date_range(
            body, today, max_days=366, targets=_BLOCK_AUDIT_NOUNS, max_prefix_tokens=6
        )
        if date_range and (date_range[1] - date_range[0]).days >= MIN_INSPECT_AUDIT_DAYS:
            start, end = date_range
            return {"skill": "plan-audit", "args": {"start_date": iso_date(start), "end_date": iso_date(end)}}
        return None

    date_range = _parse_date_range(
        body, today, max_days=366, targets=_DATED_AUDIT_TARGETS, max_prefix_tokens=6
    )
    if date_range:
        start, end = date_range
        return {"skill": "plan-audit", "args": {"start_date": iso_date(start), "end_date": iso_date(end)}}

    weeks = _parse_next_weeks(
        body, max_weeks=26, allowed_words=_UNDATED_AUDIT_WORDS, targets=_UNDATED_AUDIT_TARGETS
    )
    if weeks is not None:
        return {
            "skill": "plan-audit",
            "args": {"start_date": iso_date(today), "end_date": iso_date(today + timedelta(weeks=weeks))},
        }

    months = _parse_next_months(
        body,
        max_months=6,
        allowed_words=_UNDATED_AUDIT_WORDS | _DATED_AUDIT_TARGETS,
        targets=_DATED_AUDIT_TARGETS,
    )
    if months is not None:
        return {
            "skill": "plan-audit",
            "args": {"start_date": iso_date(today), "end_date": iso_date(_add_months(today, months))},
        }

    tokens = _tokens(body)
    if tokens and all(t in _UNDATED_AUDIT_WORDS for t in tokens) and any(t in _UNDATED_AUDIT_TARGETS for t in tokens):
        return {"skill": "plan-audit", "args": {}}
    return None


def _infer_typed_schedule(lead: str, today: date) -> Optional[dict[str, Any]]:
    m = _SCHEDULE_LEAD_RE.match(lead)
    if not m:
        return None
    if m.group("wbody") is not None:
        raw_body = m.group("wbody").strip()
        body = f"runs {raw_body}" if raw_body else "runs"
    elif m.group("qbody") is not None or re.match(
        r"^(?:please\s+|can\s+you\s+|could\s+you\s+|let(?:'s|’s|s)\s+)?what\b", lead, re.IGNORECASE
    ):
        raw_body = (m.group("qbody") or "").strip()
        if not raw_body:
            return {"skill": SCHEDULE_LOOKUP, "args": {}}
        body = f"schedule {raw_body}"
    elif m.group("nbody") is not None:
        body = f"schedule {m.group('nbody').strip()}"
    elif m.group("cbody") is not None:
        body = m.group("cbody").strip()
    else:
        body = m.group("vbody").strip()

    if _has_extra_conjunction(body, extra_words=r"audit|check[- ]?in"):
        return None

    date_range = _parse_date_range(
        body, today, max_days=MAX_SCHEDULE_DAYS - 1, targets=_SCHEDULE_TARGETS, allowed_words=_SCHEDULE_WORDS
    )
    if date_range:
        start, end = date_range
        return {"skill": SCHEDULE_LOOKUP, "args": {"start_date": iso_date(start), "end_date": iso_date(end)}}

    wm = _WEEK_OF_RE.match(body)
    if wm:
        prefix = (wm.group("prefix") or "").strip()
        if prefix and any(t not in _SCHEDULE_WORDS for t in _tokens(prefix)):
            return None
        anchor = _parse_window_date(wm.group("wday"), today)
        if not anchor:
            return None
        mon = monday_of(anchor)
        return {"skill": SCHEDULE_LOOKUP, "args": {"start_date": iso_date(mon), "end_date": iso_date(mon + timedelta(days=6))}}

    weeks = _parse_next_weeks(
        body, max_weeks=6, allowed_words=_SCHEDULE_WORDS, targets=_SCHEDULE_TARGETS
    )
    if weeks is not None:
        start = monday_of(today)
        end = min(today + timedelta(weeks=weeks), start + timedelta(days=MAX_SCHEDULE_DAYS - 1))
        return {"skill": SCHEDULE_LOOKUP, "args": {"start_date": iso_date(start), "end_date": iso_date(end)}}

    norm_body = re.sub(r"\s+", " ", body.lower()).strip()
    if _NEXT_WEEK_RE.fullmatch(norm_body):
        next_mon = monday_of(today) + timedelta(days=7)
        return {
            "skill": SCHEDULE_LOOKUP,
            "args": {"start_date": iso_date(next_mon), "end_date": iso_date(next_mon + timedelta(days=6))},
        }

    tokens = _tokens(body)
    if tokens and all(t in _SCHEDULE_WORDS for t in tokens) and any(t in _SCHEDULE_TARGETS for t in tokens):
        return {"skill": SCHEDULE_LOOKUP, "args": {}}
    return None


def _infer_typed_workout(lead: str, today: date) -> Optional[dict[str, Any]]:
    norm = re.sub(r"\s+", " ", lead.strip()).lower()
    m = _ANALYZE_LEAD_RE.match(norm)
    if not m:
        return None
    raw_rest = m.group("rest") or m.group("lrest") or m.group("hrest") or ""
    requires_noun = m.group("averb") is None
    rest = raw_rest.replace("'s", " ").replace("’s", " ").strip()

    date_str: Optional[str] = None
    residual = rest
    iso_m = _ISO_DATE_RE.search(residual)
    if iso_m:
        try:
            date.fromisoformat(iso_m.group(1))
            date_str = iso_m.group(1)
            residual = (residual[:iso_m.start()] + " " + residual[iso_m.end():]).strip()
        except ValueError:
            return None
    else:
        for regex in (_MONTH_DAY_RE, _DAY_MONTH_RE):
            dm = regex.search(residual)
            if dm and dm.group("m").lower() in _MONTHS:
                resolved = _resolve_month_day(dm.group("m"), dm.group("d"), dm.group("y"), today)
                if not resolved:
                    return None
                date_str = resolved
                residual = (residual[:dm.start()] + " " + residual[dm.end():]).strip()
                break

    tokens = _tokens(residual)
    if any(t in ("today", "todays") for t in tokens):
        if date_str is not None:
            return None
        date_str = "today"
    elif any(t in ("yesterday", "yesterdays") for t in tokens):
        if date_str is not None:
            return None
        date_str = iso_date(today - timedelta(days=1))

    # Every remaining token must be a known workout noun, distance, or allowed filler word; any extra clause
    # falls back to normal LLM routing.
    if any(
        t not in _WORKOUT_NOUNS and t not in _ALLOWED_FILLER and not _DISTANCE_TOKEN_RE.fullmatch(t)
        for t in tokens
    ):
        return None
    has_workout_noun = any(t in _WORKOUT_NOUNS for t in tokens)
    if requires_noun and not has_workout_noun:
        return None
    if not has_workout_noun and date_str is None:
        return None

    has_bike = any(t in _BIKE_WORDS for t in tokens)
    has_run = any(t in _RUN_WORDS for t in tokens)
    if has_bike and has_run:
        return None
    args: dict[str, Any] = {"date_str": date_str or "today"}
    if has_bike:
        args["sport"] = "bike"
        return {"skill": BIKE_WORKOUT_SKILL, "args": args}
    if has_run:
        args["sport"] = "run"
    return {"skill": RUN_WORKOUT_SKILL, "args": args}


def _infer_typed_lead(lead: str, today: date) -> Optional[dict[str, Any]]:
    if _CHECKIN_RE.match(lead):
        return {"skill": "check-in-report", "args": {}}
    if (audit := _infer_typed_audit(lead, today)) is not None:
        return audit
    if (sched := _infer_typed_schedule(lead, today)) is not None:
        return sched
    return _infer_typed_workout(lead, today)


def _tail_blocks_pre_dispatch(action: dict[str, Any], tail: str) -> bool:
    """True when follow-up context/questions in `tail` require another tool, comparison, or different date window."""
    if _TAIL_OTHER_REPORT_RE.search(tail):
        return True
    if action["skill"] in _WORKOUT_SKILLS:
        return bool(_WORKOUT_COMPARE_RE.search(tail) or _TAIL_WINDOW_HINT_RE.search(tail))
    return not action["args"] and bool(_TAIL_WINDOW_HINT_RE.search(tail))


def infer_typed_quick_action(text: Optional[str], today: Optional[date] = None) -> Optional[dict[str, Any]]:
    """Infers a deterministic action for unambiguous typed report, schedule, or workout prompts (None otherwise)."""
    cleaned = (text or "").strip()
    if not cleaned or has_action_or_event_intent(cleaned):
        return None
    today = today or get_today_date()

    norm_dots = _MONTH_DOT_RE.sub(r"\1", cleaned)
    sentences = [re.sub(r"\s+", " ", s).strip() for s in _SENTENCE_SPLIT_RE.split(norm_dots) if s.strip()]
    if not sentences:
        return None
    action = _infer_typed_lead(sentences[0], today)
    if action is None:
        return None
    tail = " ".join(sentences[1:]).strip()
    if tail and _tail_blocks_pre_dispatch(action, tail):
        return None
    return action
