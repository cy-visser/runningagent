"""Compact 1-line, multi-date, and week-line shorthand parser for `stage_workout_changes`.

Lets the coach stage 1 workout or 150 workouts in minimal tokens (~4-10 tokens/workout) without verbose
per-workout JSON dicts, while passing existing dict entries through unchanged.

Supported string forms:
- Single / multi-date / short range:
  * `"2027-01-05: P 4x1.2k @4:08-4:10 r2'"`
  * `"2026-12-30,2026-12-31: E 8 -strides"` (or `2026-12-30..2026-12-31: E 8`)
  * `"2027-01-05 +create: E 5 pm"` (or multiple `;`-separated codes on one day)
- Delete / Move / Note:
  * `"2027-01-29: delete strength"` | `"2027-01-29: delete note Holiday"` | `"delete id=12345"`
  * `"2026-12-25 -> 2026-12-26: run"` (optional new title after sport: `"2026-12-25 -> 2026-12-26: run Shakeout"`)
  * `"2026-12-19: note Holiday to Canary Islands | Travel day"`
- Full week line (stages an entire ISO week of sessions in one ~30-token line):
  * `"[W1 ]2026-11-30 | Tue: I 6x400 @4:18 r90\"; S 45' heavy-lower | Wed/Thu: E 6 | Sun: L 14"`
"""

from datetime import date, timedelta
import re
from typing import Any, Iterable

from ....shared.dates import iso_date, monday_of, parse_date
from ....shared.session_codes.session_codes import code_sport

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_WEEKDAY_WORD_RE = (
    r"(?:mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
)
_KNOWN_SPORTS = {
    "run": "Run", "running": "Run",
    "bike": "Bike", "cycling": "Bike", "ride": "Bike", "biking": "Bike",
    "strength": "Strength", "str": "Strength", "gym": "Strength", "s&c": "Strength", "sc": "Strength",
    "conditioning": "Strength",
    "swim": "Swim", "walk": "Walk", "crosstrain": "Crosstrain", "other": "Other",
}
_WEEK_ANCHOR_RE = re.compile(r"^(?:w\d+\s+)?(?P<d>\d{4}-\d{2}-\d{2})$", re.IGNORECASE)
_DAY_SPEC_RE = re.compile(
    r"^(?P<days>(?:mon|tue|wed|thu|fri|sat|sun)(?:\s*[/,-]\s*(?:mon|tue|wed|thu|fri|sat|sun))*)\s*:\s*(?P<rhs>.+)$",
    re.IGNORECASE,
)
_MOVE_LINE_RE = re.compile(
    r"^(?P<mv>move\s+)?(?P<from_d>\d{4}-\d{2}-\d{2})\s*(?P<sep>->|→|\bto\b)\s*"
    r"(?P<to_d>\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?)"
    r"(?:\s*:\s*(?P<rhs>.*))?$",
    re.IGNORECASE,
)
_DATED_LINE_RE = re.compile(
    rf"^(?P<lhs>(?:{_WEEKDAY_WORD_RE}\s+)?\d{{4}}-\d{{2}}-\d{{2}}[^|]*?)\s*:\s*(?P<rhs>.+)$",
    re.IGNORECASE,
)
_DELETE_ID_RE = re.compile(
    r"^(?:delete|remove|drop|clear)\s+(?:id=\[?(?P<wid1>[A-Za-z0-9_-]+)\]?|\[?(?P<wid2>[A-Za-z0-9_-]*\d[A-Za-z0-9_-]*)\]?)$",
    re.IGNORECASE,
)
_FLAG_CREATE_RE = re.compile(r"(?:^|\s)\+create\b", re.IGNORECASE)
_FLAG_NOSTRIDES_RE = re.compile(r"(?:^|\s)(?:-strides|\bnostrides\b|\bno[-_]?strides\b)", re.IGNORECASE)
MAX_EXPANDED_RANGE_DAYS = 31


def _strip_flags(text: str) -> tuple[str, bool, bool]:
    """Returns `(cleaned_text, create_flag, no_strides_flag)`."""
    create = bool(_FLAG_CREATE_RE.search(text))
    no_strides = bool(_FLAG_NOSTRIDES_RE.search(text))
    cleaned = _FLAG_CREATE_RE.sub(" ", text)
    cleaned = _FLAG_NOSTRIDES_RE.sub(" ", cleaned)
    return " ".join(cleaned.split()), create, no_strides


def _strip_weekday_affixes(token: str) -> str:
    return re.sub(
        rf"^(?:{_WEEKDAY_WORD_RE})\s+|\s*\((?:{_WEEKDAY_WORD_RE})\)$",
        "",
        token.strip(),
        flags=re.IGNORECASE,
    ).strip()


def _expand_date_lhs(lhs: str) -> tuple[list[str], bool, bool] | None:
    cleaned, create, no_strides = _strip_flags(lhs)
    out: list[str] = []
    for raw_part in (p.strip() for p in cleaned.split(",") if p.strip()):
        part = _strip_weekday_affixes(raw_part)
        if ".." in part:
            s_raw, e_raw = (_strip_weekday_affixes(x) for x in part.split("..", 1))
            s_day, e_day = parse_date(s_raw), parse_date(e_raw)
            if not s_day or not e_day or not (0 <= (e_day - s_day).days <= MAX_EXPANDED_RANGE_DAYS):
                return None
            cur = s_day
            while cur <= e_day:
                out.append(iso_date(cur))
                cur += timedelta(days=1)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?)?", part):
            if parse_date(part[:10]) is None:
                return None
            out.append(part if len(part) != 16 else f"{part}:00")
        else:
            return None
    return (out, create, no_strides) if out else None


def _expand_weekday_offsets(spec: str) -> list[int]:
    offsets: list[int] = []
    for token in re.split(r"\s*[,/]\s*", spec.strip().lower()):
        if "-" in token:
            a_str, b_str = (x.strip() for x in token.split("-", 1))
            a, b = _WEEKDAYS.get(a_str), _WEEKDAYS.get(b_str)
            if a is not None and b is not None and a <= b:
                offsets.extend(range(a, b + 1))
        elif token in _WEEKDAYS:
            offsets.append(_WEEKDAYS[token])
    return list(dict.fromkeys(offsets))


def _parse_clause_for_date(
    date_str: str,
    clause: str,
    *,
    base_create: bool,
    base_no_strides: bool,
    seen_sports: set[str],
) -> list[dict[str, Any]]:
    raw = clause.strip()
    if not raw:
        return []

    # Race event creation/update: "event A RunningRoad 21.1k Amsterdam HM | goal=1:35:00 place=10 pr=true"
    # Note: session-code "EVENT 16k @M Tilburg 10mi" carries "@<pace>" and no A/B/C priority -> stays a workout code.
    ev_m = re.match(r"^(?:tp_event|calendar_event|event)\s+(?P<body>.+)$", raw, re.IGNORECASE)
    if ev_m:
        body = ev_m.group("body").strip()
        head, _, tail = body.partition("|")
        head_tokens = head.split()
        is_calendar_event = (
            raw.lower().startswith(("tp_event ", "calendar_event "))
            or bool(tail.strip())
            or (bool(head_tokens) and head_tokens[0].upper() in ("A", "B", "C") and "@" not in head)
        )
        if is_calendar_event:
            ev_item: dict[str, Any] = {"kind": "event", "date_str": date_str[:10]}
            if base_create:
                ev_item["create"] = True
            idx = 0
            if idx < len(head_tokens) and head_tokens[idx].upper() in ("A", "B", "C"):
                ev_item["priority"] = head_tokens[idx].upper()
                idx += 1
            if idx < len(head_tokens) and head_tokens[idx].lower().startswith("running"):
                ev_item["event_type"] = head_tokens[idx]
                idx += 1
            if idx < len(head_tokens) and re.fullmatch(r"\d+(?:\.\d+)?(?:k|km|mi)", head_tokens[idx], re.IGNORECASE):
                tok = head_tokens[idx].lower()
                val = float(re.sub(r"[^0-9.]", "", tok))
                ev_item["distance_km"] = round(val * 1.609344, 2) if tok.endswith("mi") else val
                idx += 1
            name = " ".join(head_tokens[idx:]).strip()
            if name:
                ev_item["name"] = name
                ev_item["title"] = name
            for part in (p.strip() for p in tail.split() if "=" in p):
                k, _, v = part.partition("=")
                kl = k.strip().lower()
                vs = v.strip().rstrip(",;")
                if not vs:
                    continue
                is_unset = vs.lower() in ("none", "null", "n/a", "-")
                if kl in ("goal", "goal_time", "time"):
                    if not is_unset:
                        ev_item["goal_time"] = vs
                elif kl in ("place", "goal_place"):
                    if not is_unset:
                        ev_item["goal_place"] = vs
                elif kl in ("pr", "goal_pr"):
                    ev_item["goal_pr"] = vs
                elif kl in ("type", "event_type"):
                    ev_item["event_type"] = vs
                elif kl in ("atp", "atp_event_type", "race_type_duration"):
                    ev_item["race_type_duration"] = vs
                elif kl in ("dist", "distance", "distance_km"):
                    ev_item["distance_km"] = float(re.sub(r"[^0-9.]", "", vs))
                elif kl in ("priority", "prio"):
                    ev_item["priority"] = vs.upper()
                elif kl == "id":
                    ev_item["event_id"] = vs.strip("[]")
            return [ev_item]

    # Delete item: "delete/remove/drop/clear strength" | "delete note Title" | "delete event Title" | "delete id=w_1"
    del_m = re.match(r"^(?:delete|remove|drop|clear)(?:\s+(?P<body>.+))?$", raw, re.IGNORECASE)
    if del_m:
        body = (del_m.group("body") or "").strip()
        if not body:
            return [{"date_str": date_str[:10], "sport": "Run", "delete": True}]
        if body.lower().startswith("note "):
            return [{"kind": "note", "date_str": date_str[:10], "title": body[5:].strip(), "delete": True}]
        if body.lower().startswith("event"):
            ev_title = body[5:].strip()
            return [{"kind": "event", "date_str": date_str[:10], "title": ev_title, "name": ev_title, "delete": True}]
        if body.lower().startswith("id="):
            return [{"workout_id": body[3:].strip(" []"), "delete": True}]
        sport = _KNOWN_SPORTS.get(body.lower())
        if sport:
            return [{"date_str": date_str[:10], "sport": sport, "delete": True}]
        parts = body.split(None, 1)
        if len(parts) == 2 and parts[0].lower() in _KNOWN_SPORTS:
            return [{"date_str": date_str[:10], "sport": _KNOWN_SPORTS[parts[0].lower()], "title": parts[1].strip(), "delete": True}]
        return [{"date_str": date_str[:10], "title": body, "delete": True}]

    code_text, seg_create, seg_no_strides = _strip_flags(raw)
    if not code_text:
        return []
    sport = (code_sport(code_text) or "Run").lower()
    entry: dict[str, Any] = {"date_str": date_str, "code": code_text}
    if base_create or seg_create or sport in seen_sports:
        entry["create"] = True
    if base_no_strides or seg_no_strides:
        entry["strides"] = False
    seen_sports.add(sport)
    return [entry]


def _parse_rhs_for_date(date_str: str, rhs: str, *, base_create: bool = False, base_no_strides: bool = False) -> list[dict[str, Any]]:
    raw = rhs.strip()
    if not raw:
        return []

    # Note creation stays unsplit so semicolons inside note descriptions remain intact.
    note_m = re.match(r"^note\s+(?P<body>.+)$", raw, re.IGNORECASE)
    if note_m:
        body = note_m.group("body").strip()
        title, _, desc = body.partition("|")
        item: dict[str, Any] = {"kind": "note", "date_str": date_str[:10], "title": title.strip()}
        if desc.strip():
            item["description"] = desc.strip()
        return [item]

    items: list[dict[str, Any]] = []
    seen_sports: set[str] = set()
    for seg in (s.strip() for s in raw.split(";") if s.strip()):
        items.extend(
            _parse_clause_for_date(
                date_str,
                seg,
                base_create=base_create,
                base_no_strides=base_no_strides,
                seen_sports=seen_sports,
            )
        )
    return items


def _expand_week_line(line: str) -> list[dict[str, Any]] | None:
    segments = [s.strip() for s in line.split("|") if s.strip()]
    if len(segments) < 2:
        return None
    anchor_m = _WEEK_ANCHOR_RE.match(segments[0])
    if not anchor_m:
        return None
    anchor = parse_date(anchor_m.group("d"))
    if anchor is None:
        return None
    mon = monday_of(anchor)
    out: list[dict[str, Any]] = []
    saw_day = False
    for seg in segments[1:]:
        dm = _DAY_SPEC_RE.match(seg)
        if not dm:
            if not saw_day:
                continue  # optional phase / focus metadata before the first day segment
            return None
        saw_day = True
        offsets = _expand_weekday_offsets(dm.group("days"))
        if not offsets:
            return None
        for off in offsets:
            out.extend(_parse_rhs_for_date(iso_date(mon + timedelta(days=off)), dm.group("rhs")))
    return out if saw_day else None


def _clean_entry_line(raw: str) -> str:
    line = raw.strip()
    line = re.sub(r"^(?:[-*•]|\d+[.)])\s+", "", line).strip()
    while len(line) >= 2 and line[0] == line[-1] and line[0] in ("`", '"', "'"):
        line = line[1:-1].strip()
    return line


def _expand_move_line(line: str) -> dict[str, Any] | None:
    mm = _MOVE_LINE_RE.match(line)
    if not mm:
        return None
    from_d, to_d = mm.group("from_d"), mm.group("to_d")
    if parse_date(from_d) is None or parse_date(to_d[:10]) is None:
        return None
    if len(to_d) == 16:
        to_d = f"{to_d}:00"
    rhs = (mm.group("rhs") or "").strip()
    is_word_to = mm.group("sep").lower() == "to" and not mm.group("mv")
    if not rhs:
        return {"from_date_str": from_d, "date_str": to_d, "sport": "Run"}
    if rhs.lower().startswith("id="):
        wid, _, title = rhs[3:].strip().partition(" ")
        item: dict[str, Any] = {"workout_id": wid.strip("[]"), "date_str": to_d}
        if title.strip():
            item["title"] = title.strip()
        return item
    parts = rhs.split(None, 1)
    sport = _KNOWN_SPORTS.get(parts[0].lower())
    if sport:
        item = {"from_date_str": from_d, "date_str": to_d, "sport": sport}
        if len(parts) > 1 and parts[1].strip():
            item["title"] = parts[1].strip()
        return item
    if is_word_to:
        return None
    return {"from_date_str": from_d, "date_str": to_d, "sport": "Run", "title": rhs}


def expand_change_entries(entries: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Expands mixed compact string lines and legacy dict items into normalized change dicts."""
    expanded: list[dict[str, Any]] = []
    for raw in entries or []:
        if isinstance(raw, dict):
            expanded.append(raw)
            continue
        if not isinstance(raw, str):
            continue
        line = _clean_entry_line(raw)
        if not line:
            continue
        if "|" in line and (week_items := _expand_week_line(line)) is not None:
            expanded.extend(week_items)
            continue
        if (move_item := _expand_move_line(line)) is not None:
            expanded.append(move_item)
            continue
        del_id_m = _DELETE_ID_RE.match(line)
        if del_id_m:
            expanded.append({"workout_id": del_id_m.group("wid1") or del_id_m.group("wid2"), "delete": True})
            continue
        dm = _DATED_LINE_RE.match(line)
        if dm and (lhs_parsed := _expand_date_lhs(dm.group("lhs"))) is not None:
            dates, create, no_strides = lhs_parsed
            for d in dates:
                expanded.extend(_parse_rhs_for_date(d, dm.group("rhs"), base_create=create, base_no_strides=no_strides))
            continue
        # Unrecognized string: surface cleanly as a missing-builder problem rather than silently dropping.
        expanded.append({"title": line, "sport": "Run"})
    return expanded
