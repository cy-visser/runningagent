"""Model callbacks for the coaching agent.

- Per call: state-driven thinking (COACH_THINKING_LEVEL, default MEDIUM; LOW only for staged approvals,
  the Build Plan opener, and rejected staging retries), with `include_thoughts=True` so the UI receives
  immediate thinking status.
- Internal & skill-gated tools: `fetch_plan_context` and `apply_training_plan` stay runnable in
  `tools_dict` for code dispatches (`plan-builder:intake`, `plan-builder:apply`, `load_skill("plan-builder")`)
  and are never declared as tools to the LLM. `stage_training_plan` is declared only once `plan-builder`
  is loaded in the current turn or while an unapplied `staged_training_plan` sits in session state.
  Declared tool schemas strip redundant Pydantic `title` / null `default` metadata on every call.
- History: thought signatures and thought parts of completed turns are dropped before each call.
"""

from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry import trace

from ...features.plan_builder.fetch_plan_context_tool import resolve_plan_context_window
from ...features.workout_creator.stage_workout_changes_tool import STAGED_CHANGES_STATE_KEY
from ...shared.dates import get_today_date, iso_date
from ...shared.session_state import PLAN_CONTEXT_STATE_KEY, WORKOUT_REPORT_STATE_KEY
from ..model_config import COACH_THINKING_LEVEL
from .quick_actions import (
    BIKE_WORKOUT_SKILL,
    RUN_WORKOUT_SKILL,
    drop_disabled_tool_calls,
    is_plan_intake,
    is_quick_action_report,
    is_synthesis_guard,
)
from .report_tool_guard import track_turn_calls
from .skill_toolset import (
    PLAN_BUILDER_CONTEXT_ARGS,
    PLAN_BUILDER_SKILL,
    has_active_plan_context,
    skill_toolset,
    unapplied_staged_plan_id,
)

# ------------------------------------------------------------------------------
# Internal tools & plan-builder expansion
# ------------------------------------------------------------------------------
INTERNAL_TOOLS = frozenset({"fetch_plan_context", "apply_training_plan", "refresh_race_projection"})
LOAD_SKILL = "load_skill"
FETCH_PLAN_CONTEXT = "fetch_plan_context"
STAGE_TRAINING_PLAN = "stage_training_plan"
STAGE_WORKOUT_CHANGES = "stage_workout_changes"
ANALYZE_WORKOUT = "analyze_workout"
_WORKOUT_SKILLS = frozenset({RUN_WORKOUT_SKILL, BIKE_WORKOUT_SKILL})


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


def align_workout_skill(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: swaps workout-analysis <-> bike-workout-analysis on the active tool step
    when a date-only `analyze_workout` resolved to the other sport family (e.g. 'Analyze oct 15th')."""
    state = callback_context.state if callback_context is not None else None
    report = state.get(WORKOUT_REPORT_STATE_KEY) if state else None
    contents = llm_request.contents or []
    if not isinstance(report, dict) or not contents:
        return None
    last = contents[-1]
    parts = list(last.parts or [])
    if last.role != "user" or not any(
        p.function_response
        and p.function_response.name == ANALYZE_WORKOUT
        and "### Workout Analysis" in str(p.function_response.response or "")
        for p in parts
    ):
        return None
    expected = BIKE_WORKOUT_SKILL if report.get("sport_family") == "bike" else RUN_WORKOUT_SKILL
    changed = False
    for i, part in enumerate(parts):
        resp = part.function_response
        payload = resp.response if (resp and resp.name == LOAD_SKILL and isinstance(resp.response, dict)) else None
        if not payload or payload.get("skill_name") not in _WORKOUT_SKILLS or payload.get("skill_name") == expected:
            continue
        target_skill = next((s for s in skill_toolset._list_skills() if s.name == expected), None)
        if not target_skill:
            continue
        parts[i] = part.model_copy(update={
            "function_response": resp.model_copy(update={
                "response": {"skill_name": expected, "instructions": target_skill.instructions}
            })
        })
        changed = True
    if changed:
        llm_request.contents = [*contents[:-1], last.model_copy(update={"parts": parts})]
    return None


_SCHEMA_MAP_KEYS = frozenset({"properties", "$defs", "definitions"})
_SCHEMA_LIST_KEYS = frozenset({"anyOf", "oneOf", "allOf", "prefixItems"})


def _clean_json_schema(node: Any) -> Any:
    """Strips redundant Pydantic `title` metadata and null `default` entries while preserving property names."""
    if isinstance(node, list):
        return [_clean_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for k, v in node.items():
        if k == "title" or (k == "default" and v is None):
            continue
        if k in _SCHEMA_MAP_KEYS and isinstance(v, dict):
            cleaned[k] = {prop: _clean_json_schema(sub) for prop, sub in v.items()}
        elif k == "items":
            cleaned[k] = _clean_json_schema(v)
        elif k in _SCHEMA_LIST_KEYS and isinstance(v, list):
            cleaned[k] = [_clean_json_schema(sub) for sub in v]
        elif k == "additionalProperties" and isinstance(v, dict):
            cleaned[k] = _clean_json_schema(v)
        else:
            cleaned[k] = v
    return cleaned


def _clean_declaration(decl: types.FunctionDeclaration) -> types.FunctionDeclaration:
    updates: dict[str, Any] = {}
    if isinstance(decl.parameters_json_schema, dict):
        cleaned_json = _clean_json_schema(decl.parameters_json_schema)
        if cleaned_json != decl.parameters_json_schema:
            updates["parameters_json_schema"] = cleaned_json
    if decl.parameters is not None:
        raw_params = decl.parameters.model_dump(exclude_none=True)
        cleaned_params = _clean_json_schema(raw_params)
        if cleaned_params != raw_params or "default" in decl.parameters.model_fields_set:
            updates["parameters"] = types.Schema.model_validate(cleaned_params)
    return decl.model_copy(update=updates) if updates else decl


def hide_internal_tools(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: removes internal/unloaded tools from `config.tools` and strips schema noise."""
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
        kept = [_clean_declaration(d) for d in declarations if d.name not in hidden]
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
    if (
        is_quick_action_report(callback_context.state, callback_context.invocation_id)
        or is_synthesis_guard(callback_context.state, callback_context.invocation_id)
    ):
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


def after_coach_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Single `after_model_callback` composing disabled-tool dropping, plan-builder expansion, and turn tracking."""
    shaped = (
        drop_disabled_tool_calls(callback_context, llm_response)
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


def _has_rejected_staging_step(contents: list[types.Content], tool_name: str) -> bool:
    """True when the current turn is retrying a rejected staging tool call (`staged: 0`)."""
    cut = max((i for i, c in enumerate(contents) if _is_runner_message(c)), default=0)
    for c in contents[cut:]:
        for p in c.parts or []:
            resp = p.function_response
            if resp and resp.name == tool_name:
                payload = resp.response if isinstance(resp.response, dict) else {}
                raw = str(payload.get("result", payload))
                if '"staged": 0' in raw or '"staged":0' in raw:
                    return True
    return False


def _has_workout_creator_step(contents: list[types.Content]) -> bool:
    return _has_rejected_staging_step(contents, STAGE_WORKOUT_CHANGES)


def _has_plan_builder_retry_step(contents: list[types.Content]) -> bool:
    return _has_rejected_staging_step(contents, STAGE_TRAINING_PLAN)


def thinking_for(
    state: Any, llm_request: LlmRequest, invocation_id: Optional[str] = None
) -> tuple[types.ThinkingConfig, str]:
    """The state-driven thinking config for this call and why (recorded on the trace span)."""
    if is_staged_approval(state, llm_request):
        return EXECUTION_THINKING, "approval"
    if is_plan_intake(state, invocation_id):
        return EXECUTION_THINKING, "intake"  # short Build Plan opener: the data is already in the request
    if _has_plan_builder_retry_step(llm_request.contents or []):
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
