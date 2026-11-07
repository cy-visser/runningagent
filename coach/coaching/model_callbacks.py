"""Model callbacks for the coaching agent.

- Thinking: LOW when the runner approves staged workout changes in chat (the call only has to run
  `apply_staged_changes`) and for the short coaching message after staging; MEDIUM for a turn that
  moves / renames planned sessions; HIGH otherwise.
- History: reasoning and thought signatures of completed turns are dropped before each call.

(Report metrics and tables are rendered by the web app from the `*_report_data` payloads; the
coach's text is never spliced. Replies after staging / applying are coded in
`write_confirmation_callback`, so no model call follows those tools.)
"""

import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry import trace

from ...features.workout_creator.stage_workout_changes_tool import STAGED_CHANGES_STATE_KEY
from ...features.workout_creator.write_confirmation_callback import is_explanation_request

# ------------------------------------------------------------------------------
# Thinking policy
# ------------------------------------------------------------------------------
# LOW: a short chat approval while changes are staged ("update them", "yes do it": it just calls
# apply_staged_changes) and the post-staging coaching message (tools off, the changes are decided).
# MEDIUM: every call of a turn whose runner message asks to move / swap / rename planned sessions
# (resolve the session, stage it; the card shows the details).
# Everything else (runner questions, report/analysis tools, new sessions, request_new_goal,
# get_weather, unknown tools) runs at HIGH, pinned so it never shifts with the model's default.
# LOW, not MINIMAL: not every Gemini 3 flash model accepts THINKING_LEVEL_MINIMAL.
EXECUTION_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
EDIT_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM)
DEFAULT_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.HIGH)
APPROVAL_MAX_WORDS = 12
_SESSION_EDIT = re.compile(
    r"\b(move|moving|shift|swap|switch|reschedule|postpone|push|bring\s+forward|rename|retitle)\b", re.IGNORECASE
)
# ... of a session on a day: a weekday, today/tomorrow, a month or a numeric date.
_DAY_REF = re.compile(
    r"\b(mon|tues?|wed|thu|thurs|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|today|tomorrow|tonight|weekend"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec|january|february|march|april|june|july|august"
    r"|september|october|november|december)\b|\b\d{1,2}(st|nd|rd|th)\b|\d{4}-\d{2}-\d{2}|\b\d{1,2}[/-]\d{1,2}\b",
    re.IGNORECASE,
)


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


def _turn_runner_text(llm_request: LlmRequest) -> Optional[str]:
    """The runner's message that started the current turn (the tool loop since then included)."""
    for content in reversed(llm_request.contents or []):
        parts = content.parts or []
        if content.role == "user" and parts and not any(p.function_response for p in parts):
            return _text(content)
    return None


def is_session_edit_request(llm_request: LlmRequest) -> bool:
    """The current turn asks to move / swap / rename a planned session on a given day."""
    text = _turn_runner_text(llm_request)
    return bool(text) and bool(_SESSION_EDIT.search(text)) and bool(_DAY_REF.search(text))


def is_staged_approval(state: Any, llm_request: LlmRequest) -> bool:
    """Changes are staged and the runner's message is a short reply without a question."""
    staged = state.get(STAGED_CHANGES_STATE_KEY)
    if not isinstance(staged, dict) or not staged.get("changes"):
        return False
    text = _runner_text(llm_request)
    return bool(text) and "?" not in text and len(text.split()) <= APPROVAL_MAX_WORDS


def thinking_for(state: Any, llm_request: LlmRequest) -> tuple[types.ThinkingConfig, str]:
    """The thinking config for this call and why (recorded on the trace span)."""
    if is_explanation_request(llm_request):
        return EXECUTION_THINKING, "explanation"
    if is_session_edit_request(llm_request):  # "move X to Thursday" is a new edit, not an approval
        return EDIT_THINKING, "session_edit"
    if is_staged_approval(state, llm_request):
        return EXECUTION_THINKING, "approval"
    return DEFAULT_THINKING, "default"


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: LOW for approvals / post-staging prose, MEDIUM for session edits, else HIGH."""
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
