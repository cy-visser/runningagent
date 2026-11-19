"""Web quick actions: deterministic skill + data-tool dispatch without an LLM routing call.

A dashboard feature button sends a structured action. The web BFF appends it to the runner's message
as one extra text part `QUICK_ACTION_PART_PREFIX + json` (Agent Runtime's `/api/run_sse` drops
`state_delta`, so state cannot carry it). `QuickActionPlugin` removes that part from the message
before it is persisted and puts the action in `temp:quick_action` state for that one turn (`temp:`
keys are never persisted). On the turn's first model call `dispatch_quick_action` returns the
data-tool (+ `load_skill`) calls directly, eliminating the LLM routing call.

Prefix-cache invariant:
- Report, workout, and schedule dispatches keep the full `(system_instruction + tools)` prefix
  intact from Turn 0 onward (`SYNTHESIS_GUARD_STATE_KEY`), warming the implicit prefix cache on
  Turn 0 while `drop_disabled_tool_calls` strips any stray function calls returned on synthesis.
- Only `plan-builder:intake` (`PLAN_INTAKE_STATE_KEY`) runs with `_PLAN_INTAKE_RULES`, zero tools,
  and `LOW` thinking. Zero-LLM code actions end inside the tool via `skip_summarization=True`.
"""

import json
import logging
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.invocation_context import InvocationContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types
from opentelemetry import trace

from ...features.check_in_report.fetch_checkin_data_tool import fetch_checkin_data_tool
from ...features.check_in_report.refresh_race_projection_tool import (
    refresh_race_projection_tool,
)
from ...features.plan_audit.fetch_plan_audit_data_tool import (
    fetch_plan_audit_data_tool,
)
from ...features.plan_builder.apply_training_plan_tool import apply_training_plan_tool
from ...features.plan_builder.fetch_plan_context_tool import fetch_plan_context_tool
from ...features.schedule_lookup.get_schedule_tool import get_schedule_tool
from ...features.trend_analysis.fetch_trend_data_tool import fetch_trend_data_tool
from ...features.workout_analysis.analyze_workout_tool import analyze_workout_tool
from ...features.workout_creator.apply_staged_changes_tool import apply_staged_changes_tool
from .typed_dispatch import (
    BIKE_WORKOUT_SKILL,
    RUN_WORKOUT_SKILL,
    SCHEDULE_LOOKUP,
    has_action_or_event_intent,
    infer_typed_quick_action,
)

logger = logging.getLogger(__name__)

# Set per turn from the web BFF (`webapp/backend/app/quick_actions.py`; contract in test_structure).
QUICK_ACTION_STATE_KEY = "temp:quick_action"
# Message part carrying the action: this prefix followed by the action JSON.
QUICK_ACTION_PART_PREFIX = "[[running_coach:quick_action]]"
# Invocation id of the Build Plan opener (`plan-builder:intake`): uses `_PLAN_INTAKE_RULES`, tools=[], LOW thinking.
PLAN_INTAKE_STATE_KEY = "temp:plan_intake_invocation"
# Invocation id of a report/schedule synthesis call: keeps the full prefix cached while dropping stray tool calls.
SYNTHESIS_GUARD_STATE_KEY = "temp:report_synthesis_guard"

PLAN_INTAKE = "plan-builder:intake"
PROJECT_RACE = "check-in-report:project"

# skill -> (data tool, arguments the web app may set)
QUICK_ACTIONS = {
    "check-in-report": (fetch_checkin_data_tool, frozenset({"start_date", "end_date"})),
    PROJECT_RACE: (refresh_race_projection_tool, frozenset({"refresh_analysis_cache"})),
    "trend-analysis": (fetch_trend_data_tool, frozenset({"weeks"})),
    "plan-audit": (fetch_plan_audit_data_tool, frozenset({"start_date", "end_date"})),
    RUN_WORKOUT_SKILL: (analyze_workout_tool, frozenset({"date_str", "sport"})),
    # "Update TrainingPeaks" button: applies the staged changes in code (zero LLM calls).
    "workout-creator": (apply_staged_changes_tool, frozenset({"staged_id"})),
    # Build Plan button: fetches plan context in code; one short opener call with tools off.
    PLAN_INTAKE: (fetch_plan_context_tool, frozenset()),
    # Apply to TrainingPeaks on a staged plan: one silent action per week in code (zero LLM calls).
    "plan-builder:apply": (apply_training_plan_tool, frozenset({"staged_id", "week"})),
}
# Internal dispatch table adds bike-workout-analysis and schedule-lookup for typed chat pre-dispatch.
_TYPED_DISPATCH_ACTIONS = {
    **QUICK_ACTIONS,
    BIKE_WORKOUT_SKILL: (analyze_workout_tool, frozenset({"date_str", "sport"})),
    SCHEDULE_LOOKUP: (get_schedule_tool, frozenset({"start_date", "end_date"})),
}
# Actions that only execute code or need no SKILL.md instructions loaded.
SKILL_FREE_ACTIONS = frozenset({
    "workout-creator", "plan-builder:apply", PLAN_INTAKE, PROJECT_RACE, SCHEDULE_LOOKUP,
})
# Pure-code actions that end inside the tool via `skip_summarization=True` (no LLM call follows).
_ZERO_LLM_ACTIONS = frozenset({"workout-creator", "plan-builder:apply", PROJECT_RACE})

LOAD_SKILL = "load_skill"
# Gemini 3/4 validates thought signatures on the current turn's function calls; calls synthesized in code
# carry the documented dummy signature on the first call part (preserved across turns for prefix caching).
SYNTHETIC_THOUGHT_SIGNATURE = b"skip_thought_signature_validator"
NO_TOOL_CALLS = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.NONE)
)


def is_plan_intake(state: Any, invocation_id: Optional[str]) -> bool:
    """True during the Build Plan opener call (`plan-builder:intake`, this invocation only)."""
    return bool(invocation_id) and state.get(PLAN_INTAKE_STATE_KEY) == invocation_id


def is_synthesis_guard(state: Any, invocation_id: Optional[str]) -> bool:
    """True during a report/schedule synthesis call (keeps full prefix cached while dropping stray tool calls)."""
    return bool(invocation_id) and state.get(SYNTHESIS_GUARD_STATE_KEY) == invocation_id


def _is_turn_start(llm_request: LlmRequest) -> bool:
    """The turn's first model call: the last content is the runner's message, not a tool response."""
    if not llm_request.contents:
        return False
    last = llm_request.contents[-1]
    parts = last.parts or []
    return last.role == "user" and any(p.text for p in parts) and not any(p.function_response for p in parts)


def _turn_start_text(llm_request: LlmRequest) -> Optional[str]:
    if not _is_turn_start(llm_request):
        return None
    return " ".join(p.text for p in (llm_request.contents[-1].parts or []) if p.text).strip() or None


def _no_model_step_yet(callback_context: CallbackContext) -> bool:
    """Covers silent actions whose message has no text (e.g. per-week plan apply)."""
    session = getattr(callback_context, "session", None)
    invocation_id, agent = callback_context.invocation_id, callback_context.agent_name
    return session is not None and not any(
        e.invocation_id == invocation_id and e.author == agent for e in session.events or []
    )


def _consume_or_infer_action(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> tuple[Optional[dict[str, Any]], bool]:
    state = callback_context.state
    action = state.get(QUICK_ACTION_STATE_KEY)
    if action:
        if not (_is_turn_start(llm_request) or _no_model_step_yet(callback_context)):
            return None, False
        state[QUICK_ACTION_STATE_KEY] = None  # consumed: never dispatched twice
        return action, False
    if _is_turn_start(llm_request):
        inferred = infer_typed_quick_action(_turn_start_text(llm_request))
        return inferred, inferred is not None
    return None, False


def quick_action_calls(
    action: Any, _llm_request: Optional[LlmRequest] = None, *, allow_typed: bool = False
) -> list[types.Part]:
    """The function-call parts for a valid action (`[]` when the action is unknown)."""
    registry = _TYPED_DISPATCH_ACTIONS if allow_typed else QUICK_ACTIONS
    if not isinstance(action, dict) or action.get("skill") not in registry:
        return []
    skill = action["skill"]
    tool, allowed = registry[skill]
    raw_args = action.get("args") if isinstance(action.get("args"), dict) else {}
    args = {k: v for k, v in raw_args.items() if k in allowed and v is not None}
    calls = [(tool.name, args)]
    if skill not in SKILL_FREE_ACTIONS:
        calls.append((LOAD_SKILL, {"skill_name": skill}))
    return [
        types.Part(
            function_call=types.FunctionCall(name=name, args=call_args),
            thought_signature=SYNTHETIC_THOUGHT_SIGNATURE if i == 0 else None,
        )
        for i, (name, call_args) in enumerate(calls)
    ]


def dispatch_quick_action(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: runs a web quick action (or standalone typed prompt) without a routing LLM call."""
    state = callback_context.state
    invocation_id = callback_context.invocation_id
    if is_plan_intake(state, invocation_id):
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.tool_config = NO_TOOL_CALLS
        llm_request.config.tools = []
        return None
    if is_synthesis_guard(state, invocation_id):
        return None

    action, inferred = _consume_or_infer_action(callback_context, llm_request)
    if not action:
        return None
    parts = quick_action_calls(action, allow_typed=inferred)
    if not parts:
        return None  # unknown action: fall back to normal LLM routing

    skill = action["skill"]
    if skill == PLAN_INTAKE:
        state[PLAN_INTAKE_STATE_KEY] = invocation_id
    elif skill not in _ZERO_LLM_ACTIONS:
        state[SYNTHESIS_GUARD_STATE_KEY] = invocation_id
    if inferred:
        trace.get_current_span().set_attribute("coach.typed_pre_dispatch", skill)
    return LlmResponse(content=types.Content(role="model", parts=parts))


def drop_disabled_tool_calls(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: synthesis and intake calls must end on text; drop any stray function calls."""
    content = llm_response.content
    if llm_response.partial or not content or not content.parts:
        return None
    if not (
        is_plan_intake(callback_context.state, callback_context.invocation_id)
        or is_synthesis_guard(callback_context.state, callback_context.invocation_id)
    ):
        return None
    kept = [p for p in content.parts if not p.function_call]
    if len(kept) == len(content.parts):
        return None
    trace.get_current_span().set_attribute("coach.dropped_tool_calls", len(content.parts) - len(kept))
    logger.warning("Dropped %d function call(s) from a synthesis/intake call", len(content.parts) - len(kept))
    return llm_response.model_copy(update={"content": content.model_copy(update={"parts": kept})})


def extract_quick_action(message: Optional[types.Content]) -> Optional[dict]:
    """Removes the quick-action part(s) from `message` in place; returns the action (None if absent/invalid)."""
    if not message or not message.parts:
        return None
    action, kept = None, []
    for part in message.parts:
        text = part.text or ""
        if text.startswith(QUICK_ACTION_PART_PREFIX):
            try:
                parsed = json.loads(text[len(QUICK_ACTION_PART_PREFIX):])
                action = parsed if isinstance(parsed, dict) else action
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed quick-action part")
            continue
        kept.append(part)
    if len(kept) != len(message.parts):
        message.parts = kept
    return action


class QuickActionPlugin(BasePlugin):
    """Moves a web quick action from the runner's message into per-turn `temp:` state."""

    def __init__(self) -> None:
        super().__init__(name="quick_action")

    async def on_user_message_callback(
        self, *, invocation_context: InvocationContext, user_message: types.Content
    ) -> Optional[types.Content]:
        action = extract_quick_action(user_message)
        if action is not None:
            invocation_context.session.state[QUICK_ACTION_STATE_KEY] = action
            logger.info("Quick action received: %s", action.get("skill"))
        return None


__all__ = [
    "BIKE_WORKOUT_SKILL",
    "LOAD_SKILL",
    "NO_TOOL_CALLS",
    "PLAN_INTAKE",
    "PLAN_INTAKE_STATE_KEY",
    "PROJECT_RACE",
    "QUICK_ACTIONS",
    "QUICK_ACTION_PART_PREFIX",
    "QUICK_ACTION_STATE_KEY",
    "QuickActionPlugin",
    "RUN_WORKOUT_SKILL",
    "SCHEDULE_LOOKUP",
    "SKILL_FREE_ACTIONS",
    "SYNTHESIS_GUARD_STATE_KEY",
    "SYNTHETIC_THOUGHT_SIGNATURE",
    "dispatch_quick_action",
    "drop_disabled_tool_calls",
    "extract_quick_action",
    "has_action_or_event_intent",
    "infer_typed_quick_action",
    "is_plan_intake",
    "is_synthesis_guard",
    "quick_action_calls",
]
