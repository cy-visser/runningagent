"""Keeps report data tools from being used as data lookups, and gates UI-only tools.

`fetch_checkin_data` and `fetch_plan_audit_data` write a web report payload to state, which the web
app renders as a full report card. Called as a lookup in a follow-up turn (e.g. to find workout ids
for `stage_workout_changes`), they would open a report the runner never asked for. `fetch_trend_data`
is hidden from LLM declarations and only allowed when dispatched by the Trend Analysis dashboard button.

`track_turn_calls` (after_model_callback) records each model step's function calls of the current
invocation before its tools run. `guard_report_tools` (before_tool_callback) only lets a report tool run
when it is the turn's report: no other skill was loaded in this turn and no earlier step of the turn
called anything but `load_skill` of the report's own skill. Otherwise the tool is skipped (no state
write, no report card) and the model is told to answer from the data in the conversation.
"""

import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from opentelemetry import trace

from .quick_actions import (
    SYNTHESIS_GUARD_STATE_KEY,
    has_action_or_event_intent,
    is_plan_intake,
    is_synthesis_guard,
    is_trend_synthesis,
)

TURN_CALLS_STATE_KEY = "temp:turn_calls"
LOAD_SKILL = "load_skill"
FETCH_PLAN_CONTEXT = "fetch_plan_context"
FETCH_TREND_DATA = "fetch_trend_data"
PLAN_BUILDER_SKILL = "plan-builder"
ANALYZE_WORKOUT = "analyze_workout"

# report data tool -> the skill whose report it renders
REPORT_TOOL_SKILLS = {
    "fetch_checkin_data": "check-in-report",
    "fetch_plan_audit_data": "plan-audit",
}
_SYNTHESIS_TOOLS = frozenset({*REPORT_TOOL_SKILLS, "fetch_nutrition_context", "get_schedule"})
_RACE_RE = re.compile(r"\b(?:race|parkrun|time\s+trial|tt)\b", re.IGNORECASE)

_REPORT_NAMES = {
    "fetch_checkin_data": "check-in report",
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


def is_plan_builder_turn(tool_context: ToolContext) -> bool:
    """True when `fetch_plan_context` was dispatched by `plan-builder:intake` or `load_skill('plan-builder')`."""
    if is_plan_intake(tool_context.state, tool_context.invocation_id):
        return True
    return any(
        call["name"] == LOAD_SKILL and call.get("skill") == PLAN_BUILDER_SKILL
        for step in _turn_steps(tool_context)
        for call in step
    )


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
    """before_tool_callback: skips report tools used as lookups, and blocks internal/UI-only tools from chat."""
    if tool.name == FETCH_PLAN_CONTEXT:
        if is_plan_builder_turn(tool_context):
            return None
        return {
            "result": (
                "fetch_plan_context is internal to plan-builder and was not run. Answer directly from "
                "the profile block and the data already in this conversation."
            )
        }
    if tool.name == FETCH_TREND_DATA:
        if is_trend_synthesis(tool_context.state, tool_context.invocation_id):
            return None
        return {
            "result": (
                "fetch_trend_data is triggered only by the Trend Analysis dashboard button and was not run. "
                "Use fetch_plan_audit_data + plan-audit for multi-week/month plan audits, or answer directly "
                "from the profile block and the data already in this conversation."
            )
        }
    if tool.name not in REPORT_TOOL_SKILLS:
        return None
    if is_turn_report(tool.name, _turn_steps(tool_context)):
        return None
    return {"result": blocked_message(tool.name)}


def mark_report_synthesis(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> Optional[dict]:
    """after_tool_callback: guards Step 2 of read-only LLM-routed report turns so it ends on prose while keeping Call 1's prefix cache intact."""
    if tool.name not in _SYNTHESIS_TOOLS and tool.name != ANALYZE_WORKOUT:
        return None
    invocation_id = getattr(tool_context, "invocation_id", None)
    if (
        not invocation_id
        or is_plan_intake(tool_context.state, invocation_id)
        or is_synthesis_guard(tool_context.state, invocation_id)
    ):
        return None
    user_content = getattr(tool_context, "user_content", None)
    if user_content is None:
        return None
    user_text = " ".join(p.text for p in (user_content.parts or []) if p.text).strip()
    if has_action_or_event_intent(user_text):
        return None
    res_obj = tool_response.get("result", tool_response) if isinstance(tool_response, dict) else tool_response
    res_str = res_obj if isinstance(res_obj, str) else str(res_obj or "")
    if res_str.startswith(f"{tool.name} was not run:"):
        return None
    if tool.name == ANALYZE_WORKOUT:
        if "### Workout Analysis" not in res_str or _RACE_RE.search(res_str) or _RACE_RE.search(user_text):
            return None
    steps = _turn_steps(tool_context)
    if not steps or any(c["name"] not in (LOAD_SKILL, tool.name) for step in steps for c in step):
        return None
    tool_context.state[SYNTHESIS_GUARD_STATE_KEY] = invocation_id
    trace.get_current_span().set_attribute("coach.report_synthesis_guard", tool.name)
    return None
