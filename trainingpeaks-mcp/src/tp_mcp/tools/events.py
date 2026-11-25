"""Events and calendar tools: races, notes, availability."""

import logging
from datetime import date as dt_date
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from tp_mcp.client import TPClient
from tp_mcp.tools._validation import DateRangeInput, WorkoutIdInput, format_validation_error

logger = logging.getLogger("tp-mcp")

# Default result rows expected by POST /fitness/v6/athletes/{id}/event (singular).
DEFAULT_EVENT_RESULTS: list[dict[str, str]] = [
    {"resultType": "Division"},
    {"resultType": "Gender"},
    {"resultType": "Overall"},
]


# Known ATP running duration types verified from TrainingPeaks v6 event payloads.
RACE_TYPE_DURATIONS = (
    "RunUnderOneHour",
    "RunOnetoTwoHours",
    "RunOverTwoHours",
)


def _parse_goal_time_hours(value: str | float | int | None) -> float | None:
    """Converts 'H:MM:SS', 'MM:SS', or decimal hours into decimal hours for TP `goals.time.value`."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if float(value) > 0 else None
    text = str(value).strip()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 3:
            h, m, s = (int(p) for p in parts)
        elif len(parts) == 2:
            h, m, s = 0, int(parts[0]), int(parts[1])
        else:
            raise ValueError(f"goal_time must be H:MM:SS or MM:SS, got {value!r}")
        if m < 0 or m >= 60 or s < 0 or s >= 60 or h < 0:
            raise ValueError(f"goal_time out of range: {value!r}")
        total_s = h * 3600 + m * 60 + s
        if total_s <= 0:
            raise ValueError("goal_time must be greater than zero.")
        return total_s / 3600.0
    hours = float(text)
    if hours <= 0:
        raise ValueError("goal_time must be greater than zero.")
    return hours


def _build_goal_entry(value: Any, existing: Any = None, **extra: Any) -> dict[str, Any]:
    base = dict(existing) if isinstance(existing, dict) else {}
    entry = {
        "complete": bool(base.get("complete", False)),
        "sortOrder": int(base.get("sortOrder", 0)),
        **extra,
        "value": value,
    }
    for key in ("eventGoalId", "setByPersonId"):
        if base.get(key) is not None:
            entry[key] = base[key]
    return entry


def _merge_event_goals(
    existing_goals: Any,
    *,
    goal_distance_km: float | None = None,
    goal_time: str | float | int | None = None,
    goal_place: int | None = None,
    goal_finish: bool | None = None,
    goal_pr: bool | None = None,
) -> dict[str, Any]:
    """Builds or merges TP v6 `goals` object; returns `{}` when no goals are provided on create."""
    has_any = any(
        v is not None for v in (goal_distance_km, goal_time, goal_place, goal_finish, goal_pr)
    )
    if not has_any:
        return dict(existing_goals) if isinstance(existing_goals, dict) else {}
    goals: dict[str, Any] = dict(existing_goals) if isinstance(existing_goals, dict) else {}
    goals.setdefault("written", [])
    if goal_distance_km is not None:
        goals["distance"] = _build_goal_entry(
            round(float(goal_distance_km) * 1000.0, 1),
            goals.get("distance"),
            displayUnits="Kilometers",
        )
    if goal_time is not None:
        hours = _parse_goal_time_hours(goal_time)
        if hours is not None:
            goals["time"] = _build_goal_entry(hours, goals.get("time"))
    if goal_place is not None:
        goals["place"] = _build_goal_entry(int(goal_place), goals.get("place"))
    if goal_finish is not None:
        goals["finish"] = _build_goal_entry(bool(goal_finish), goals.get("finish"))
    if goal_pr is not None:
        goals["pr"] = _build_goal_entry(bool(goal_pr), goals.get("pr"))
    return goals


def _default_create_event_payload(
    *,
    athlete_id: int,
    name: str,
    event_date_yyyy_mm_dd: str,
    event_type: str,
    atp_priority: str,
    distance_km: float | None,
    ctl_target: float | None,
    description: str | None,
    race_type_duration: str | None = None,
    goals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build JSON body for POST .../event (v6 singular) per TrainingPeaks web app contract."""
    payload: dict[str, Any] = {
        "goals": goals if goals is not None else {},
        "atpPriority": atp_priority,
        "legs": [],
        "eventDate": event_date_yyyy_mm_dd,
        "name": name,
        "personId": athlete_id,
        "eventType": event_type,
        "workouts": [],
        "results": [dict(r) for r in DEFAULT_EVENT_RESULTS],
    }
    if race_type_duration:
        payload["raceTypeDuration"] = race_type_duration
    if distance_km is not None:
        payload["distance"] = round(float(distance_km) * 1000.0, 1)
        payload["distanceUnits"] = "Meters"
    else:
        payload["distance"] = None
        payload["distanceUnits"] = None
    if ctl_target is not None:
        payload["ctlTarget"] = ctl_target
    if description:
        payload["description"] = description
    return payload


# Known event types from the TrainingPeaks event UI (web-form enum values).
# Not exhaustive and not enforced — the API may accept unlisted values.
EVENT_TYPES = [
    "RunningRoad", "RunningTrail", "RunningTrack", "RunningCrossCountry", "RunningOther",
    "CyclingRoad", "CyclingMountain", "CyclingCyclocross", "CyclingTrack", "CyclingOther",
    "SwimOpenWater", "SwimPool",
    "MultisportTriathlon", "MultisportXterra", "MultisportDuathlon",
    "MultisportAquabike", "MultisportAquathon", "MultisportOther",
    "RowingRegatta", "RowingOther",
    "SnowAlpine", "SnowNordic", "SnowSkiMountaineering", "SnowSnowshoe", "SnowOther",
    "OtherAdventure", "OtherObstacle", "OtherSpeedSkate", "OtherOther",
]


class CreateEventInput(BaseModel):
    """Validates input for event creation."""

    name: str = Field(min_length=1, max_length=200)
    date: str
    event_type: str | None = None
    priority: str | None = None
    distance_km: float | None = Field(default=None, ge=0)
    ctl_target: float | None = Field(default=None, ge=0)
    description: str | None = None
    race_type_duration: str | None = None
    goal_distance_km: float | None = Field(default=None, ge=0)
    goal_time: str | float | int | None = None
    goal_place: int | None = Field(default=None, ge=1)
    goal_finish: bool | None = None
    goal_pr: bool | None = None

    @field_validator("date")
    @classmethod
    def check_date(cls, v: str) -> str:
        from datetime import date

        date.fromisoformat(v)
        return v

    @field_validator("priority")
    @classmethod
    def check_priority(cls, v: str | None) -> str | None:
        if v is not None and v not in ("A", "B", "C"):
            raise ValueError("priority must be 'A', 'B', or 'C'")
        return v

    @field_validator("event_type")
    @classmethod
    def check_event_type(cls, v: str | None) -> str | None:
        # Don't reject unknown types - the TP API may accept types not in our list
        return v

    @field_validator("goal_time")
    @classmethod
    def check_goal_time(cls, v: str | float | int | None) -> str | float | int | None:
        if v is not None:
            _parse_goal_time_hours(v)
        return v


async def tp_get_focus_event() -> dict[str, Any]:
    """Get the A-priority focus event with goals and results."""
    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/fitness/v6/athletes/{athlete_id}/events/focusevent"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        if not response.data:
            return {"event": None, "message": "No focus event set."}

        return {"event": response.data}


async def tp_get_next_event() -> dict[str, Any]:
    """Get the nearest future planned event."""
    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/fitness/v6/athletes/{athlete_id}/events/nextplannedevent"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        if not response.data:
            return {"event": None, "message": "No upcoming events."}

        return {"event": response.data}


async def tp_get_events(start_date: str, end_date: str) -> dict[str, Any]:
    """List events in a date range.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        Dict with events list.
    """
    try:
        params = DateRangeInput(start_date=start_date, end_date=end_date)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        start_str = params.start_date.isoformat()
        end_str = params.end_date.isoformat()
        endpoint = f"/fitness/v6/athletes/{athlete_id}/events/{start_str}/{end_str}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        data = response.data if isinstance(response.data, list) else []
        return {
            "events": data,
            "count": len(data),
            "date_range": {"start": start_date, "end": end_date},
        }


async def tp_create_event(
    name: str,
    date: str,
    event_type: str | None = None,
    priority: str | None = None,
    distance_km: float | None = None,
    ctl_target: float | None = None,
    description: str | None = None,
    race_type_duration: str | None = None,
    goal_distance_km: float | None = None,
    goal_time: str | float | int | None = None,
    goal_place: int | None = None,
    goal_finish: bool | None = None,
    goal_pr: bool | None = None,
) -> dict[str, Any]:
    """Create a race/event.

    Args:
        name: Event name.
        date: Event date (YYYY-MM-DD).
        event_type: Event type (e.g. 'RunningRoad', 'RunningOther', 'CyclingRoad'); defaults to 'OtherOther'.
        priority: Priority level ('A', 'B', or 'C'); defaults to 'C' if omitted.
        distance_km: Event distance in km (sent as meters + distanceUnits='Meters').
        ctl_target: Target CTL for the event.
        description: Optional description.
        race_type_duration: ATP event duration type (e.g. 'RunUnderOneHour', 'RunOnetoTwoHours', 'RunOverTwoHours').
        goal_distance_km: Goal distance in km (defaults to distance_km when other goals are set).
        goal_time: Target finish time ('H:MM:SS', 'MM:SS', or decimal hours).
        goal_place: Optional integer target finish placement.
        goal_finish: Optional boolean finish goal (defaults to True when other goals are set).
        goal_pr: Optional boolean PR goal.

    Returns:
        Dict with created event details or error.
    """
    try:
        params = CreateEventInput(
            name=name,
            date=date,
            event_type=event_type,
            priority=priority,
            distance_km=distance_km,
            ctl_target=ctl_target,
            description=description,
            race_type_duration=race_type_duration,
            goal_distance_km=goal_distance_km,
            goal_time=goal_time,
            goal_place=goal_place,
            goal_finish=goal_finish,
            goal_pr=goal_pr,
        )
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        # POST /event (singular) — not /events; matches app.trainingpeaks.com HAR (v6).
        event_type = params.event_type or "OtherOther"
        atp_priority = params.priority or "C"
        has_goal_input = any(
            v is not None
            for v in (params.goal_distance_km, params.goal_time, params.goal_place, params.goal_finish, params.goal_pr)
        )
        goals = _merge_event_goals(
            {},
            goal_distance_km=params.goal_distance_km if params.goal_distance_km is not None else (params.distance_km if has_goal_input else None),
            goal_time=params.goal_time,
            goal_place=params.goal_place,
            goal_finish=params.goal_finish if params.goal_finish is not None else (True if has_goal_input else None),
            goal_pr=params.goal_pr,
        )
        payload = _default_create_event_payload(
            athlete_id=int(athlete_id),
            name=params.name,
            event_date_yyyy_mm_dd=params.date,
            event_type=event_type,
            atp_priority=atp_priority,
            distance_km=params.distance_km,
            ctl_target=params.ctl_target,
            description=params.description,
            race_type_duration=params.race_type_duration,
            goals=goals,
        )

        endpoint = f"/fitness/v6/athletes/{athlete_id}/event"
        response = await client.post(endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        event_id = None
        if isinstance(response.data, dict):
            event_id = response.data.get("eventId", response.data.get("id"))

        return {
            "success": True,
            "event_id": event_id,
            "name": params.name,
            "date": params.date,
        }


async def tp_update_event(
    event_id: str,
    name: str | None = None,
    date: str | None = None,
    event_type: str | None = None,
    priority: str | None = None,
    distance_km: float | None = None,
    ctl_target: float | None = None,
    description: str | None = None,
    workout_ids: list[int] | None = None,
    race_type_duration: str | None = None,
    goal_distance_km: float | None = None,
    goal_time: str | float | int | None = None,
    goal_place: int | None = None,
    goal_finish: bool | None = None,
    goal_pr: bool | None = None,
) -> dict[str, Any]:
    """Update an event (GET then PUT merge).

    Args:
        event_id: Event ID.
        name: Optional new name.
        date: Optional new date (YYYY-MM-DD).
        event_type: Optional event type.
        priority: Optional priority ('A', 'B', 'C').
        distance_km: Optional distance in km.
        ctl_target: Optional CTL target.
        description: Optional description.
        workout_ids: Optional list of workout IDs to attach to the event as its
            legs. TrainingPeaks links workouts via the event's ``workouts`` array
            (the ``legs`` structure is derived server-side); pass the ordered
            swim/T1/bike/T2/run workout IDs. Replaces the existing list.

    Returns:
        Dict with confirmation or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=event_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    # Validate optional fields before making API calls
    if priority is not None and priority not in ("A", "B", "C"):
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "priority must be 'A', 'B', or 'C'.",
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        # GET existing event by searching a broad date range
        today = dt_date.today()
        search_start = (today - timedelta(days=730)).isoformat()
        search_end = (today + timedelta(days=730)).isoformat()
        search_endpoint = f"/fitness/v6/athletes/{athlete_id}/events/{search_start}/{search_end}"
        search_response = await client.get(search_endpoint)

        existing = None
        if search_response.success and isinstance(search_response.data, list):
            for evt in search_response.data:
                if evt.get("id") == validated.workout_id:
                    existing = evt
                    break

        if existing is None:
            return {
                "isError": True,
                "error_code": "NOT_FOUND",
                "message": f"Event {validated.workout_id} not found.",
            }

        # Merge updates into existing event
        existing["personId"] = athlete_id
        if name is not None:
            existing["name"] = name
        if date is not None:
            dt_date.fromisoformat(date)
            # v6 create uses YYYY-MM-DD; keep updates consistent with list/GET shape when possible.
            existing["eventDate"] = date
        if event_type is not None:
            existing["eventType"] = event_type
        if priority is not None:
            existing["atpPriority"] = priority
        if race_type_duration is not None:
            existing["raceTypeDuration"] = race_type_duration
        if distance_km is not None:
            existing["distance"] = round(float(distance_km) * 1000.0, 1)
            existing["distanceUnits"] = "Meters"
        if ctl_target is not None:
            existing["ctlTarget"] = ctl_target
        if description is not None:
            existing["description"] = description
        if any(v is not None for v in (goal_distance_km, goal_time, goal_place, goal_finish, goal_pr)):
            try:
                existing["goals"] = _merge_event_goals(
                    existing.get("goals"),
                    goal_distance_km=goal_distance_km,
                    goal_time=goal_time,
                    goal_place=goal_place,
                    goal_finish=goal_finish,
                    goal_pr=goal_pr,
                )
            except ValueError as e:
                return {
                    "isError": True,
                    "error_code": "VALIDATION_ERROR",
                    "message": str(e),
                }
        if workout_ids is not None:
            # TP attaches workouts to an event via the `workouts` id array (HAR-
            # verified: PUT /event with workouts=[…], legs stays [] and is derived
            # server-side). Replace the list with the provided ordered leg ids.
            existing["workouts"] = [int(w) for w in workout_ids]

        endpoint = f"/fitness/v6/athletes/{athlete_id}/event"
        response = await client.put(endpoint, json=existing)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {
            "success": True,
            "message": f"Event {validated.workout_id} updated.",
        }


async def tp_delete_event(event_id: str) -> dict[str, Any]:
    """Delete an event.

    Args:
        event_id: Event ID.

    Returns:
        Dict with confirmation or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=event_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/fitness/v6/athletes/{athlete_id}/event/{validated.workout_id}"
        response = await client.delete(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {
            "success": True,
            "message": f"Event {validated.workout_id} deleted.",
        }


async def tp_create_note(
    date: str,
    title: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a calendar note.

    Args:
        date: Note date (YYYY-MM-DD).
        title: Note title.
        description: Optional note description.

    Returns:
        Dict with confirmation or error.
    """
    try:
        from datetime import date as date_type

        date_type.fromisoformat(date)
    except ValueError:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": f"Invalid date: {date}",
        }

    if not title or not title.strip():
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Title must not be empty.",
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        payload: dict[str, Any] = {
            "athleteId": athlete_id,
            "noteDate": f"{date}T00:00:00",
            "title": title.strip(),
        }
        if description:
            payload["description"] = description

        endpoint = f"/fitness/v1/athletes/{athlete_id}/calendarNote"
        response = await client.post(endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        note_id = None
        if isinstance(response.data, dict):
            note_id = response.data.get("calendarNoteId", response.data.get("id"))

        return {
            "success": True,
            "note_id": note_id,
            "title": title,
            "date": date,
        }


async def tp_delete_note(note_id: str) -> dict[str, Any]:
    """Delete a calendar note.

    Args:
        note_id: Note ID.

    Returns:
        Dict with confirmation or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=note_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/fitness/v1/athletes/{athlete_id}/calendarNote/{validated.workout_id}"
        response = await client.delete(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {
            "success": True,
            "message": f"Note {validated.workout_id} deleted.",
        }


async def tp_get_note(note_id: str) -> dict[str, Any]:
    """Get a calendar note by ID.

    Args:
        note_id: Note ID.

    Returns:
        Dict with note fields or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=note_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": msg}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID",
                    "message": "Could not get athlete ID. Re-authenticate."}

        endpoint = f"/fitness/v1/athletes/{athlete_id}/calendarNote/{validated.workout_id}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        d = response.data or {}
        note_date_str = d.get("noteDate", "")
        if note_date_str and "T" in note_date_str:
            note_date_str = note_date_str.split("T")[0]

        return {
            "note": {
                "id": d.get("id"),
                "title": d.get("title"),
                "description": d.get("description"),
                "date": note_date_str,
                "is_hidden": d.get("isHidden", False),
                "created_date": d.get("createdDate"),
                "modified_date": d.get("modifiedDate"),
            }
        }


async def tp_list_notes(start_date: str, end_date: str) -> dict[str, Any]:
    """List calendar notes for a date range.

    Args:
        start_date: Range start (YYYY-MM-DD).
        end_date: Range end (YYYY-MM-DD).

    Returns:
        Dict with list of notes or error.
    """
    try:
        validated = DateRangeInput(start_date=start_date, end_date=end_date)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": msg}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID",
                    "message": "Could not get athlete ID. Re-authenticate."}

        start_str = validated.start_date.isoformat()
        end_str = validated.end_date.isoformat()
        # v1 only supports POST/DELETE by ID; range listing requires v2.
        endpoint = f"/fitness/v2/athletes/{athlete_id}/calendarNote/{start_str}/{end_str}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        raw_notes = response.data if isinstance(response.data, list) else []
        notes = []
        for d in raw_notes:
            if not isinstance(d, dict):
                continue
            raw_date = d.get("noteDate")
            if isinstance(raw_date, str) and "T" in raw_date:
                raw_date = raw_date.split("T", 1)[0]
            notes.append({
                "id": d.get("id") or d.get("calendarNoteId"),
                "title": d.get("title"),
                "description": d.get("description"),
                "date": raw_date or None,
                "is_hidden": d.get("isHidden", False),
                "comment_count": d.get("commentCount", 0),
                "created_date": d.get("createdDate"),
                "modified_date": d.get("modifiedDate"),
                "owner_id": d.get("ownerId"),
                "attachments": d.get("attachments") or [],
            })

        return {
            "notes": notes,
            "count": len(notes),
            "date_range": {"start": start_str, "end": end_str},
        }


async def tp_update_note(
    note_id: str,
    title: str | None = None,
    description: str | None = None,
    date: str | None = None,
    is_hidden: bool | None = None,
) -> dict[str, Any]:
    """Update a calendar note.

    Args:
        note_id: Note ID.
        title: New title (optional).
        description: New description (optional).
        date: New note date YYYY-MM-DD (optional).
        is_hidden: Set visibility (optional).

    Returns:
        Dict with updated note or error.
    """
    if title is None and description is None and date is None and is_hidden is None:
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Provide at least one field to update (title, description, date, is_hidden).",
        }

    if title is not None and not title.strip():
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": "Title must not be empty.",
        }

    try:
        validated = WorkoutIdInput(workout_id=note_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": msg}

    if date is not None:
        try:
            from datetime import date as date_type
            date_type.fromisoformat(date)
        except ValueError:
            return {"isError": True, "error_code": "VALIDATION_ERROR",
                    "message": f"Invalid date: {date}"}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID",
                    "message": "Could not get athlete ID. Re-authenticate."}

        get_endpoint = f"/fitness/v1/athletes/{athlete_id}/calendarNote/{validated.workout_id}"
        get_response = await client.get(get_endpoint)
        if get_response.is_error:
            return {
                "isError": True,
                "error_code": get_response.error_code.value if get_response.error_code else "API_ERROR",
                "message": get_response.message,
            }

        payload: dict[str, Any] = dict(get_response.data or {})
        if title is not None:
            payload["title"] = title.strip()
        if description is not None:
            payload["description"] = description
        if date is not None:
            payload["noteDate"] = f"{date}T00:00:00"
        if is_hidden is not None:
            payload["isHidden"] = is_hidden

        put_response = await client.put(get_endpoint, json=payload)
        if put_response.is_error:
            return {
                "isError": True,
                "error_code": put_response.error_code.value if put_response.error_code else "API_ERROR",
                "message": put_response.message,
            }

        d = put_response.data or {}
        note_date_str = d.get("noteDate", "")
        if note_date_str and "T" in note_date_str:
            note_date_str = note_date_str.split("T")[0]

        return {
            "success": True,
            "note": {
                "id": d.get("id"),
                "title": d.get("title"),
                "description": d.get("description"),
                "date": note_date_str,
                "is_hidden": d.get("isHidden", False),
                "modified_date": d.get("modifiedDate"),
            },
        }


async def tp_get_note_comments(note_id: str) -> dict[str, Any]:
    """Get comments for a calendar note.

    Args:
        note_id: Note ID.

    Returns:
        Dict with comments list and count, or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=note_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": msg}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID",
                    "message": "Could not get athlete ID. Re-authenticate."}

        endpoint = f"/fitness/v1/athletes/{athlete_id}/calendarNote/{validated.workout_id}/comments"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        raw_comments: list[dict[str, Any]] = response.data if isinstance(response.data, list) else []
        comments = [
            {
                "id": c.get("calendarNoteCommentStreamId"),
                "comment": c.get("comment"),
                "commenter": f"{c.get('firstName', '')} {c.get('lastName', '')}".strip(),
                "created_at": c.get("createdDateTimeUtc"),
            }
            for c in raw_comments
        ]
        return {"comments": comments, "count": len(comments)}


async def tp_add_note_comment(note_id: str, comment: str) -> dict[str, Any]:
    """Add a comment to a calendar note.

    Args:
        note_id: Note ID.
        comment: Comment text.

    Returns:
        Dict with success confirmation or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=note_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {"isError": True, "error_code": "VALIDATION_ERROR", "message": msg}

    if not comment or not comment.strip():
        return {"isError": True, "error_code": "VALIDATION_ERROR",
                "message": "Comment must not be empty."}

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {"isError": True, "error_code": "AUTH_INVALID",
                    "message": "Could not get athlete ID. Re-authenticate."}

        endpoint = f"/fitness/v1/athletes/{athlete_id}/calendarNote/{validated.workout_id}/comment"
        response = await client.put(endpoint, json={"Comment": comment.strip()})

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {"success": True, "note_id": validated.workout_id}


async def tp_get_availability(start_date: str, end_date: str) -> dict[str, Any]:
    """Get availability entries for a date range.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).

    Returns:
        Dict with availability entries.
    """
    try:
        params = DateRangeInput(start_date=start_date, end_date=end_date)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        start_str = params.start_date.isoformat()
        end_str = params.end_date.isoformat()
        endpoint = f"/fitness/v1/athletes/{athlete_id}/availability/{start_str}/{end_str}"
        response = await client.get(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        data = response.data if isinstance(response.data, list) else []
        return {
            "availability": data,
            "count": len(data),
        }


async def tp_create_availability(
    start_date: str,
    end_date: str,
    limited: bool = False,
    sport_types: list[str] | None = None,
) -> dict[str, Any]:
    """Mark dates as unavailable or limited.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        limited: If True, mark as limited (not fully unavailable).
        sport_types: If limited, list of available sport types.

    Returns:
        Dict with confirmation or error.
    """
    try:
        params = DateRangeInput(start_date=start_date, end_date=end_date)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        payload: dict[str, Any] = {
            "athleteId": athlete_id,
            "startDate": f"{params.start_date.isoformat()}T00:00:00",
            "endDate": f"{params.end_date.isoformat()}T00:00:00",
            "limited": limited,
        }
        if limited and sport_types:
            payload["sportTypes"] = sport_types

        endpoint = f"/fitness/v1/athletes/{athlete_id}/availability"
        response = await client.post(endpoint, json=payload)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        avail_id = None
        if isinstance(response.data, dict):
            avail_id = response.data.get("availabilityId", response.data.get("id"))

        return {
            "success": True,
            "availability_id": avail_id,
            "start_date": start_date,
            "end_date": end_date,
            "limited": limited,
        }


async def tp_delete_availability(availability_id: str) -> dict[str, Any]:
    """Remove an availability entry.

    Args:
        availability_id: Availability entry ID.

    Returns:
        Dict with confirmation or error.
    """
    try:
        validated = WorkoutIdInput(workout_id=availability_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        endpoint = f"/fitness/v1/athletes/{athlete_id}/availability/{validated.workout_id}"
        response = await client.delete(endpoint)

        if response.is_error:
            return {
                "isError": True,
                "error_code": response.error_code.value if response.error_code else "API_ERROR",
                "message": response.message,
            }

        return {
            "success": True,
            "message": f"Availability {validated.workout_id} deleted.",
        }
