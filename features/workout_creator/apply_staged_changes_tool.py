"""Tool that applies staged workout / note changes (1 to 150+) to TrainingPeaks with rate-limit protection."""

import asyncio
import json
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...shared.session_state import PLAN_CONTEXT_STATE_KEY
from ...shared.ui_channel import reply
from ...shared.workout_upsert import write_changes_throttled
from .helpers.staged_changes import APPLIED_CHANGES_STATE_KEY, STAGED_CHANGES_STATE_KEY, confirmation_text

NOTHING_STAGED_TEXT = "There are no staged changes to apply. Ask me to plan the changes first."
REPLACED_TEXT = (
    "These changes were replaced by a newer set. Use the **Update TrainingPeaks** button on the latest changes."
)
_sleep = asyncio.sleep  # module-level hook so tests can skip real 429 backoff


async def apply_staged_changes(tool_context: ToolContext, staged_id: Optional[str] = None) -> str:
    """Applies already-staged workout/note changes when the runner approves in chat (omit `staged_id`; never call to stage new edits)."""
    staged = tool_context.state.get(STAGED_CHANGES_STATE_KEY)
    if not isinstance(staged, dict) or not staged.get("changes"):
        reply(tool_context, NOTHING_STAGED_TEXT)
        return json.dumps({"success": False, "reason": "nothing_staged"})
    if staged_id and staged_id != staged.get("staged_id"):
        reply(tool_context, REPLACED_TEXT)
        return json.dumps({"success": False, "reason": "replaced"})

    orig_changes = list(staged["changes"])
    results = await write_changes_throttled(tool_context, orig_changes, sleep=_sleep)
    remaining = [orig for orig, res in zip(orig_changes, results) if not res.get("ok")]
    if remaining:
        # Keep only unapplied failed items staged so pressing Update TrainingPeaks retries them with 0 LLM calls.
        tool_context.state[STAGED_CHANGES_STATE_KEY] = {**staged, "changes": remaining}
    else:
        tool_context.state[STAGED_CHANGES_STATE_KEY] = None
        tool_context.state[APPLIED_CHANGES_STATE_KEY] = {
            "staged_id": staged.get("staged_id"),
            "applied": sum(1 for r in results if r.get("ok")),
            "failed": 0,
        }
    if any(r.get("ok") for r in results):
        tool_context.state[PLAN_CONTEXT_STATE_KEY] = None
    reply(tool_context, confirmation_text(results))
    return json.dumps({
        "success": not remaining and any(r.get("ok") for r in results),
        "partial": bool(remaining and any(r.get("ok") for r in results)),
        "remaining": len(remaining),
        "results": results,
    })


apply_staged_changes_tool = FunctionTool(apply_staged_changes)
