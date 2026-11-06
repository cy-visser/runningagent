"""Model callbacks for the coaching agent.

- Thinking: low reasoning for the confirmation that follows a write tool, default otherwise.
- Splicing: replaces table placeholders with the tables from `fetch_checkin_data` / `fetch_trend_data`.
- Pruning: stubs tool output / SKILL.md text from earlier turns out of the outgoing model request.
"""

import logging
from typing import Any, Optional

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
WRITE_TOOLS = frozenset({"create_workout", "create_note", "request_new_goal"})
# LOW, not MINIMAL: gemini-3.8-flash (COACH_MODEL) rejects THINKING_LEVEL_MINIMAL with a 400.
CONFIRMATION_THINKING = types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)


def _last_function_response_names(llm_request: LlmRequest) -> set[str]:
    """Tool names answered by the request's final content (empty if it isn't a tool response)."""
    if not llm_request.contents:
        return set()
    parts = llm_request.contents[-1].parts or []
    return {p.function_response.name for p in parts if p.function_response and p.function_response.name}


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
CHECKIN_PLACEHOLDER = "[[CHECKIN_METRICS]]"
CHECKIN_TABLES_STATE_KEY = "checkin_tables"
TREND_PLACEHOLDER = "[[TREND_METRICS]]"
TREND_TABLES_STATE_KEY = "trend_tables"
# Placeholder written by the model -> state key holding the pre-rendered tables.
SPLICES = {CHECKIN_PLACEHOLDER: CHECKIN_TABLES_STATE_KEY, TREND_PLACEHOLDER: TREND_TABLES_STATE_KEY}


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


# ------------------------------------------------------------------------------
# History pruning
# ------------------------------------------------------------------------------
# Raw tool output and SKILL.md text from earlier turns would otherwise be re-sent on every
# model call until compaction (~7k tokens per call after a check-in). The model's own reply
# already summarises them, so they are stubbed out of the OUTGOING request only: session
# events are never mutated (new Content/Part objects are built for pruned entries).
ELIDED_TOOL = "[Output from an earlier turn elided to save context. Call the tool again if you need fresh data.]"
ELIDED_SKILL = "[Skill instructions from an earlier turn elided. Call load_skill again to use this skill.]"


def _current_turn_start(contents: list[types.Content]) -> int:
    """Index of the latest runner text message, i.e. the start of the current invocation."""
    for i in range(len(contents) - 1, -1, -1):
        c = contents[i]
        if c.role == "user" and any(p.text and not p.function_response for p in (c.parts or [])):
            return i
    return 0


def _stub(part: types.Part) -> types.Part:
    fr = part.function_response
    text = ELIDED_SKILL if fr.name == "load_skill" else ELIDED_TOOL
    return types.Part(function_response=types.FunctionResponse(id=fr.id, name=fr.name, response={"result": text}))


def prune_stale_history(llm_request: LlmRequest) -> int:
    """Stubs function responses that precede the current turn. Returns how many were pruned."""
    contents = llm_request.contents or []
    pruned = 0
    for i in range(_current_turn_start(contents)):
        c = contents[i]
        parts = c.parts or []
        if not any(p.function_response for p in parts):
            continue
        new_parts = [_stub(p) if p.function_response else p for p in parts]
        pruned += sum(1 for p in parts if p.function_response)
        contents[i] = types.Content(role=c.role, parts=new_parts)
    return pruned


def before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> Optional[LlmResponse]:
    """before_model_callback: prune earlier-turn payloads, then apply the thinking policy."""
    pruned = prune_stale_history(llm_request)
    if pruned:
        logger.debug("Pruned %d earlier-turn function responses from the model request", pruned)
    return apply_thinking_policy(callback_context, llm_request)

