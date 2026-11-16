"""Tool that applies the staged workout / note changes to TrainingPeaks (pure code, no reasoning)."""

import asyncio
import json
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...shared.session_state import PLAN_CONTEXT_STATE_KEY
from ...shared.ui_channel import reply
from .helpers.staged_changes import APPLIED_CHANGES_STATE_KEY, STAGED_CHANGES_STATE_KEY, confirmation_text
from ...shared.workout_upsert import write_change

NOTHING_STAGED_TEXT = "There are no staged changes to apply. Ask me to plan the changes first."
REPLACED_TEXT = (
    "These changes were replaced by a newer set. Use the **Update TrainingPeaks** button on the latest changes."
)


async def apply_staged_changes(tool_context: ToolContext, staged_id: Optional[str] = None) -> str:
    """Applies already-staged workout/note changes when the runner approves in chat (omit `staged_id`; never call to stage new edits)."""
    staged = tool_context.state.get(STAGED_CHANGES_STATE_KEY)
    if not isinstance(staged, dict) or not staged.get("changes"):
        reply(tool_context, NOTHING_STAGED_TEXT)
        return json.dumps({"success": False, "reason": "nothing_staged"})
    if staged_id and staged_id != staged.get("staged_id"):
        reply(tool_context, REPLACED_TEXT)
        return json.dumps({"success": False, "reason": "replaced"})

    results = list(await asyncio.gather(*(write_change(tool_context, c) for c in staged["changes"])))
    tool_context.state[STAGED_CHANGES_STATE_KEY] = None
    if any(r.get("ok") for r in results):
        tool_context.state[PLAN_CONTEXT_STATE_KEY] = None
    tool_context.state[APPLIED_CHANGES_STATE_KEY] = {
        "staged_id": staged.get("staged_id"),
        "applied": sum(1 for r in results if r.get("ok")),
        "failed": sum(1 for r in results if not r.get("ok")),
    }
    reply(tool_context, confirmation_text(results))
    return json.dumps({"success": any(r.get("ok") for r in results), "results": results})


apply_staged_changes_tool = FunctionTool(apply_staged_changes)
