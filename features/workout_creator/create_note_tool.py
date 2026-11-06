"""Tool for creating a calendar note in TrainingPeaks."""

import json
import logging
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.tp_payloads import coerce_mcp_payload

logger = logging.getLogger(__name__)


async def create_note(
    tool_context: ToolContext,
    date: str,
    title: str,
    description: Optional[str] = None,
) -> str:
    """Creates a calendar note in TrainingPeaks (travel, illness, rest days, life stress)."""
    node_input: dict[str, Any] = {"date": date, "title": title}
    if description is not None:
        node_input["description"] = description

    try:
        result = await tp_calls.run_tp_tool(tool_context, "tp_create_note", **node_input)
    except Exception as e:
        logger.error("Failed to create calendar note on %s: %s", date, e)
        return f"Error: Failed to create calendar note: {e}"

    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return f"Error creating note: {data.get('message', 'Unknown error')}"
    return json.dumps(data) if data else "Success: Calendar note created."


create_note_tool = FunctionTool(create_note)
