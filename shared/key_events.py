"""Key events: the coach's hidden memory of what happened to the runner (races, injuries, breaks...).

Stored on the runner profile as `key_events` (a list, oldest first). The runner never sees or edits it:
the web BFF strips it from profile responses and its edit payload has no such field. Written by code
(`analyze_workout` on a goal race date) and by the coach (`record_key_event` tool); read by the coach
through the profile block (`format_key_events`), which is rebuilt on every model call.
"""

from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Optional

from ..integrations import firestore
from .dates import get_today_date, iso_date, parse_date
from .runner_identity import profile_user_id

logger = logging.getLogger(__name__)

KEY_EVENTS_FIELD = "key_events"
EVENT_TYPES = ("race", "injury", "illness", "break", "life", "other")
SOURCE_WORKOUT_ANALYSIS = "workout_analysis"
SOURCE_COACH = "coach"

MAX_STORED = 100  # oldest events are dropped beyond this
CONTEXT_MAX = 15  # events shown to the coach
CONTEXT_DAYS = 548  # ~18 months shown to the coach
MAX_SUMMARY_CHARS = 300


def make_event(
    event_type: str,
    day: Any,
    summary: str,
    source: str,
    workout_id: Optional[str] = None,
    recorded_at: Optional[str] = None,
) -> dict:
    """A validated event. Raises ValueError for an unknown type, a bad date or an empty summary."""
    kind = str(event_type or "").strip().lower()
    if kind not in EVENT_TYPES:
        raise ValueError(f"event_type must be one of {', '.join(EVENT_TYPES)}")
    parsed = parse_date(day)
    if not parsed:
        raise ValueError("date must be YYYY-MM-DD")
    text = " ".join(str(summary or "").split())[:MAX_SUMMARY_CHARS]
    if not text:
        raise ValueError("summary must not be empty")
    event = {
        "date": iso_date(parsed),
        "type": kind,
        "summary": text,
        "source": source,
        "recorded_at": recorded_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if workout_id:
        event["workout_id"] = str(workout_id)
    return event


def _valid(events: Any) -> list[dict]:
    return [e for e in events or [] if isinstance(e, dict) and e.get("date") and e.get("summary")]


def add_key_event(events: Any, event: dict) -> list[dict]:
    """`events` plus `event`, sorted by date and capped at MAX_STORED (a new list).

    A race with the same workout_id replaces the earlier entry (re-analysis); an event with the same
    date, type and summary is not added twice.
    """
    kept = []
    for e in _valid(events):
        if event.get("workout_id") and e.get("workout_id") == event["workout_id"] and e.get("type") == event["type"]:
            continue
        if (e.get("date"), e.get("type"), e.get("summary")) == (event["date"], event["type"], event["summary"]):
            return sorted(_valid(events), key=lambda x: str(x["date"]))[-MAX_STORED:]
        kept.append(dict(e))
    kept.append(dict(event))
    return sorted(kept, key=lambda x: str(x["date"]))[-MAX_STORED:]


def format_key_events(profile: Optional[dict], today: Optional[date] = None) -> str:
    """KEY EVENTS section for the profile block ('' when there are none in the window)."""
    today = today or get_today_date()
    cutoff = today - timedelta(days=CONTEXT_DAYS)
    recent = [e for e in _valid((profile or {}).get(KEY_EVENTS_FIELD)) if (parse_date(e["date"]) or date.min) >= cutoff]
    if not recent:
        return ""
    recent = sorted(recent, key=lambda e: str(e["date"]))[-CONTEXT_MAX:]
    lines = [f"- {e['date']} {e.get('type') or 'other'}: {e['summary']}" for e in recent]
    return (
        "KEY EVENTS (recorded by you, the coach, oldest first; the runner cannot see this list, so refer to the "
        "events naturally, e.g. \"your calf strain in November\", never to a list or profile field):\n"
        + "\n".join(lines)
    )


async def save_key_event(tool_context: Any, profile: Optional[dict], event: dict) -> bool:
    """Adds `event` to the stored profile and to `user_profile` state. False when it cannot be saved."""
    profile = profile or {}
    user_id = profile_user_id(profile)
    if not user_id:
        logger.error("Cannot save a key event: no runner name in profile")
        return False
    events = add_key_event(profile.get(KEY_EVENTS_FIELD), event)
    try:
        await firestore.update_user_profile(user_id, {KEY_EVENTS_FIELD: events})
    except Exception as e:
        logger.error("Failed to save key event for %s: %s", user_id, e)
        return False
    latest = tool_context.state.get("user_profile") or profile
    tool_context.state["user_profile"] = {**latest, KEY_EVENTS_FIELD: events}
    return True
