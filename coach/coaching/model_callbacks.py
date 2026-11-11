"""Model callbacks for the coaching agent.

- Per call: thinking (COACH_THINKING_LEVEL, default MEDIUM; LOW for a short chat approval of staged changes).
- History: thought signatures of completed turns are dropped before each call.
(The staging call carries the coaching message and ends the turn itself: `stage_workout_changes`, `shared/ui_channel.py`.)
"""

from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry import trace

from ...features.workout_creator.stage_workout_changes_tool import STAGED_CHANGES_STATE_KEY
from ..model_config import COACH_THINKING_LEVEL

# ------------------------------------------------------------------------------
# Thinking policy
# ------------------------------------------------------------------------------
# LOW, not MINIMAL: Gemini 4 Argon accepts LOW / MEDIUM / HIGH only.
EXECUTION_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
DEFAULT_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel[COACH_THINKING_LEVEL])
APPROVAL_MAX_WORDS = 12


def _text(content: types.Content) -> Optional[str]:
    return " ".join(p.text for p in content.parts or [] if p.text).strip() or None


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


def thinking_for(state: Any, llm_request: LlmRequest) -> tuple[types.ThinkingConfig, str]:
    """The thinking config for this call and why (recorded on the trace span)."""
    if is_staged_approval(state, llm_request):
        return EXECUTION_THINKING, "approval"
    return DEFAULT_THINKING, "default"


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: the call's thinking level. Never changes the prompt (keeps the cache prefix)."""
    thinking, reason = thinking_for(callback_context.state, llm_request)
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


def _is_runner_message(content: types.Content) -> bool:
    """A user content that is not just tool responses (i.e. a real runner message)."""
    return content.role == "user" and any(not p.function_response for p in content.parts or [])


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
