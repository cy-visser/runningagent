"""Model callbacks for the coaching agent.

- Thinking: low reasoning for the confirmation that follows a write tool, default otherwise.
- History: reasoning and thought signatures of completed turns are dropped before each call.

(Report metrics and tables are rendered by the web app from the `*_report_data` payloads; the
coach's text is never spliced.)
"""

from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ...features.workout_creator.create_note_tool import create_note_tool
from ...features.workout_creator.create_workout_tool import create_workout_tool
from ..onboarding.request_new_goal_tool import request_new_goal_tool

# ------------------------------------------------------------------------------
# Thinking policy
# ------------------------------------------------------------------------------
# Tools whose response only needs a short confirmation. Anything else (runner messages,
# facade outputs, get_weather, unknown tools) keeps the model's default reasoning.
WRITE_TOOLS = frozenset({
    create_workout_tool.name,
    create_note_tool.name,
    request_new_goal_tool.name,
})
# LOW, not MINIMAL: gemini-3.8-flash (COACH_MODEL) rejects THINKING_LEVEL_MINIMAL with a 400.
CONFIRMATION_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)


def _last_function_responses(llm_request: LlmRequest) -> list[types.FunctionResponse]:
    """Tool responses in the request's final content (empty if it isn't a tool response)."""
    if not llm_request.contents:
        return []
    parts = llm_request.contents[-1].parts or []
    return [p.function_response for p in parts if p.function_response and p.function_response.name]


def _wrote(response: types.FunctionResponse) -> bool:
    """False when a write tool stopped before writing (`needs_confirmation` / `needs_workout_id`)."""
    return '"action": "needs_' not in str((response.response or {}).get("result") or "")


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: low thinking right after successful writes, default otherwise."""
    responses = _last_function_responses(llm_request)
    if responses and all(r.name in WRITE_TOOLS and _wrote(r) for r in responses):
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.thinking_config = CONFIRMATION_THINKING
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
