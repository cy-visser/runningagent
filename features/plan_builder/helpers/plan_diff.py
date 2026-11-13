"""Diff of a planned week against the TrainingPeaks calendar, per day and per sport (pure code).

Managed sports are Run, Strength and Bike. Per day and sport, planned sessions are matched to the planned
(not completed) workouts of that sport (by time of day, then title, then order):
- keep: the workout already is the planned session (same title and totals): nothing is written;
- update: the workout is rewritten in place (its workout_id is kept);
- create: no workout left to match;
- delete: an unmatched workout of a managed sport, in overhaul mode or on a REST day.
Never touched: completed workouts, calendar notes, and other sports (Swim, Walk, ...) unless the spec has an
X session of that sport on that day (then that sport is managed on that day; deleted only in overhaul).
"""

from typing import Any, Optional

from ....shared.dates import iso_date, parse_date, parse_iso_timestamp
from ....shared.sports import BIKE_SPORTS, NON_TRAINING_SPORTS, RUN_SPORTS, STRENGTH_SPORTS, is_quality_title
from ....shared.units import as_float
from ....shared.workout_status import is_workout_completed
from ....shared.workout_upsert import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, KIND_WORKOUT

ACTION_KEEP = "keep"
DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MANAGED_SPORTS = ("Run", "Strength", "Bike")
SPORT_ORDER = {"Run": 0, "Bike": 1, "Strength": 2}
QUALITY_KINDS = frozenset({"T", "I", "RP", "M", "P", "H", "RACE"})
DISTANCE_TOL_KM = 0.1
DURATION_TOL_MIN = 1.5
# Row fields shown on the web card (contract: staged_training_plan.weeks[].rows).
ROW_FIELDS = ("date", "day", "sport", "category", "action", "title", "code", "distance_km", "duration_minutes",
              "tss_planned", "summary", "exercises", "load", "time")


def sport_name(raw: Any) -> str:
    """Canonical sport of a calendar workout ('running' -> 'Run', 'cycling' -> 'Bike', ...)."""
    text = str(raw or "Run").strip()
    low = text.lower()
    if low in RUN_SPORTS:
        return "Run"
    if low in BIKE_SPORTS:
        return "Bike"
    if low in STRENGTH_SPORTS:
        return "Strength"
    return text[:1].upper() + text[1:]


def session_category(sport: str, title: str = "", kind: Optional[str] = None, code: Optional[str] = None) -> str:
    """Agenda category ('easy' | 'quality' | 'bike' | 'strength' | 'other'), matching plan-audit."""
    low = str(sport or "Run").strip().lower()
    if low in BIKE_SPORTS:
        return "bike"
    if low in STRENGTH_SPORTS:
        return "strength"
    if low in RUN_SPORTS or low == "race":
        if (kind and kind.upper() in QUALITY_KINDS) or (code and "@" in code) or is_quality_title(title):
            return "quality"
        return "easy"
    return "other"


def _day(workout: dict) -> Optional[str]:
    day = parse_date(workout.get("date") or workout.get("start_time"))
    return iso_date(day) if day else None


def _minute_of_day(value: Any) -> Optional[int]:
    """Minutes after midnight of a timestamp or 'HH:MM'; None when no time of day is set (00:00)."""
    if isinstance(value, str) and len(value) == 5 and value[2] == ":":
        return int(value[:2]) * 60 + int(value[3:])
    ts = parse_iso_timestamp(value) if value and len(str(value)) > 10 else None
    minutes = ts.hour * 60 + ts.minute if ts else 0
    return minutes or None


def _existing_values(workout: dict) -> dict:
    hours = as_float(workout.get("duration_planned"))
    return {"distance_km": as_float(workout.get("distance_planned_km")),
            "duration_minutes": round(hours * 60) if hours else None,
            "tss_planned": as_float(workout.get("tss_planned"))}


def _close(a: Optional[float], b: Optional[float], tol: float) -> bool:
    if not a and not b:
        return True
    return a is not None and b is not None and abs(a - b) <= tol


def is_same(session: dict, workout: dict) -> bool:
    """The calendar workout already is the planned session (same title, distance and duration)."""
    values = _existing_values(workout)
    return (str(workout.get("title") or "").strip().casefold() == session["title"].strip().casefold()
            and _close(session.get("distance_km"), values["distance_km"], DISTANCE_TOL_KM)
            and _close(session.get("duration_minutes"), values["duration_minutes"], DURATION_TOL_MIN))


def match(planned: list[dict], existing: list[dict]) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """(pairs, unmatched planned, unmatched existing) of one day and sport."""
    todo = list(planned)
    left = sorted(existing, key=lambda w: (_minute_of_day(w.get("start_time")) or 24 * 60,
                                           str(w.get("title") or "")))
    pairs: list[tuple[dict, dict]] = []

    def take(p: dict, w: dict) -> None:
        pairs.append((p, w))
        todo[:] = [x for x in todo if x is not p]
        left[:] = [x for x in left if x is not w]

    # 1. Time of day: an 'am' / 'pm' session takes the workout nearest in time.
    for p in [p for p in todo if p.get("time")]:
        timed = [w for w in left if _minute_of_day(w.get("start_time")) is not None]
        if timed:
            target = _minute_of_day(p["time"])
            take(p, min(timed, key=lambda w: abs(_minute_of_day(w.get("start_time")) - target)))
    # 2. Same title.
    for p in list(todo):
        same = next((w for w in left if str(w.get("title") or "").strip().casefold() == p["title"].casefold()), None)
        if same:
            take(p, same)
    # 3. Order of the day (workouts by time of day, sessions in spec order).
    for p, w in list(zip(list(todo), list(left))):
        take(p, w)
    return pairs, todo, left


def _row(session: dict, action: str, workout: Optional[dict] = None) -> dict:
    row = {k: session.get(k) for k in ROW_FIELDS}
    row["category"] = session_category(session["sport"], session.get("title") or "", session.get("kind"), session.get("code"))
    row.update({"action": action, "workout_id": str(workout["id"]) if workout and workout.get("id") else None,
                "session": session})
    return row


def _delete_row(workout: dict, day: str, day_label: str) -> dict:
    sport = sport_name(workout.get("sport"))
    title = workout.get("title") or "Planned workout"
    return {"date": day, "day": day_label, "sport": sport, "category": session_category(sport, title),
            "action": ACTION_DELETE, "title": title, "code": None, **_existing_values(workout),
            "summary": None, "exercises": None, "load": None, "time": None,
            "workout_id": str(workout.get("id") or ""), "session": None}


def diff_week(week: dict, workouts: list[dict], mode: str) -> list[dict]:
    """Changes of one expanded week (plan_expand.expand_week) against the calendar `workouts`, sorted by
    date and sport. Each change: the card row fields + action, workout_id and the planned `session`."""
    by_day: dict[str, list[dict]] = {}
    for s in week["sessions"]:
        by_day.setdefault(s["date"], []).append(s)
    rest = set(week["rest"])
    changes: list[dict] = []
    for day in week["days"]:
        planned = by_day.get(day, [])
        existing = [w for w in workouts if _day(w) == day and not is_workout_completed(w)
                    and str(w.get("sport") or "Run").strip() not in NON_TRAINING_SPORTS]
        x_sports = {s["sport"] for s in planned if s["kind"] == "X"}
        sports = sorted(set(MANAGED_SPORTS) | x_sports | {s["sport"] for s in planned})
        for sport in sports:
            p_sport = [s for s in planned if s["sport"] == sport]
            e_sport = [w for w in existing if sport_name(w.get("sport")) == sport]
            pairs, new, unmatched = match(p_sport, e_sport)
            for session, workout in pairs:
                changes.append(_row(session, ACTION_KEEP if is_same(session, workout) else ACTION_UPDATE, workout))
            changes.extend(_row(s, ACTION_CREATE) for s in new)
            removable = (sport in MANAGED_SPORTS and (mode == "overhaul" or day in rest)) or (
                sport in x_sports and mode == "overhaul")
            if removable:
                changes.extend(_delete_row(w, day, DAY_LABELS[parse_date(day).weekday()]) for w in unmatched)
    changes.sort(key=lambda c: (c["date"], SPORT_ORDER.get(c["sport"], 3)))
    return changes


def counts(changes: list[dict]) -> dict[str, int]:
    return {a: sum(1 for c in changes if c["action"] == a)
            for a in (ACTION_CREATE, ACTION_UPDATE, ACTION_DELETE, ACTION_KEEP)}


def write_change(change: dict) -> Optional[dict]:
    """The shared.workout_upsert change of a diff change (None for keep)."""
    if change["action"] == ACTION_KEEP:
        return None
    if change["action"] == ACTION_DELETE:
        return {"kind": KIND_WORKOUT, "action": ACTION_DELETE, "workout_id": change["workout_id"],
                "date": change["date"], "sport": change["sport"], "title": change["title"]}
    s = change["session"]
    return {"kind": KIND_WORKOUT, "action": change["action"], "date": s["write_date"], "sport": s["sport"],
            "title": s["title"], "workout_id": change["workout_id"] if change["action"] == ACTION_UPDATE else None,
            "distance_km": s.get("distance_km"), "duration_minutes": s.get("duration_minutes"),
            "tss_planned": s.get("tss_planned"), "description": s.get("description"),
            "structured_workout": s.get("structured_workout")}
