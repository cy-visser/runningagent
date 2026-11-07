"""TrainingPeaks create/update dispatch for staged workouts and notes (pure execution, no lookups)."""

import logging
from typing import Any

from google.adk.tools import ToolContext

from ....integrations.trainingpeaks import tp_calls
from ....shared.tp_payloads import coerce_mcp_payload
from .staged_changes import KIND_NOTE

logger = logging.getLogger(__name__)

# Per-action differences between the create and update MCP tools.
_CREATE_SPEC = {"tool": "tp_create_workout", "duration_cast": lambda v: int(round(v)), "verb": "create"}
_UPDATE_SPEC = {"tool": "tp_update_workout", "duration_cast": float, "verb": "update"}


async def _run(tool_context: ToolContext, tool: str, verb: str, what: str, node_input: dict) -> dict[str, Any]:
    """Runs one TP write; returns {"ok": True, "id": ...} or {"ok": False, "error": ...}."""
    try:
        result = await tp_calls.run_tp_tool(tool_context, tool, **node_input)
    except Exception as e:
        logger.error("Failed to %s %s (%s): %s", verb, what, node_input.get("date"), e)
        return {"ok": False, "error": f"Failed to {verb} {what}: {e}"}
    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return {"ok": False, "error": str(data.get("message") or "Unknown error")}
    return {"ok": True, "id": data.get("id") or data.get("workout_id")}


async def write_workout(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Creates or updates one resolved workout change (update when it carries a workout_id).

    An update writes only what the coach changed: fields listed in `inherited` (the current workout's
    title / planned totals, shown on the card) are left to TrainingPeaks.
    """
    spec = _UPDATE_SPEC if change.get("workout_id") else _CREATE_SPEC
    inherited = set(change.get("inherited") or ()) if change.get("workout_id") else set()

    def changed(field: str) -> bool:
        return change.get(field) is not None and field not in inherited

    node_input: dict[str, Any] = {"date": change["date"], "sport": change["sport"]}
    if changed("title"):
        node_input["title"] = change["title"]
    if change.get("workout_id"):
        node_input["workout_id"] = change["workout_id"]
    if changed("duration_minutes"):
        node_input["duration_minutes"] = spec["duration_cast"](change["duration_minutes"])
    if changed("distance_km"):
        node_input["distance_km"] = float(change["distance_km"])
    if changed("tss_planned"):
        node_input["tss_planned"] = float(change["tss_planned"])
    if change.get("description"):
        node_input["description"] = change["description"]
    if change.get("structured_workout"):
        node_input["structured_workout"] = change["structured_workout"]
    result = await _run(tool_context, spec["tool"], spec["verb"], "workout", node_input)
    if result["ok"] and change.get("workout_id"):
        result["id"] = change["workout_id"]
    return result


async def write_note(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Creates one calendar note."""
    node_input: dict[str, Any] = {"date": change["date"][:10], "title": change["title"]}
    if change.get("description"):
        node_input["description"] = change["description"]
    return await _run(tool_context, "tp_create_note", "create", "note", node_input)


async def write_change(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Writes one resolved staged change; returns the change (without its native builder) merged with its outcome."""
    writer = write_note if change.get("kind") == KIND_NOTE else write_workout
    outcome = await writer(tool_context, change)
    return {**{k: v for k, v in change.items() if k != "structured_workout"}, **outcome}
