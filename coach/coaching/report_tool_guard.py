"""Keeps report data tools from being used as data lookups, and gates UI-only tools.

`fetch_checkin_data` and `fetch_plan_audit_data` write a web report payload to state, which the web
app renders as a full report card. Called as a lookup in a follow-up turn (e.g. to find workout ids
for `stage_workout_changes`), they would open a report the runner never asked for. `fetch_trend_data`
is hidden from LLM declarations and only allowed when dispatched by the Trend Analysis dashboard button.

`track_turn_calls` (after_model_callback) records each model step's function calls of the current
invocation before its tools run. `guard_report_tools` (before_tool_callback) only lets a report tool run
when it is the turn's report: no other skill was loaded in this turn and no earlier step of the turn
called anything but `load_skill` of the report's own skill. Otherwise the tool is skipped (no state
write, no report card) and the model is told to answer from the data in the conversation.
"""

from datetime import date
import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from opentelemetry import trace

from ...features.schedule_lookup.get_schedule_tool import PRESCRIPTION_MAX_DAYS, resolve_schedule_window
from ...shared.dates import iso_date
from .quick_actions import (
    SYNTHESIS_GUARD_STATE_KEY,
    has_action_or_event_intent,
    is_force_prose,
    is_plan_intake,
    is_synthesis_guard,
    is_trend_synthesis,
)

TURN_CALLS_STATE_KEY = "temp:turn_calls"
LOAD_SKILL = "load_skill"
FETCH_PLAN_CONTEXT = "fetch_plan_context"
FETCH_TREND_DATA = "fetch_trend_data"
GET_SCHEDULE = "get_schedule"
PLAN_BUILDER_SKILL = "plan-builder"
ANALYZE_WORKOUT = "analyze_workout"
_APPLY_TOOLS = frozenset({"apply_staged_changes", "apply_training_plan"})
_SCHEDULE_HEADER_RE = re.compile(r"^### Schedule \((\d{4}-\d{2}-\d{2})\s*[–-]\s*(\d{4}-\d{2}-\d{2})\)")
_SCHEDULE_BLOCK_RE = re.compile(r'<report tool="get_schedule"(?P<attrs>[^>]*)>\s*(?P<body>.*?)\s*</report>', re.DOTALL)
_AUDIT_BLOCK_RE = re.compile(r'<report tool="fetch_plan_audit_data"[^>]*>\s*(?P<body>.*?)\s*</report>', re.DOTALL)
_AUDIT_WEEK_RE = re.compile(
    r"^\*\s+\*\*(?P<s_iso>\d{4}-\d{2}-\d{2})\s*[–-]\s*(?:(?P<e_iso>\d{4}-\d{2}-\d{2})|(?P<e_mon>[A-Za-z]{3})\s+(?P<e_day>\d{1,2}))\*\*",
    re.MULTILINE,
)
_SHORT_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_EXPLICIT_REFRESH_RE = re.compile(r"\b(?:refresh|reload|re-?check|check\s+again|pull\s+up\s+again)\b", re.IGNORECASE)

# report data tool -> the skill whose report it renders
REPORT_TOOL_SKILLS = {
    "fetch_checkin_data": "check-in-report",
    "fetch_plan_audit_data": "plan-audit",
}
_SYNTHESIS_TOOLS = frozenset({*REPORT_TOOL_SKILLS, "fetch_nutrition_context", "get_schedule"})
_RACE_RE = re.compile(r"\b(?:race|parkrun|time\s+trial|tt)\b", re.IGNORECASE)

_REPORT_NAMES = {
    "fetch_checkin_data": "check-in report",
    "fetch_plan_audit_data": "plan audit report",
}


def _step_calls(llm_response: LlmResponse) -> list[dict]:
    content = llm_response.content
    calls = []
    for part in (content.parts if content else None) or []:
        fc = part.function_call
        if fc and fc.name:
            call = {"name": fc.name}
            if fc.name == LOAD_SKILL:
                call["skill"] = (fc.args or {}).get("skill_name")
            calls.append(call)
    return calls


def track_turn_calls(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """after_model_callback: appends this model step's function calls to the turn's record."""
    if llm_response.partial:
        return None
    calls = _step_calls(llm_response)
    if not calls:
        return None
    invocation_id = callback_context.invocation_id
    record = callback_context.state.get(TURN_CALLS_STATE_KEY)
    steps = list(record["steps"]) if isinstance(record, dict) and record.get("invocation") == invocation_id else []
    steps.append(calls)
    callback_context.state[TURN_CALLS_STATE_KEY] = {"invocation": invocation_id, "steps": steps}
    return None


def _turn_steps(tool_context: ToolContext) -> list[list[dict]]:
    record = tool_context.state.get(TURN_CALLS_STATE_KEY)
    if isinstance(record, dict) and record.get("invocation") == tool_context.invocation_id:
        return record.get("steps") or []
    return []


def is_turn_report(tool_name: str, steps: list[list[dict]]) -> bool:
    """True when `tool_name` runs as this turn's report, not as a lookup.

    `steps` are the turn's model steps; the last one holds the current call.
    """
    skill = REPORT_TOOL_SKILLS[tool_name]
    for call in (c for step in steps for c in step):
        if call["name"] == LOAD_SKILL and call.get("skill") != skill:
            return False  # another skill drives this turn
    for call in (c for step in steps[:-1] for c in step):
        if not (call["name"] == LOAD_SKILL and call.get("skill") == skill):
            return False  # other work came first: this would be a lookup
    return True


def is_plan_builder_turn(tool_context: ToolContext) -> bool:
    """True when `fetch_plan_context` was dispatched by `plan-builder:intake` or `load_skill('plan-builder')`."""
    if is_plan_intake(tool_context.state, tool_context.invocation_id):
        return True
    return any(
        call["name"] == LOAD_SKILL and call.get("skill") == PLAN_BUILDER_SKILL
        for step in _turn_steps(tool_context)
        for call in step
    )


def blocked_message(tool_name: str) -> str:
    return (
        f"{tool_name} was not run: it renders the {_REPORT_NAMES[tool_name]} for the runner and is only for "
        "that report when the runner asks for it. Answer from the data already in this conversation (planned "
        "sessions carry their [workout_id]); stage_workout_changes resolves a session by date and sport without "
        "an id."
    )


def _audit_window_from_text(text: str) -> Optional[tuple[str, str]]:
    stripped = text.lstrip()
    if not stripped.startswith("### Training Plan Audit"):
        return None
    matches = list(_AUDIT_WEEK_RE.finditer(stripped))
    if not matches:
        return None
    start_iso = matches[0].group("s_iso")
    last = matches[-1]
    if last.group("e_iso"):
        return start_iso, last.group("e_iso")
    try:
        s_day = date.fromisoformat(last.group("s_iso"))
        month = _SHORT_MONTHS.get((last.group("e_mon") or "").lower())
        if not month:
            return None
        year = s_day.year + 1 if month < s_day.month else s_day.year
        end_iso = date(year, month, int(last.group("e_day"))).isoformat()
        return start_iso, end_iso
    except ValueError:
        return None


def _covering_schedule(
    tool_context: ToolContext, args: dict[str, Any]
) -> Optional[tuple[str, str, str, str, str]]:
    """Returns `(req_start, req_end, prev_start, prev_end, source)` when an active Schedule or Plan Audit covers `args`."""
    # Pre-dispatched standalone schedule commands (`"Pull up next week"`) or explicit refresh requests run live.
    if is_synthesis_guard(tool_context.state, getattr(tool_context, "invocation_id", None)):
        return None
    user_content = getattr(tool_context, "user_content", None)
    user_text = " ".join(p.text for p in (user_content.parts or []) if p.text).strip() if user_content else ""
    if _EXPLICIT_REFRESH_RE.search(user_text):
        return None

    session = getattr(tool_context, "session", None)
    events = getattr(session, "events", None) if session is not None else None
    if not events:
        return None

    want_details = bool(args.get("include_details"))
    q_start, q_end, _ = resolve_schedule_window(
        args.get("start_date"), args.get("end_date"), include_details=want_details
    )
    req_s, req_e = iso_date(q_start), iso_date(q_end)

    detail_call_ids: set[str] = set()
    active: list[tuple[str, str, bool]] = []
    active_audits: list[tuple[str, str]] = []
    for ev in events:
        for part in (ev.content.parts if ev.content else None) or []:
            fc = part.function_call
            if fc and fc.name == GET_SCHEDULE and fc.id and bool((fc.args or {}).get("include_details")):
                detail_call_ids.add(fc.id)
            resp = part.function_response
            if resp and resp.name in _APPLY_TOOLS:
                active.clear()
                active_audits.clear()
            elif resp and resp.name == GET_SCHEDULE:
                payload = resp.response or {}
                raw_text = payload.get("result", payload) if isinstance(payload, dict) else payload
                m = _SCHEDULE_HEADER_RE.match(str(raw_text or "").lstrip())
                if m:
                    active.append((m.group(1), m.group(2), (resp.id or "") in detail_call_ids))
            elif resp and resp.name == "fetch_plan_audit_data":
                payload = resp.response or {}
                raw_text = payload.get("result", payload) if isinstance(payload, dict) else payload
                audit_win = _audit_window_from_text(str(raw_text or ""))
                if audit_win:
                    active_audits.append(audit_win)
            elif part.text and not getattr(part, "thought", False):
                if 'tool="get_schedule"' in part.text:
                    for bm in _SCHEDULE_BLOCK_RE.finditer(part.text):
                        hm = _SCHEDULE_HEADER_RE.match(bm.group("body"))
                        if hm:
                            active.append((hm.group(1), hm.group(2), "include_details=True" in bm.group("attrs")))
                if 'tool="fetch_plan_audit_data"' in part.text:
                    for am in _AUDIT_BLOCK_RE.finditer(part.text):
                        audit_win = _audit_window_from_text(am.group("body"))
                        if audit_win:
                            active_audits.append(audit_win)

    for prev_s, prev_e, prev_details in reversed(active):
        if prev_s <= req_s and req_e <= prev_e and (not want_details or prev_details):
            return req_s, req_e, prev_s, prev_e, "### Schedule"
    if not want_details and (q_end - q_start).days > PRESCRIPTION_MAX_DAYS:
        for prev_s, prev_e in reversed(active_audits):
            if prev_s <= req_s and req_e <= prev_e:
                return req_s, req_e, prev_s, prev_e, "### Training Plan Audit"
    return None


def guard_report_tools(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """before_tool_callback: skips report tools used as lookups, deduplicates sub-window schedule checks,
    and blocks internal/UI-only or force-prose synthesis tool calls."""
    if is_force_prose(tool_context.state, getattr(tool_context, "invocation_id", None)):
        return {
            "result": (
                f"{tool.name} was not run: the data for this turn is already loaded above. "
                "Reply directly in prose from the data in this conversation (if a specific detail is "
                "not shown, state that plainly)."
            )
        }
    if tool.name == GET_SCHEDULE:
        covered = _covering_schedule(tool_context, args or {})
        if covered is not None:
            req_s, req_e, prev_s, prev_e, source = covered
            trace.get_current_span().set_attribute("coach.skipped_duplicate_schedule", f"{req_s}..{req_e}")
            if source == "### Training Plan Audit":
                return {
                    "result": (
                        f"get_schedule was not run: {req_s}..{req_e} is already in the active "
                        f"### Training Plan Audit ({prev_s} – {prev_e}) in this conversation. Answer directly from "
                        "that audit (call get_schedule on a <= 14-day window only when a specific workout's step "
                        "prescription is needed)."
                    )
                }
            return {
                "result": (
                    f"get_schedule was not run: {req_s}..{req_e} is already in the active "
                    f"### Schedule ({prev_s} – {prev_e}) in this conversation. Answer directly from "
                    "that schedule (call get_schedule with include_details=True only when a planned "
                    "workout's step targets are not shown there)."
                )
            }
        return None
    if tool.name == FETCH_PLAN_CONTEXT:
        if is_plan_builder_turn(tool_context):
            return None
        return {
            "result": (
                "fetch_plan_context is internal to plan-builder and was not run. Answer directly from "
                "the profile block and the data already in this conversation."
            )
        }
    if tool.name == FETCH_TREND_DATA:
        if is_trend_synthesis(tool_context.state, tool_context.invocation_id):
            return None
        return {
            "result": (
                "fetch_trend_data is triggered only by the Trend Analysis dashboard button and was not run. "
                "Use fetch_plan_audit_data + plan-audit for multi-week/month plan audits, or answer directly "
                "from the profile block and the data already in this conversation."
            )
        }
    if tool.name not in REPORT_TOOL_SKILLS:
        return None
    if is_turn_report(tool.name, _turn_steps(tool_context)):
        return None
    return {"result": blocked_message(tool.name)}


def mark_report_synthesis(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext, tool_response: Any
) -> Optional[dict]:
    """after_tool_callback: guards Step 2 of read-only LLM-routed report turns so it ends on prose while keeping Call 1's prefix cache intact."""
    if tool.name not in _SYNTHESIS_TOOLS and tool.name != ANALYZE_WORKOUT:
        return None
    invocation_id = getattr(tool_context, "invocation_id", None)
    if (
        not invocation_id
        or is_plan_intake(tool_context.state, invocation_id)
        or is_synthesis_guard(tool_context.state, invocation_id)
    ):
        return None
    user_content = getattr(tool_context, "user_content", None)
    if user_content is None:
        return None
    user_text = " ".join(p.text for p in (user_content.parts or []) if p.text).strip()
    if has_action_or_event_intent(user_text):
        return None
    res_obj = tool_response.get("result", tool_response) if isinstance(tool_response, dict) else tool_response
    res_str = res_obj if isinstance(res_obj, str) else str(res_obj or "")
    if res_str.startswith(f"{tool.name} was not run:"):
        return None
    if tool.name == ANALYZE_WORKOUT:
        if "### Workout Analysis" not in res_str or _RACE_RE.search(res_str) or _RACE_RE.search(user_text):
            return None
    steps = _turn_steps(tool_context)
    if not steps or any(c["name"] not in (LOAD_SKILL, tool.name) for step in steps for c in step):
        return None
    tool_context.state[SYNTHESIS_GUARD_STATE_KEY] = invocation_id
    trace.get_current_span().set_attribute("coach.report_synthesis_guard", tool.name)
    return None
