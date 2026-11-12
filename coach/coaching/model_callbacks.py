"""Model callbacks for the coaching agent.

- Per call: thinking (COACH_THINKING_LEVEL, default MEDIUM; LOW for staged approvals, short follow-up
  execution confirmations like 'yes update it', and the Build Plan opener), with `include_thoughts=True` so
  the UI receives immediate thinking status.
- Internal tools: `fetch_plan_context` and `apply_training_plan` stay runnable in `tools_dict` for code
  dispatches (`plan-builder:intake`, `plan-builder:apply`, `load_skill("plan-builder")`) and are never
  declared as tools to the LLM.
- History: thought signatures and thought parts of completed turns are dropped before each call.
"""

import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry import trace

from ...features.workout_creator.stage_workout_changes_tool import STAGED_CHANGES_STATE_KEY
from ..model_config import COACH_THINKING_LEVEL
from .quick_actions import drop_disabled_tool_calls, is_plan_intake, is_quick_action_report
from .report_tool_guard import track_turn_calls
from .skill_toolset import PLAN_BUILDER_CONTEXT_ARGS, PLAN_BUILDER_SKILL

# ------------------------------------------------------------------------------
# Internal tools & plan-builder expansion
# ------------------------------------------------------------------------------
INTERNAL_TOOLS = frozenset({"fetch_plan_context", "apply_training_plan"})
LOAD_SKILL = "load_skill"
FETCH_PLAN_CONTEXT = "fetch_plan_context"


def hide_internal_tools(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: removes internal-only tools from `config.tools` (keeps `tools_dict` runnable)."""
    config = llm_request.config
    if not config or not config.tools:
        return None
    kept_tools = []
    for tool in config.tools:
        declarations = getattr(tool, "function_declarations", None)
        if not declarations:
            kept_tools.append(tool)
            continue
        kept = [d for d in declarations if d.name not in INTERNAL_TOOLS]
        if kept:
            kept_tools.append(tool.model_copy(update={"function_declarations": kept}))
    config.tools = kept_tools
    return None


def expand_plan_builder_context(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Appends `fetch_plan_context` in code whenever `load_skill(skill_name="plan-builder")` is called."""
    content = llm_response.content
    if llm_response.partial or not content or not content.parts:
        return None
    if is_quick_action_report(callback_context.state, callback_context.invocation_id):
        return None
    called = {p.function_call.name for p in content.parts if p.function_call}
    if FETCH_PLAN_CONTEXT in called:
        return None
    for part in content.parts:
        fc = part.function_call
        if not fc or fc.name != LOAD_SKILL:
            continue
        raw_args = fc.args or {}
        if raw_args.get("skill_name") != PLAN_BUILDER_SKILL:
            continue
        ctx_args = {k: raw_args[k] for k in PLAN_BUILDER_CONTEXT_ARGS if raw_args.get(k) not in (None, "")}
        added = types.Part(function_call=types.FunctionCall(name=FETCH_PLAN_CONTEXT, args=ctx_args))
        return llm_response.model_copy(
            update={"content": content.model_copy(update={"parts": [*content.parts, added]})}
        )
    return None


def after_coach_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Single `after_model_callback` composing disabled-tool dropping, plan-builder expansion, and turn tracking."""
    shaped = drop_disabled_tool_calls(callback_context, llm_response) or expand_plan_builder_context(
        callback_context, llm_response
    )
    track_turn_calls(callback_context, shaped or llm_response)
    return shaped


# ------------------------------------------------------------------------------
# Thinking policy
# ------------------------------------------------------------------------------
# LOW, not MINIMAL: Gemini 4 Argon accepts LOW / MEDIUM / HIGH only.
EXECUTION_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW, include_thoughts=True)
DEFAULT_THINKING = types.ThinkingConfig(
    thinking_level=types.ThinkingLevel[COACH_THINKING_LEVEL], include_thoughts=True
)
APPROVAL_MAX_WORDS = 12
_CONFIRMATION_RE = re.compile(
    r"^(?:yes|yeah|yep|ok|okay|sure|please|agreed|perfect|great|go\s+ahead|do\s+it|sounds\s+good|looks\s+good)\b"
    r"|^(?:update|stage|apply|schedule)\s+(?:it|them|those|that|my\s+calendar|the\s+(?:plan|sessions|workouts|calendar))\b",
    re.IGNORECASE,
)


def _text(content: types.Content) -> Optional[str]:
    return " ".join(p.text for p in content.parts or [] if p.text).strip() or None


def _is_runner_message(content: types.Content) -> bool:
    """A user content that is not just tool responses (i.e. a real runner message)."""
    return content.role == "user" and any(not p.function_response for p in content.parts or [])


def _runner_text(llm_request: LlmRequest) -> Optional[str]:
    """The runner's message when it is the request's final content (None for tool responses)."""
    if not llm_request.contents:
        return None
    last = llm_request.contents[-1]
    if last.role != "user" or any(p.function_response for p in last.parts or []):
        return None
    return _text(last)


def is_staged_approval(state: Any, llm_request: LlmRequest) -> bool:
    """Changes are staged and the runner's message is a short reply without a question."""
    staged = state.get(STAGED_CHANGES_STATE_KEY)
    if not isinstance(staged, dict) or not staged.get("changes"):
        return False
    text = _runner_text(llm_request)
    return bool(text) and "?" not in text and len(text.split()) <= APPROVAL_MAX_WORDS


def is_followup_confirmation(llm_request: LlmRequest) -> bool:
    """Short affirmative confirmation of a prior coach proposal (e.g. 'yes update it'), held across the turn."""
    contents = llm_request.contents or []
    cut = max((i for i, c in enumerate(contents) if _is_runner_message(c)), default=0)
    if cut == 0 or not any(c.role == "model" for c in contents[:cut]):
        return False
    text = _text(contents[cut])
    if not text or "?" in text or len(text.split()) > APPROVAL_MAX_WORDS:
        return False
    return bool(_CONFIRMATION_RE.match(text.lstrip(" ,.!—-")))


def thinking_for(
    state: Any, llm_request: LlmRequest, invocation_id: Optional[str] = None
) -> tuple[types.ThinkingConfig, str]:
    """The thinking config for this call and why (recorded on the trace span)."""
    if is_staged_approval(state, llm_request):
        return EXECUTION_THINKING, "approval"
    if is_plan_intake(state, invocation_id):
        return EXECUTION_THINKING, "intake"  # short Build Plan opener: the data is already in the request
    if is_followup_confirmation(llm_request):
        return EXECUTION_THINKING, "confirmation"
    return DEFAULT_THINKING, "default"


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: the call's thinking level. Never changes the prompt (keeps the cache prefix)."""
    thinking, reason = thinking_for(callback_context.state, llm_request, callback_context.invocation_id)
    llm_request.config = llm_request.config or types.GenerateContentConfig()
    llm_request.config.thinking_config = thinking
    span = trace.get_current_span()  # no-op span when tracing is off
    span.set_attribute("coach.thinking_level", thinking.thinking_level.name)
    span.set_attribute("coach.thinking_reason", reason)
    return None  # never short-circuits the model call


# ------------------------------------------------------------------------------
# Stale reasoning in history
# ------------------------------------------------------------------------------
# Every Gemini 3 model turn carries a `thought_signature` (encrypted reasoning) that ADK replays
# on every later call and that is billed as input tokens (~35% of a typical coach request).
# Gemini only validates signatures of the CURRENT turn (the tool loop since the last runner
# message), so those of completed turns, and any thought parts, are dropped.


def _has_payload(part: types.Part) -> bool:
    return bool(
        part.text
        or part.function_call
        or part.function_response
        or part.inline_data
        or part.file_data
        or part.executable_code
        or part.code_execution_result
    )


def strip_stale_thoughts(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: drop thoughts and thought signatures of completed turns."""
    contents = llm_request.contents or []
    cut = max((i for i, c in enumerate(contents) if _is_runner_message(c)), default=0)
    kept = []
    for i, content in enumerate(contents):
        if i < cut and content.role == "model":
            parts = [
                p.model_copy(update={"thought_signature": None})
                for p in content.parts or []
                if not p.thought and _has_payload(p)
            ]
            if not parts:
                continue
            content = content.model_copy(update={"parts": parts})
        kept.append(content)
    llm_request.contents = kept
    return None  # never short-circuits the model call
