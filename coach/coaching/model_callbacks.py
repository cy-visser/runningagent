"""Model callbacks for the coaching agent.

- Thinking: low reasoning for the confirmation that follows a write tool, default otherwise.
- Splicing: replaces table placeholders with the tables from `fetch_checkin_data` / `fetch_trend_data`.
"""

from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ...features.check_in_report.fetch_checkin_data_tool import (
    CHECKIN_PLACEHOLDER,
    CHECKIN_TABLES_STATE_KEY,
)
from ...features.trend_analysis.fetch_trend_data_tool import (
    TREND_PLACEHOLDER,
    TREND_TABLES_STATE_KEY,
)
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


def _last_function_response_names(llm_request: LlmRequest) -> set[str]:
    """Tool names answered by the request's final content (empty if it isn't a tool response)."""
    if not llm_request.contents:
        return set()
    parts = llm_request.contents[-1].parts or []
    return {
        p.function_response.name
        for p in parts
        if p.function_response and p.function_response.name
    }


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: low thinking right after write tools, default otherwise."""
    names = _last_function_response_names(llm_request)
    if names and names <= WRITE_TOOLS:
        llm_request.config = llm_request.config or types.GenerateContentConfig()
        llm_request.config.thinking_config = CONFIRMATION_THINKING
    return None  # never short-circuits the model call


# ------------------------------------------------------------------------------
# Table splicing
# ------------------------------------------------------------------------------
# Placeholder written by the model -> state key holding the pre-rendered tables.
SPLICES = {
    CHECKIN_PLACEHOLDER: CHECKIN_TABLES_STATE_KEY,
    TREND_PLACEHOLDER: TREND_TABLES_STATE_KEY,
}


def expand_placeholders(text: str, state: Any) -> str:
    """Replaces each placeholder with its pre-rendered tables (left as-is when no tables)."""
    for placeholder, key in SPLICES.items():
        tables = state.get(key)
        if text and tables and placeholder in text:
            text = text.replace(placeholder, tables.strip())
    return text


def splice_tables(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: swaps table placeholders for the tables the data tools rendered."""
    content = llm_response.content
    if not content or not content.parts or llm_response.partial:
        return None
    spliced = False
    for part in content.parts:
        if part.text and not part.thought:
            new_text = expand_placeholders(part.text, callback_context.state)
            spliced = spliced or new_text != part.text
            part.text = new_text
    return llm_response if spliced else None
