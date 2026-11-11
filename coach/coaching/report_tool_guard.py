"""Keeps report data tools from being used as data lookups.

`fetch_checkin_data`, `fetch_trend_data` and `fetch_plan_audit_data` write a web report payload to
state, which the web app renders as a full report card. Called as a lookup in a follow-up turn (e.g. to
find workout ids for `stage_workout_changes`), they would open a report the runner never asked for.

`track_turn_calls` (after_model_callback) records each model step's function calls of the current
invocation before its tools run. `guard_report_tools` (before_tool_callback) only lets a report tool run
when it is the turn's report: no other skill was loaded in this turn and no earlier step of the turn
called anything but `load_skill` of the report's own skill. Otherwise the tool is skipped (no state
write, no report card) and the model is told to answer from the data in the conversation.
"""

from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

TURN_CALLS_STATE_KEY = "temp:turn_calls"
LOAD_SKILL = "load_skill"

# report data tool -> the skill whose report it renders
REPORT_TOOL_SKILLS = {
    "fetch_checkin_data": "check-in-report",
    "fetch_trend_data": "trend-analysis",
    "fetch_plan_audit_data": "plan-audit",
}

_REPORT_NAMES = {
    "fetch_checkin_data": "check-in report",
    "fetch_trend_data": "trend report",
    "fetch_plan_audit_data": "plan audit report",
}


def _step_calls(llm_response: LlmResponse) -> list[dict]:
    content = llm_response.content
    calls = []
    for part in (content.parts if content else None) or []:
        fc = part.function_call
        if fc and fc.name:
            call = {"name": fc.name}
            if fc.name == LOAD_SKILL:
                call["skill"] = (fc.args or {}).get("skill_name")
            calls.append(call)
    return calls


def track_turn_calls(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: appends this model step's function calls to the turn's record."""
    if llm_response.partial:
        return None
    calls = _step_calls(llm_response)
    if not calls:
        return None
    invocation_id = callback_context.invocation_id
    record = callback_context.state.get(TURN_CALLS_STATE_KEY)
    steps = list(record["steps"]) if isinstance(record, dict) and record.get("invocation") == invocation_id else []
    steps.append(calls)
    callback_context.state[TURN_CALLS_STATE_KEY] = {"invocation": invocation_id, "steps": steps}
    return None


def _turn_steps(tool_context: ToolContext) -> list[list[dict]]:
    record = tool_context.state.get(TURN_CALLS_STATE_KEY)
    if isinstance(record, dict) and record.get("invocation") == tool_context.invocation_id:
        return record.get("steps") or []
    return []


def is_turn_report(tool_name: str, steps: list[list[dict]]) -> bool:
    """True when `tool_name` runs as this turn's report, not as a lookup.

    `steps` are the turn's model steps; the last one holds the current call.
    """
    skill = REPORT_TOOL_SKILLS[tool_name]
    for call in (c for step in steps for c in step):
        if call["name"] == LOAD_SKILL and call.get("skill") != skill:
            return False  # another skill drives this turn
    for call in (c for step in steps[:-1] for c in step):
        if not (call["name"] == LOAD_SKILL and call.get("skill") == skill):
            return False  # other work came first: this would be a lookup
    return True


def blocked_message(tool_name: str) -> str:
    return (
        f"{tool_name} was not run: it renders the {_REPORT_NAMES[tool_name]} for the runner and is only for "
        "that report when the runner asks for it. Answer from the data already in this conversation (planned "
        "sessions carry their [workout_id]); stage_workout_changes resolves a session by date and sport without "
        "an id."
    )


def guard_report_tools(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """before_tool_callback: skips a report tool used as a lookup (no report state, no report card)."""
    if tool.name not in REPORT_TOOL_SKILLS:
        return None
    if is_turn_report(tool.name, _turn_steps(tool_context)):
        return None
    return {"result": blocked_message(tool.name)}
