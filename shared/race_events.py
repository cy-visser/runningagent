"""Shared TrainingPeaks running race-event normalization, derivation, matching, and formatting."""

from __future__ import annotations

import re
from typing import Any, Optional

from .dates import iso_date, parse_date
from .goal_distance import DISTANCE_PROFILES, resolve_goal_distance
from .race_equivalents import goal_km, goal_target_s
from .race_time import parse_race_time
from .units import as_float, format_seconds_hms, to_km

RUNNING_EVENT_TYPES: tuple[str, ...] = (
    "RunningRoad",
    "RunningTrail",
    "RunningTrack",
    "RunningCrossCountry",
    "RunningOther",
)
_RUNNING_EVENT_TYPE_MAP: dict[str, str] = {
    "runningroad": "RunningRoad",
    "road": "RunningRoad",
    "running": "RunningRoad",
    "run": "RunningRoad",
    "runningtrail": "RunningTrail",
    "trail": "RunningTrail",
    "runningtrack": "RunningTrack",
    "track": "RunningTrack",
    "runningcrosscountry": "RunningCrossCountry",
    "crosscountry": "RunningCrossCountry",
    "cross country": "RunningCrossCountry",
    "xc": "RunningCrossCountry",
    "runningother": "RunningOther",
    "other": "RunningOther",
}

# Verified TrainingPeaks v6 `raceTypeDuration` enum values for Running ATP event types.
RACE_TYPE_UNDER_1H = "RunUnderOneHour"
RACE_TYPE_1_TO_2H = "RunOnetoTwoHours"
RACE_TYPE_OVER_2H = "RunOverTwoHours"
RUNNING_RACE_TYPE_DURATIONS: tuple[str, ...] = (
    RACE_TYPE_UNDER_1H,
    RACE_TYPE_1_TO_2H,
    RACE_TYPE_OVER_2H,
)
_RACE_DURATION_ALIASES: dict[str, str] = {
    "rununderonehour": RACE_TYPE_UNDER_1H,
    "0-1": RACE_TYPE_UNDER_1H,
    "0-1h": RACE_TYPE_UNDER_1H,
    "under1h": RACE_TYPE_UNDER_1H,
    "underonehour": RACE_TYPE_UNDER_1H,
    "runonetotwohours": RACE_TYPE_1_TO_2H,
    "1-2": RACE_TYPE_1_TO_2H,
    "1-2h": RACE_TYPE_1_TO_2H,
    "onetotwohours": RACE_TYPE_1_TO_2H,
    "runovertwohours": RACE_TYPE_OVER_2H,
    "2+": RACE_TYPE_OVER_2H,
    "2+h": RACE_TYPE_OVER_2H,
    "over2h": RACE_TYPE_OVER_2H,
    "overtwohours": RACE_TYPE_OVER_2H,
}

VALID_PRIORITIES: tuple[str, ...] = ("A", "B", "C")
_RUNNING_EVENT_RE = re.compile(r"run|marathon|track|trail|cross\s?country|5k|10k|half", re.IGNORECASE)
_TAG_SPLIT_RE = re.compile(r"[,;\s]+")


def has_race_tag(tags: Any) -> bool:
    """True when TrainingPeaks workout `tags` (`userTags`) explicitly includes the token `race`."""
    if not tags:
        return False
    if isinstance(tags, (list, tuple, set)):
        tokens = [str(t).strip().lower() for t in tags]
    else:
        tokens = [tok.strip().lower() for tok in _TAG_SPLIT_RE.split(str(tags)) if tok.strip()]
    return "race" in tokens


def is_running_event(event: dict[str, Any]) -> bool:
    """True when a TrainingPeaks Calendar Event represents a running event."""
    if not isinstance(event, dict):
        return False
    ev_type = str(event.get("eventType") or event.get("event_type") or "").strip()
    if not ev_type:
        return True
    if ev_type.lower().startswith("running"):
        return True
    name = str(event.get("name") or event.get("title") or "")
    return bool(_RUNNING_EVENT_RE.search(ev_type) or _RUNNING_EVENT_RE.search(name))


def event_date_iso(event: dict[str, Any]) -> Optional[str]:
    """ISO date (`YYYY-MM-DD`) of a TrainingPeaks event dict."""
    d = parse_date(event.get("eventDate") or event.get("date"))
    return iso_date(d) if d else None


def event_priority(event: dict[str, Any]) -> Optional[str]:
    """Priority (`'A' | 'B' | 'C'`) of a TrainingPeaks event dict, or None."""
    raw = str(event.get("atpPriority") or event.get("priority") or "").strip().upper()
    return raw if raw in VALID_PRIORITIES else None


def event_distance_km(event: dict[str, Any]) -> Optional[float]:
    """Event distance in km from top-level `distance`/`distanceUnits` or `goals.distance`."""
    dist = to_km(event.get("distance"), event.get("distanceUnits"))
    if dist and dist > 0:
        return round(dist, 2)
    goals = event.get("goals")
    if isinstance(goals, dict):
        gd = goals.get("distance")
        if isinstance(gd, dict) and gd.get("value") is not None:
            km = to_km(gd.get("value"), "Meters")
            if km and km > 0:
                return round(km, 2)
    return None


def event_goal_time_s(event: dict[str, Any]) -> Optional[int]:
    """Goal finish time in whole seconds from TP `goals.time.value` (decimal hours) or `goal_time`."""
    if event.get("goal_time"):
        _, secs = normalize_goal_time(event.get("goal_time"))
        if secs:
            return secs
    goals = event.get("goals")
    if isinstance(goals, dict):
        gt = goals.get("time")
        hours = as_float(gt.get("value") if isinstance(gt, dict) else gt)
        if hours and hours > 0:
            return int(round(hours * 3600.0))
    return None


def event_goal_place(event: dict[str, Any]) -> Optional[int]:
    """Integer target placement from TP `goals.place.value` or `goal_place`."""
    raw = event.get("goal_place")
    if raw is None and isinstance(event.get("goals"), dict):
        gp = event["goals"].get("place")
        raw = gp.get("value") if isinstance(gp, dict) else gp
    if raw is None or isinstance(raw, bool):
        return None
    try:
        val = int(raw)
        return val if val >= 1 else None
    except (TypeError, ValueError):
        return None


def event_goal_pr(event: dict[str, Any]) -> Optional[bool]:
    """Optional boolean PR target from TP `goals.pr.value` or `goal_pr`."""
    raw = event.get("goal_pr")
    if raw is None and isinstance(event.get("goals"), dict):
        gp = event["goals"].get("pr")
        raw = gp.get("value") if isinstance(gp, dict) else gp
    if isinstance(raw, bool):
        return raw
    return None


def normalize_running_event_type(raw: Any) -> str:
    """Canonical TP running `eventType` (defaults to `'RunningRoad'`)."""
    text = str(raw or "").strip()
    if not text:
        return "RunningRoad"
    key = re.sub(r"[^a-z]", "", text.lower())
    return _RUNNING_EVENT_TYPE_MAP.get(key, "RunningRoad")


def normalize_race_type_duration(raw: Any) -> Optional[str]:
    """Normalizes a TP `raceTypeDuration` string or shorthand (`'0-1'`, `'1-2'`, `'2+'`) to TP's exact enum."""
    text = str(raw or "").strip()
    if not text:
        return None
    key = re.sub(r"\s+", "", text.lower())
    if key in _RACE_DURATION_ALIASES:
        return _RACE_DURATION_ALIASES[key]
    if text in RUNNING_RACE_TYPE_DURATIONS:
        return text
    return None


def derive_race_type_duration(
    *,
    target_seconds: Optional[float] = None,
    distance_km: Optional[float] = None,
    goal_text: Optional[str] = None,
) -> str:
    """Derives TP's ATP `raceTypeDuration` (`RunUnderOneHour` | `RunOnetoTwoHours` | `RunOverTwoHours`)."""
    secs = as_float(target_seconds)
    if (not secs or secs <= 0) and goal_text:
        secs = goal_target_s(goal_text)
    if secs and secs > 0:
        if secs < 3600.0:
            return RACE_TYPE_UNDER_1H
        if secs < 7200.0:
            return RACE_TYPE_1_TO_2H
        return RACE_TYPE_OVER_2H

    km = as_float(distance_km)
    if (not km or km <= 0) and goal_text:
        km = goal_km(goal_text)
    if km and km > 0:
        if km <= 12.0:
            return RACE_TYPE_UNDER_1H
        if km <= 25.0:
            return RACE_TYPE_1_TO_2H
        return RACE_TYPE_OVER_2H
    return RACE_TYPE_1_TO_2H


def normalize_goal_time(raw: Any) -> tuple[Optional[str], Optional[int]]:
    """Normalizes a target race time (`'H:MM:SS'`, `'MM:SS'`, or seconds/goal string) to `(text, seconds)`."""
    if raw is None or isinstance(raw, bool):
        return None, None
    if isinstance(raw, (int, float)):
        secs = int(round(float(raw)))
        return (format_seconds_hms(secs), secs) if secs > 0 else (None, None)
    text = str(raw).strip()
    if not text:
        return None, None
    try:
        return parse_race_time(text)
    except ValueError:
        secs = goal_target_s(text)
        if secs and secs > 0:
            sec_i = int(round(secs))
            return format_seconds_hms(sec_i), sec_i
        return None, None


def _parse_optional_bool(raw: Any) -> Optional[bool]:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    low = str(raw).strip().lower()
    if low in ("true", "yes", "1", "y"):
        return True
    if low in ("false", "no", "0", "n"):
        return False
    return None


def derive_block_event(
    goal_block: Optional[dict[str, Any]],
    *,
    event_type: str = "RunningRoad",
    goal_place: Optional[int] = None,
    goal_pr: Optional[bool] = None,
) -> Optional[dict[str, Any]]:
    """Builds the default A-priority TP Running Event for a training block's target goal."""
    if not isinstance(goal_block, dict):
        return None
    day = parse_date(goal_block.get("timeline") or goal_block.get("race_date"))
    if not day:
        return None
    goal_text = str(goal_block.get("training_goal") or goal_block.get("goal") or "").strip()
    name = str(goal_block.get("race_name") or goal_text or "Goal Race").strip()
    km = goal_km(goal_text)
    label = resolve_goal_distance(goal_text)
    if not km and label in DISTANCE_PROFILES:
        km = float(DISTANCE_PROFILES[label]["km"])
    target_s = goal_target_s(goal_text)
    goal_time = format_seconds_hms(target_s) if target_s else None
    rtd = derive_race_type_duration(target_seconds=target_s, distance_km=km, goal_text=goal_text)
    return {
        "date": iso_date(day),
        "name": name,
        "event_type": normalize_running_event_type(event_type),
        "race_type_duration": rtd,
        "distance_km": round(float(km), 2) if km else None,
        "priority": "A",
        "goal_time": goal_time,
        "goal_place": int(goal_place) if goal_place is not None else None,
        "goal_pr": goal_pr if isinstance(goal_pr, bool) else None,
        "goal_finish": True,
        "description": goal_text or None,
    }


def normalize_event_spec(
    raw: dict[str, Any],
    *,
    block_goal: Optional[dict[str, Any]] = None,
    is_intermediate: Optional[bool] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Validates and normalizes a proposed TP Running Event dict; returns `(event, error_msg)`."""
    if not isinstance(raw, dict):
        return None, "event must be an object"
    day = parse_date(raw.get("date") or raw.get("date_str") or raw.get("eventDate"))
    if not day:
        return None, "event date (YYYY-MM-DD) is missing or invalid"
    day_iso = iso_date(day)

    block_day = parse_date((block_goal or {}).get("timeline") or (block_goal or {}).get("race_date"))
    block_iso = iso_date(block_day) if block_day else None
    is_block_target = bool(block_iso and day_iso == block_iso)
    if is_intermediate is None and block_iso:
        is_intermediate = day_iso != block_iso

    defaults = derive_block_event(block_goal) if is_block_target else None
    name = str(raw.get("name") or raw.get("title") or (defaults or {}).get("name") or "").strip()
    if not name:
        return None, f"event on {day_iso} is missing a name"

    raw_prio = str(raw.get("priority") or raw.get("atpPriority") or "").strip().upper()
    if not raw_prio:
        priority = "A" if is_block_target else "B"
    elif raw_prio in VALID_PRIORITIES:
        priority = raw_prio
    else:
        return None, f"event priority must be A, B, or C (got {raw_prio!r})"

    if is_intermediate and priority == "A":
        return None, (
            f"Intermediate race '{name}' on {day_iso} cannot be priority A; "
            "use priority B (key tune-up) or C (training race / controlled event)."
        )

    event_type = normalize_running_event_type(raw.get("event_type") or raw.get("eventType"))

    km = as_float(raw.get("distance_km"))
    if km is None and raw.get("distance") is not None:
        km = to_km(raw.get("distance"), raw.get("distanceUnits"))
    if km is None:
        km = goal_km(name) or (defaults or {}).get("distance_km")
    if km is not None and km <= 0:
        return None, f"event distance_km must be positive (got {km})"
    km = round(float(km), 2) if km else None

    raw_goal_time = raw.get("goal_time")
    if raw_goal_time is not None and str(raw_goal_time).strip() != "":
        goal_time, goal_secs = normalize_goal_time(raw_goal_time)
        if goal_time is None:
            return None, f"event goal_time must be H:MM:SS or MM:SS (got {raw_goal_time!r})"
    else:
        goal_time = (defaults or {}).get("goal_time")
        _, goal_secs = normalize_goal_time(goal_time) if goal_time else (None, None)

    raw_place = raw.get("goal_place")
    goal_place: Optional[int] = None
    if raw_place is not None and str(raw_place).strip() != "":
        if isinstance(raw_place, bool):
            return None, "event goal_place must be a positive integer"
        try:
            goal_place = int(raw_place)
        except (TypeError, ValueError):
            return None, f"event goal_place must be a positive integer (got {raw_place!r})"
        if goal_place < 1:
            return None, f"event goal_place must be >= 1 (got {goal_place})"

    goal_pr = _parse_optional_bool(raw.get("goal_pr"))
    if raw.get("goal_pr") is not None and goal_pr is None:
        return None, f"event goal_pr must be true or false (got {raw.get('goal_pr')!r})"

    goal_finish_val = _parse_optional_bool(raw.get("goal_finish"))
    goal_finish = True if goal_finish_val is None else goal_finish_val

    rtd = normalize_race_type_duration(
        raw.get("race_type_duration") or raw.get("raceTypeDuration") or raw.get("atp_event_type")
    )
    if not rtd:
        rtd = derive_race_type_duration(
            target_seconds=goal_secs,
            distance_km=km,
            goal_text=(block_goal or {}).get("training_goal") if is_block_target else name,
        )

    out: dict[str, Any] = {
        "date": day_iso,
        "name": name,
        "event_type": event_type,
        "race_type_duration": rtd,
        "distance_km": km,
        "priority": priority,
        "goal_time": goal_time,
        "goal_place": goal_place,
        "goal_pr": goal_pr,
        "goal_finish": goal_finish,
        "description": str(raw.get("description") or "").strip() or (defaults or {}).get("description"),
    }
    if raw.get("event_id"):
        out["event_id"] = str(raw["event_id"]).strip()
    return out, None


def match_event_for_date(
    events: list[dict[str, Any]],
    target_iso: str,
    name: str = "",
) -> Optional[dict[str, Any]]:
    """Matches an existing TP running event on `target_iso` (same name first, else single match)."""
    on_day = [ev for ev in (events or []) if is_running_event(ev) and event_date_iso(ev) == target_iso]
    if not on_day:
        return None
    needle = name.strip().casefold()
    if needle:
        exact = next((ev for ev in on_day if str(ev.get("name") or "").strip().casefold() == needle), None)
        if exact is not None:
            return exact
    return on_day[0]


def is_same_event(planned: dict[str, Any], existing: dict[str, Any]) -> bool:
    """True when an existing TP Calendar Event already matches the planned event's key fields."""
    if str(existing.get("name") or "").strip().casefold() != str(planned.get("name") or "").strip().casefold():
        return False
    if event_priority(existing) != planned.get("priority"):
        return False
    if str(existing.get("eventType") or "").strip() != str(planned.get("event_type") or "").strip():
        return False
    if planned.get("race_type_duration") and str(existing.get("raceTypeDuration") or "") != planned["race_type_duration"]:
        return False
    ex_km, pl_km = event_distance_km(existing), as_float(planned.get("distance_km"))
    if pl_km is not None and (ex_km is None or abs(ex_km - pl_km) > 0.15):
        return False
    _, pl_s = normalize_goal_time(planned.get("goal_time"))
    ex_s = event_goal_time_s(existing)
    if pl_s is not None and (ex_s is None or abs(ex_s - pl_s) > 30):
        return False
    if planned.get("goal_place") is not None and event_goal_place(existing) != planned["goal_place"]:
        return False
    if planned.get("goal_pr") is not None and event_goal_pr(existing) != planned["goal_pr"]:
        return False
    return True


def event_snapshot(existing: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Compact snapshot of an existing TP Event for staged diff cards."""
    if not isinstance(existing, dict):
        return None
    gt_s = event_goal_time_s(existing)
    return {
        "title": existing.get("name") or "Event",
        "date": event_date_iso(existing),
        "event_type": existing.get("eventType"),
        "priority": event_priority(existing),
        "race_type_duration": existing.get("raceTypeDuration"),
        "distance_km": event_distance_km(existing),
        "goal_time": format_seconds_hms(gt_s) if gt_s else None,
        "goal_place": event_goal_place(existing),
        "goal_pr": event_goal_pr(existing),
    }


def format_event_summary(ev: dict[str, Any]) -> str:
    """Compact summary like `'A · RunningRoad · 21.1 km · Goal 1:35:00 · Place #10 · PR'`."""
    prio = ev.get("priority") or event_priority(ev)
    ev_type = ev.get("event_type") or ev.get("eventType")
    km = as_float(ev.get("distance_km")) or event_distance_km(ev)
    gt_s = event_goal_time_s(ev)
    place = event_goal_place(ev)
    pr = event_goal_pr(ev)
    parts: list[str] = []
    if prio:
        parts.append(f"{prio} Priority")
    if ev_type:
        parts.append(str(ev_type))
    if km:
        parts.append(f"{km:g} km")
    if gt_s:
        parts.append(f"Goal {format_seconds_hms(gt_s)}")
    if place is not None:
        parts.append(f"Place #{place}")
    if pr is True:
        parts.append("PR target")
    elif pr is False:
        parts.append("Non-PR")
    return " · ".join(parts)
