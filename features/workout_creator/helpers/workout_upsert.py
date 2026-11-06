"""Same-sport planned workout lookup and TrainingPeaks create/update dispatch."""

import json
import logging
from typing import Any, Optional

from google.adk.tools import ToolContext

from ....integrations.trainingpeaks import tp_calls
from ....shared.tp_payloads import coerce_mcp_payload
from ....shared.workout_status import is_workout_completed

logger = logging.getLogger(__name__)

# Per-action differences between the create and update MCP tools.
_CREATE_SPEC = {"tool": "tp_create_workout", "date_key": "date", "duration_cast": int,
                "verb": "create", "gerund": "creating", "past": "created"}
_UPDATE_SPEC = {"tool": "tp_update_workout", "date_key": "date", "duration_cast": float,
                "verb": "update", "gerund": "updating", "past": "updated"}


async def find_existing_workouts(
    tool_context: ToolContext,
    target_iso: str,
    sport: str,
) -> list[dict]:
    """Returns the planned workouts of the same sport on the target date."""
    try:
        workouts_list = await tp_calls.fetch_workouts(tool_context, target_iso, target_iso)
    except Exception as e:
        logger.warning("Failed checking existing workouts for %s: %s", target_iso, e)
        return []
    sport_lower = sport.strip().lower()
    return [
        w for w in workouts_list
        if not is_workout_completed(w) and (w.get("sport") or "").strip().lower() == sport_lower
    ]


async def write_workout(
    tool_context: ToolContext,
    date_str: str,
    sport: str,
    title: str,
    workout_id: Optional[str] = None,
    duration_minutes: Optional[int | float] = None,
    distance_km: Optional[float] = None,
    tss_planned: Optional[float] = None,
    description: Optional[str] = None,
    structure: Optional[Any] = None,
) -> str:
    """Creates or updates a TrainingPeaks workout, depending on whether workout_id is set."""
    spec = _UPDATE_SPEC if workout_id else _CREATE_SPEC

    node_input: dict[str, Any] = {
        spec["date_key"]: date_str,
        "sport": sport,
        "title": title,
    }
    if workout_id:
        node_input["workout_id"] = workout_id
    if duration_minutes is not None:
        node_input["duration_minutes"] = spec["duration_cast"](duration_minutes)
    if distance_km is not None:
        node_input["distance_km"] = float(distance_km)
    if tss_planned is not None:
        node_input["tss_planned"] = float(tss_planned)
    if description is not None:
        node_input["description"] = description
    if structure is not None:
        node_input["structure"] = structure

    try:
        result = await tp_calls.run_tp_tool(tool_context, spec["tool"], **node_input)
    except Exception as e:
        logger.error("Failed to %s workout (%s): %s", spec["verb"], date_str, e)
        return f"Error: Failed to {spec['verb']} workout: {e}"

    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return f"Error {spec['gerund']} workout: {data.get('message', 'Unknown error')}"

    resolved_id = workout_id or data.get("id") or data.get("workout_id")
    return json.dumps({
        "success": True,
        "action": spec["past"],
        "workout_id": resolved_id,
        "title": title,
        "date": date_str,
        "sport": sport,
        "duration_minutes": duration_minutes,
        "distance_km": distance_km,
        "tss_planned": tss_planned,
    })
