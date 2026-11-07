"""Deterministic replies after the workout write path, so no LLM call follows staging or applying.

- After `apply_staged_changes`: the confirmation and the table of applied changes.
- After `stage_workout_changes`, when the coach already wrote its recommendations in this turn, or the
  staged set only moves / renames existing workouts (`edit_only`), and nothing is ambiguous or missing:
  one line pointing at the Update TrainingPeaks button.
- After `stage_workout_changes` WITHOUT any coaching text this turn: the LLM call goes ahead with tools
  disabled, at LOW thinking, and an instruction to write a short reasoning (never bare cards).
Anything else (ambiguous / unknown changes, other tools in the same step) goes to the LLM as usual.
"""

import json
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from .apply_staged_changes_tool import apply_staged_changes_tool
from .helpers.staged_changes import confirmation_text
from .stage_workout_changes_tool import stage_workout_changes_tool

APPLY = apply_staged_changes_tool.name
STAGE = stage_workout_changes_tool.name

NOTHING_STAGED_TEXT = "There are no staged changes to apply. Ask me to plan the changes first."
REPLACED_TEXT = (
    "These changes were replaced by a newer set. Use the **Update TrainingPeaks** button on the latest changes."
)


def _payload(response: types.FunctionResponse) -> dict[str, Any]:
    raw = (response.response or {}).get("result")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _reply(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _wrote_text_this_turn(contents: list[types.Content]) -> bool:
    """True when a model content since the runner's last message holds visible text."""
    for content in reversed(contents[:-1]):
        parts = content.parts or []
        if content.role == "user" and any(not p.function_response for p in parts):
            return False  # reached the runner's message
        if content.role == "model" and any(p.text and p.text.strip() and not p.thought for p in parts):
            return True
    return False


def apply_text(payload: dict[str, Any]) -> str:
    reason = payload.get("reason")
    if reason == "nothing_staged":
        return NOTHING_STAGED_TEXT
    if reason == "replaced":
        return REPLACED_TEXT
    return confirmation_text(payload.get("results") or [])


def staged_text(staged: int) -> str:
    noun = "change" if staged == 1 else "changes"
    return f"📋 {staged} {noun} staged. Review them below and press **Update TrainingPeaks** to apply."


def builder_not_staged_text(needs_structure: list[dict]) -> str:
    lines = ["⚠️ **Nothing was staged:** I could not write an exact workout builder for:"]
    lines += [f"- {n.get('date_str')} · {n.get('title')}: {n.get('why')}" for n in needs_structure]
    lines += ["", "Ask me again, ideally with the exact session (reps, lengths, target paces)."]
    return "\n".join(lines)


def write_confirmation_reply(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: coded reply after staging / applying workout changes (no LLM call).

    When changes were staged without any coaching text this turn, the model call goes ahead with tool
    calling disabled and an instruction to write the reasoning, so the runner never gets bare cards.
    """
    contents = llm_request.contents or []
    if not contents:
        return None
    responses = [p.function_response for p in contents[-1].parts or [] if p.function_response]
    if not responses or len(responses) != len(contents[-1].parts or []):
        return None
    names = {r.name for r in responses}
    if names == {APPLY}:
        return _reply("\n\n".join(apply_text(_payload(r)) for r in responses))
    if names == {STAGE} and len(responses) == 1:
        payload = _payload(responses[0])
        if payload.get("give_up"):
            return _reply(builder_not_staged_text(payload.get("needs_structure") or []))
        clean = not any(payload.get(k) for k in ("ambiguous", "needs_structure", "not_found"))
        if payload.get("staged") and clean:
            # The coach already explained, or the runner asked for a plain move / rename: coded line.
            if payload.get("edit_only") or _wrote_text_this_turn(contents):
                return _reply(staged_text(int(payload["staged"])))
            _request_explanation(llm_request)
    return None


EXPLAIN_STAGED_INSTRUCTION = (
    "STAGED WITHOUT EXPLANATION: you staged the changes without explaining them. Write your coaching message now, "
    "in 2-4 sentences: why these changes, tied to this runner's data, goal and north star, and any risk with its "
    "numbers. Do not list the changes: the runner sees them in a table under your message. Call no tools."
)


def is_explanation_request(llm_request: LlmRequest) -> bool:
    """True for the post-staging call turned into the coaching message (tools off, prose only)."""
    config = llm_request.config
    return bool(config and config.system_instruction) and EXPLAIN_STAGED_INSTRUCTION in str(config.system_instruction)


def _request_explanation(llm_request: LlmRequest) -> None:
    """Turns the post-staging model call into the coaching message: tools off, one-off instruction."""
    llm_request.config = llm_request.config or types.GenerateContentConfig()
    llm_request.config.tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode=types.FunctionCallingConfigMode.NONE)
    )
    llm_request.append_instructions([EXPLAIN_STAGED_INSTRUCTION])
