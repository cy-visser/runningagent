"""Model callbacks for the coaching agent.

- Per call: thinking (COACH_THINKING_LEVEL, default MEDIUM; LOW for staged approvals, short follow-up
  execution confirmations like 'yes update it', and the Build Plan opener), with `include_thoughts=True` so
  the UI receives immediate thinking status.
- Internal & skill-gated tools: `fetch_plan_context` and `apply_training_plan` stay runnable in
  `tools_dict` for code dispatches (`plan-builder:intake`, `plan-builder:apply`, `load_skill("plan-builder")`)
  and are never declared as tools to the LLM. `stage_training_plan` is declared only once `plan-builder`
  is loaded in the current turn or while an unapplied `staged_training_plan` sits in session state.
- History: thought signatures and thought parts of completed turns are dropped before each call.
"""

import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry import trace

from ...features.plan_builder.fetch_plan_context_tool import resolve_plan_context_window
from ...features.workout_creator.stage_workout_changes_tool import STAGED_CHANGES_STATE_KEY
from ...shared.dates import get_today_date, iso_date
from ...shared.session_state import PLAN_CONTEXT_STATE_KEY
from ...shared.workout_builder import needs_builder
from ..model_config import COACH_THINKING_LEVEL
from .quick_actions import drop_disabled_tool_calls, is_plan_intake, is_quick_action_report
from .report_tool_guard import track_turn_calls
from .skill_toolset import (
    PLAN_BUILDER_CONTEXT_ARGS,
    PLAN_BUILDER_SKILL,
    has_active_plan_context,
    unapplied_staged_plan_id,
)

# ------------------------------------------------------------------------------
# Internal tools & plan-builder expansion
# ------------------------------------------------------------------------------
INTERNAL_TOOLS = frozenset({"fetch_plan_context", "apply_training_plan"})
LOAD_SKILL = "load_skill"
FETCH_PLAN_CONTEXT = "fetch_plan_context"
STAGE_TRAINING_PLAN = "stage_training_plan"
WORKOUT_CREATOR_SKILL = "workout-creator"
STAGE_WORKOUT_CHANGES = "stage_workout_changes"


def _has_unapplied_staged_plan(state: Any) -> bool:
    return bool(unapplied_staged_plan_id(state))


def _has_plan_builder_in_context(state: Any, contents: list[types.Content]) -> bool:
    if _has_unapplied_staged_plan(state) or has_active_plan_context(contents):
        return True
    cut = max((i for i, c in enumerate(contents) if _is_runner_message(c)), default=0)
    return any(
        p.function_call
        and p.function_call.name == LOAD_SKILL
        and (p.function_call.args or {}).get("skill_name") == PLAN_BUILDER_SKILL
        for c in contents[cut:]
        for p in c.parts or []
    )


def hide_internal_tools(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: removes internal/unloaded tools from `config.tools` (keeps `tools_dict` runnable)."""
    config = llm_request.config
    if not config or not config.tools:
        return None
    state = callback_context.state if callback_context is not None else None
    hidden = set(INTERNAL_TOOLS)
    if not _has_plan_builder_in_context(state, llm_request.contents or []):
        hidden.add(STAGE_TRAINING_PLAN)
    kept_tools = []
    for tool in config.tools:
        declarations = getattr(tool, "function_declarations", None)
        if not declarations:
            kept_tools.append(tool)
            continue
        kept = [d for d in declarations if d.name not in hidden]
        if kept:
            kept_tools.append(tool.model_copy(update={"function_declarations": kept}))
    config.tools = kept_tools
    return None


def _can_reuse_plan_context(callback_context: CallbackContext, ctx_args: dict[str, Any]) -> bool:
    """True when an active `fetch_plan_context` in this session already covers `ctx_args`."""
    state = getattr(callback_context, "state", None)
    if not state:
        return False
    cached = state.get(PLAN_CONTEXT_STATE_KEY)
    if not isinstance(cached, dict):
        return False
    today = get_today_date()
    if cached.get("today") != iso_date(today):
        return False
    profile = state.get("user_profile") or {}
    start, end, mode = resolve_plan_context_window(
        profile,
        today,
        str(ctx_args.get("start_date") or ""),
        str(ctx_args.get("end_date") or ""),
        str(ctx_args.get("mode") or "new"),
    )
    if (iso_date(start), iso_date(end), mode) != (
        cached.get("start_date"),
        cached.get("end_date"),
        cached.get("mode"),
    ):
        return False
    session = getattr(callback_context, "session", None)
    if session is not None and getattr(session, "events", None) is not None:
        return has_active_plan_context([e.content for e in session.events if e.content])
    return True


def expand_plan_builder_context(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Appends `fetch_plan_context` in code when `load_skill(skill_name="plan-builder")` needs fresh context."""
    content = llm_response.content
    if llm_response.partial or not content or not content.parts:
        return None
    if is_quick_action_report(callback_context.state, callback_context.invocation_id):
        return None
    called = {p.function_call.name for p in content.parts if p.function_call}
    if FETCH_PLAN_CONTEXT in called:
        return None
    for i, part in enumerate(content.parts):
        fc = part.function_call
        if not fc or fc.name != LOAD_SKILL:
            continue
        raw_args = fc.args or {}
        if raw_args.get("skill_name") != PLAN_BUILDER_SKILL:
            continue
        ctx_args = {k: raw_args[k] for k in PLAN_BUILDER_CONTEXT_ARGS if raw_args.get(k) not in (None, "")}
        if _can_reuse_plan_context(callback_context, ctx_args):
            return None
        # Insert directly after `load_skill` so SSE's trailing `Part(text="")` never splits the parallel call run
        # (Gemini validates `thought_signature` on the first `functionCall` of each contiguous `functionCall` run).
        added = types.Part(function_call=types.FunctionCall(name=FETCH_PLAN_CONTEXT, args=ctx_args))
        return llm_response.model_copy(
            update={
                "content": content.model_copy(
                    update={"parts": [*content.parts[: i + 1], added, *content.parts[i + 1 :]]}
                )
            }
        )
    return None


def _is_blind_workout_change(item: Any) -> bool:
    """True when a Run/Bike workout change lacks `code`, `structure`, and a pure move/rename `workout_id`."""
    if not isinstance(item, dict):
        return False
    if str(item.get("kind") or "workout").strip().lower() == "note" or item.get("delete"):
        return False
    if item.get("code") not in (None, "") or item.get("structure") not in (None, "", {}):
        return False
    if not needs_builder(item.get("sport")):
        return False
    pure_move_or_rename = (
        bool(str(item.get("workout_id") or "").strip())
        and item.get("distance_km") in (None, "")
        and item.get("duration_minutes") in (None, "")
    )
    return not pure_move_or_rename


def drop_premature_staging(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Drops a blind `stage_workout_changes` emitted in the same step as `load_skill('workout-creator')`."""
    content = llm_response.content
    if llm_response.partial or not content or not content.parts:
        return None
    if is_quick_action_report(callback_context.state, callback_context.invocation_id):
        return None
    loads_wc = any(
        p.function_call
        and p.function_call.name == LOAD_SKILL
        and (p.function_call.args or {}).get("skill_name") == WORKOUT_CREATOR_SKILL
        for p in content.parts
    )
    if not loads_wc:
        return None
    stage_parts = [
        p for p in content.parts
        if p.function_call and p.function_call.name == STAGE_WORKOUT_CHANGES
    ]
    if not stage_parts:
        return None
    if not any(
        _is_blind_workout_change(c)
        for p in stage_parts
        for c in ((p.function_call.args or {}).get("changes") or [])
    ):
        return None
    sig = next((p.thought_signature for p in content.parts if p.function_call and p.thought_signature), None)
    kept: list[types.Part] = []
    restored_sig = False
    for p in content.parts:
        if p.function_call and p.function_call.name == STAGE_WORKOUT_CHANGES:
            continue
        if p.function_call and sig and not restored_sig:
            p = p.model_copy(update={"thought_signature": sig}) if not p.thought_signature else p
            restored_sig = True
        kept.append(p)
    trace.get_current_span().set_attribute("coach.dropped_premature_staging", True)
    return llm_response.model_copy(update={"content": content.model_copy(update={"parts": kept})})


def after_coach_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Single `after_model_callback` composing disabled-tool dropping, premature-staging guard, plan-builder expansion, and turn tracking."""
    shaped = (
        drop_disabled_tool_calls(callback_context, llm_response)
        or drop_premature_staging(callback_context, llm_response)
        or expand_plan_builder_context(callback_context, llm_response)
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
    r"|^(?:update|stage|apply|schedule|make|implement)\s+"
    r"(?:it|them|those|that|all(?:\s+of\s+(?:it|them|those))?|my\s+(?:calendar|plan|schedule)"
    r"|(?:(?:all|your|the|those|these)\s+)+(?:plan|sessions|workouts|calendar|schedule|recommendations|changes|adjustments|fixes|edits|suggestions))\b",
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


def _has_workout_creator_step(contents: list[types.Content]) -> bool:
    """True once the current turn loaded `workout-creator` or is retrying a rejected staging (`staged: 0`)."""
    cut = max((i for i, c in enumerate(contents) if _is_runner_message(c)), default=0)
    for c in contents[cut:]:
        for p in c.parts or []:
            if (
                p.function_call
                and p.function_call.name == LOAD_SKILL
                and (p.function_call.args or {}).get("skill_name") == WORKOUT_CREATOR_SKILL
            ):
                return True
            resp = p.function_response
            if resp and resp.name == STAGE_WORKOUT_CHANGES:
                payload = resp.response if isinstance(resp.response, dict) else {}
                raw = str(payload.get("result", payload))
                if '"staged": 0' in raw or '"staged":0' in raw:
                    return True
    return False


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
    if _has_plan_builder_in_context(state, llm_request.contents or []):
        return EXECUTION_THINKING, "plan_builder"
    if _has_workout_creator_step(llm_request.contents or []):
        return EXECUTION_THINKING, "workout_creator"
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
