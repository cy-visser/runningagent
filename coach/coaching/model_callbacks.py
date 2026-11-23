"""Model callbacks for the coaching agent.

- Per call: uniform thinking (`COACH_THINKING_LEVEL`, default `MEDIUM`) across all warm coaching turns
  so Vertex's token-0 `THINKING_SI` never flips mid-session and busts the implicit prefix cache; `LOW`
  is used only for the separate `plan-builder:intake` opener, with `include_thoughts=True` for live UI status.
- Internal & skill-gated tools: `fetch_plan_context`, `apply_training_plan`, `refresh_race_projection`,
  and `fetch_trend_data` stay runnable in `tools_dict` for code dispatches (`plan-builder:intake`,
  `plan-builder:apply`, `load_skill("plan-builder")`, `check-in-report:project`, `trend-analysis`)
  and are never declared as tools to the LLM. `stage_training_plan` is declared only once `plan-builder`
  is loaded in the current turn or while an unapplied `staged_training_plan` sits in session state.
  Declared tool schemas strip redundant Pydantic `title` / null `default` metadata on every call.
- History: thought text and empty parts are dropped on all model turns (including active-turn Call 2),
  while `thought_signature` bytes stay verbatim on retained parts (0 billable input tokens; prevents
  completed-turn prefix-cache invalidation across follow-up turns).
"""

from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from opentelemetry import trace

from ...features.plan_builder.fetch_plan_context_tool import resolve_plan_context_window
from ...shared.dates import get_today_date, iso_date
from ...shared.session_state import PLAN_CONTEXT_STATE_KEY, WORKOUT_REPORT_STATE_KEY
from ..model_config import COACH_THINKING_LEVEL
from .quick_actions import (
    BIKE_WORKOUT_SKILL,
    RUN_WORKOUT_SKILL,
    drop_disabled_tool_calls,
    is_plan_intake,
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
INTERNAL_TOOLS = frozenset({
    "fetch_plan_context",
    "apply_training_plan",
    "refresh_race_projection",
    "fetch_trend_data",
})
LOAD_SKILL = "load_skill"
FETCH_PLAN_CONTEXT = "fetch_plan_context"
STAGE_TRAINING_PLAN = "stage_training_plan"
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
        is_plan_intake(callback_context.state, callback_context.invocation_id)
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


def _record_span_usage(llm_response: LlmResponse) -> None:
    """Exposes thinking and prefix-cache token counts on the active OpenTelemetry span."""
    if llm_response.partial:
        return
    usage = getattr(llm_response, "usage_metadata", None)
    if usage is None:
        return
    span = trace.get_current_span()
    thoughts = getattr(usage, "thoughts_token_count", None)
    cached = getattr(usage, "cached_content_token_count", None)
    if isinstance(thoughts, int) and not isinstance(thoughts, bool):
        span.set_attribute("coach.thoughts_tokens", thoughts)
    if isinstance(cached, int) and not isinstance(cached, bool):
        span.set_attribute("coach.cached_tokens", cached)


def after_coach_model(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Single `after_model_callback` composing disabled-tool dropping, plan-builder expansion, and turn tracking."""
    _record_span_usage(llm_response)
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


def _is_runner_message(content: types.Content) -> bool:
    """A user content that is not just tool responses (i.e. a real runner message)."""
    return content.role == "user" and any(not p.function_response for p in content.parts or [])


def thinking_for(
    state: Any, invocation_id: Optional[str] = None
) -> tuple[types.ThinkingConfig, str]:
    """The state-driven thinking config for this call and why (recorded on the trace span).

    Warm coaching turns share `DEFAULT_THINKING` uniformly so changing `thinking_level` never
    invalidates the model's prefix cache; only the cold `plan-builder:intake` opener uses `LOW`.
    """
    if is_plan_intake(state, invocation_id):
        return EXECUTION_THINKING, "intake"  # short Build Plan opener: the data is already in the request
    return DEFAULT_THINKING, "default"


def apply_thinking_policy(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: sets the call's thinking level without mutating the prompt."""
    thinking, reason = thinking_for(callback_context.state, callback_context.invocation_id)
    llm_request.config = llm_request.config or types.GenerateContentConfig()
    llm_request.config.thinking_config = thinking
    span = trace.get_current_span()  # no-op span when tracing is off
    span.set_attribute("coach.thinking_level", thinking.thinking_level.name)
    span.set_attribute("coach.thinking_reason", reason)
    return None  # never short-circuits the model call


# ------------------------------------------------------------------------------
# Stale reasoning in history
# ------------------------------------------------------------------------------
# Gemini model turns may carry `part.thought=True` reasoning text and trailing empty SSE
# `Part(text="")`, which are stripped on ALL model turns (including active-turn Call 2).
# `thought_signature` bytes are preserved verbatim on all retained parts: they cost 0 billable
# input tokens (opaque TYPE_BYTES payload) and stripping them from completed turns invalidates
# implicit prefix caching at that turn.


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
    """before_model_callback: drop thought text and empty SSE parts on all model turns."""
    contents = llm_request.contents or []
    kept = []
    for content in contents:
        if content.role == "model":
            parts = [p for p in content.parts or [] if not p.thought and _has_payload(p)]
            if not parts:
                continue
            content = content.model_copy(update={"parts": parts})
        kept.append(content)
    llm_request.contents = kept
    return None  # never short-circuits the model call
