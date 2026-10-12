"""Model callbacks for the coaching agent: per-call thinking policy and check-in table splicing.

Both exist to cut latency without touching report quality:
- Thinking: full (model default) reasoning everywhere except the confirmation call that
  follows a write tool, where there is nothing left to reason about.
- Splicing: the check-in tables are rendered deterministically by `fetch_checkin_data`,
  so the model writes a placeholder instead of re-typing them token by token.
"""

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Thinking policy
# ------------------------------------------------------------------------------
# Tools whose response only needs a short confirmation. Anything else (runner messages,
# facade outputs, get_weather, unknown tools) keeps the model's default reasoning.
WRITE_TOOLS = frozenset({"save_checkin_report", "create_workout", "create_note", "request_new_goal"})
CONFIRMATION_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)


def _last_function_response_names(llm_request: LlmRequest) -> set[str]:
    """Tool names answered by the request's final content (empty if it isn't a tool response)."""
    if not llm_request.contents:
        return set()
    parts = llm_request.contents[-1].parts or []
    return {p.function_response.name for p in parts if p.function_response and p.function_response.name}


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: minimal thinking right after write tools, default otherwise."""
    names = _last_function_response_names(llm_request)
    if names and names <= WRITE_TOOLS:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.thinking_config = CONFIRMATION_THINKING
    return None  # never short-circuits the model call


# ------------------------------------------------------------------------------
# Check-in table splicing
# ------------------------------------------------------------------------------
CHECKIN_PLACEHOLDER = "[[CHECKIN_METRICS]]"
CHECKIN_TABLES_STATE_KEY = "checkin_tables"
LAST_CHECKIN_REPORT_STATE_KEY = "last_checkin_report"


def expand_checkin_placeholder(text: str, tables: Optional[str]) -> str:
    """Replaces the check-in placeholder with the pre-rendered tables (no-op without tables)."""
    if not text or not tables or CHECKIN_PLACEHOLDER not in text:
        return text
    return text.replace(CHECKIN_PLACEHOLDER, tables.strip())


def splice_checkin_tables(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: swaps the placeholder for the check-in tables and keeps the report.

    The finished report is stored in state so `save_checkin_report` can persist it without
    the model re-emitting the whole report as a tool argument.
    """
    content = llm_response.content
    if not content or not content.parts or llm_response.partial:
        return None
    tables = callback_context.state.get(CHECKIN_TABLES_STATE_KEY)
    spliced = False
    for part in content.parts:
        if part.text and not part.thought and CHECKIN_PLACEHOLDER in part.text:
            part.text = expand_checkin_placeholder(part.text, tables)
            spliced = bool(tables)
    if not spliced:
        return None
    callback_context.state[LAST_CHECKIN_REPORT_STATE_KEY] = "".join(
        p.text for p in content.parts if p.text and not p.thought
    )
    return llm_response
