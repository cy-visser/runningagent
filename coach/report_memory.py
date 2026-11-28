"""Report memory: report output survives session compaction, verbatim and only the latest of each kind.

Session history is compacted every N runner messages (`agent.py`). ADK's `LlmEventSummarizer` cuts
every tool result to 2,000 characters and paraphrases the rest, so a plan audit's calendar (with
its [workout_id]s) or a workout analysis's numbers used to be lost after compaction.

- `ReportMemorySummarizer`: the summary of a compacted range is the LLM's summary of the
  conversation (report output and skill instructions left out of its input) followed by one part
  with the latest output of each report tool in that range, verbatim, inside `<report ...>` blocks.
- `keep_latest_reports_and_skills` (before_model_callback): ADK keeps every earlier summary in the
  prompt, and recent raw turns hold full tool results. Per request, only the latest output of each
  report tool and the latest instructions of each skill are kept; older copies are dropped
  (summary blocks) or replaced by a one-line pointer (raw responses, so every function call keeps
  its response). A staged set replaced by a later staging (no apply in between) is cut to a pointer
  too, call and response, so only the current staged set is verbatim. What the app already settled
  is compacted: an apply result becomes one line per change (or a counts + window line for > 12 items)
  and the staged set it applied a stub (its `message` kept). Skill instructions from completed turns
  become a stub (`load_skill` sits after report data in tool responses, preserving prefix caching on
  `system_instruction + tools + report_data` while saving ~1-1.4k uncached tokens on follow-up turns).
  An applied training plan's spec becomes a stub (its `message` kept) and its per-week apply events
  collapse into one summary line. The stored session (and so the UI) is never changed.
"""

import json
import re
from datetime import datetime, timezone
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.events.event import Event
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

# Report tools whose latest output is kept verbatim (one per tool: the latest audit, check-in,
# trend and workout analysis).
REPORT_LABELS = {
    "fetch_plan_audit_data": "Plan audit",
    "get_schedule": "Schedule",
    "analyze_workout": "Workout analysis",
    "fetch_checkin_data": "Check-in",
    "fetch_trend_data": "Trend analysis",
}
LOAD_SKILL = "load_skill"
STAGE = "stage_workout_changes"
APPLY = "apply_staged_changes"
REPLACED_STAGE_ARGS = {"changes": "[replaced by a later staging below]"}
REPLACED_STAGE_RESULT = {"result": "[replaced: the current staged set is further below]"}
APPLIED_STAGE_CHANGES = "[applied: see the apply_staged_changes result below]"
APPLIED_STAGE_RESULT = {"result": "[applied: see the apply_staged_changes result below]"}
STALE_SKILL_STUB = "[completed-turn skill rubric omitted; call load_skill only when generating a new report]"
PLAN_STAGE = "stage_training_plan"
PLAN_APPLY = "apply_training_plan"
PLAN_CONTEXT = "fetch_plan_context"
REPLACED_PLAN_STUB = "[replaced by a later staged plan below]"
REPLACED_PLAN_RESULT = {"result": "[replaced: the current staged plan is further below]"}
APPLIED_PLAN_STUB = "[applied plan: {weeks} weeks, {sessions} sessions, see the apply summary]"
APPLIED_PLAN_CONTEXT_STUB = "[plan context settled: see the applied training plan summary below]"
STALE_GUARD_STUB = "[{tool} skipped earlier]"
MAX_SUMMARY_OUTPUT_TOKENS = 450
# Matches `SYNTHETIC_THOUGHT_SIGNATURE` in `coach/coaching/quick_actions.py` (identifies pre-dispatched calls).
_SYNTHETIC_THOUGHT_SIG = b"skip_thought_signature_validator"

_REPORT_BLOCK_RE = re.compile(r'\n*<report tool="(?P<tool>[^"]+)"[^>]*>.*?</report>', re.DOTALL)
_NOT_RUN_RE = re.compile(r"^\w+\s+was\s+not\s+run:", re.IGNORECASE)
_SCHEDULE_HEADER_RE = re.compile(r"^### Schedule \((\d{4}-\d{2}-\d{2})\s*[–-]\s*(\d{4}-\d{2}-\d{2})\)")
REPORT_MEMORY_HEADER = (
    "REPORT MEMORY: the latest report output from this part of the conversation, verbatim. Use it to "
    "answer follow-ups (planned sessions carry their [workout_id])."
)

COACH_SUMMARY_PROMPT = (
    "Summarize this runner-coach conversation in <= 160 words using compact bullets. Preserve: "
    "(1) runner requests, preferences, constraints, and dates; "
    "(2) coach recommendations and agreed decisions; "
    "(3) TrainingPeaks changes strictly separated into APPLIED (confirmed by apply_staged_changes / "
    "apply_training_plan) vs STAGED/PROPOSED (never mark staged or discussed ideas as applied); "
    "(4) open questions. Report data and skill instructions are stored separately: do not restate "
    "report numbers or calendars.\n\n"
    "{conversation_history}"
)


# ------------------------------------------------------------------------------
# Report blocks
# ------------------------------------------------------------------------------

def result_text(response: types.FunctionResponse) -> str:
    """The text a tool returned to the coach (`{"result": ...}` for function tools)."""
    payload = response.response or {}
    value = payload.get("result", payload) if isinstance(payload, dict) else payload
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _is_usable(text: str) -> bool:
    stripped = text.lstrip()
    return bool(stripped) and not stripped.startswith("Error") and not _NOT_RUN_RE.match(stripped)


def _schedule_window(text: str) -> Optional[tuple[str, str]]:
    m = _SCHEDULE_HEADER_RE.match(text.lstrip())
    return (m.group(1), m.group(2)) if m else None


def _args_label(args: Optional[dict]) -> str:
    return ", ".join(f"{k}={v}" for k, v in (args or {}).items() if v not in (None, ""))


def _run_label(timestamp: Optional[float]) -> str:
    if not timestamp:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def report_block(tool: str, args: Optional[dict], timestamp: Optional[float], text: str) -> str:
    attrs = f'tool="{tool}" label="{REPORT_LABELS.get(tool, tool)}"'
    if _args_label(args):
        attrs += f' args="{_args_label(args).replace(chr(34), chr(39))}"'
    if _run_label(timestamp):
        attrs += f' run="{_run_label(timestamp)}"'
    return f"<report {attrs}>\n{text.strip()}\n</report>"


def latest_report_blocks(events: list[Event]) -> list[str]:
    """One verbatim block per report tool: its latest usable output in `events`."""
    calls: dict[str, dict] = {}
    latest: dict[str, str] = {}
    for event in events:
        for part in (event.content.parts if event.content else None) or []:
            if part.function_call and part.function_call.id:
                calls[part.function_call.id] = part.function_call.args or {}
            response = part.function_response
            if not response or response.name not in REPORT_LABELS:
                continue
            text = result_text(response)
            if _is_usable(text):
                latest[response.name] = report_block(
                    response.name, calls.get(response.id or ""), event.timestamp, text
                )
    return [latest[tool] for tool in REPORT_LABELS if tool in latest]


# ------------------------------------------------------------------------------
# Summarizer
# ------------------------------------------------------------------------------

def _placeholder(response: types.FunctionResponse) -> Optional[str]:
    if response.name in REPORT_LABELS or response.name == PLAN_CONTEXT:
        return "[report output kept verbatim in the report memory]"
    if response.name == LOAD_SKILL:
        return "[skill instructions omitted]"
    return None


def _is_mid_plan_apply(events: list[Event]) -> bool:
    """True when the compaction slice ends on an incomplete per-week `apply_training_plan` event."""
    for event in reversed(events):
        if not event.content or not event.content.parts:
            continue
        for part in reversed(event.content.parts):
            response = part.function_response
            if not response:
                continue
            if response.name != PLAN_APPLY:
                return False
            state = _result_json(response).get("applied_training_plan")
            return isinstance(state, dict) and state.get("done") is False
    return False


def _prepare_events_for_summary(events: list[Event]) -> list[Event]:
    """Strips thoughts, skill loads, superseded stagings, and raw apply JSON before LLM summarization."""
    indexed = [(idx, e) for idx, e in enumerate(events) if e.content and e.content.parts and not (
        e.actions and e.actions.compaction
    )]
    if not indexed:
        return events
    contents = [e.content for _, e in indexed]
    keys = _call_response_keys(contents)
    replaced, applied = staging_status(contents, keys)
    replaced = replaced | superseded_failed_stagings(contents, keys, turn_start=len(contents))
    plans = plan_status(contents, keys, turn_start=len(contents))

    compacted_by_idx: dict[int, Optional[Event]] = {}
    for ci, (ev_idx, event) in enumerate(indexed):
        parts: list[types.Part] = []
        changed = False
        for pi, part in enumerate(event.content.parts or []):
            if getattr(part, "thought", False):
                changed = True
                continue
            call, response = part.function_call, part.function_response
            key = keys.get((ci, pi))
            if (call and call.name == LOAD_SKILL) or (response and response.name == LOAD_SKILL):
                changed = True
                continue
            if response and _NOT_RUN_RE.match(result_text(response).lstrip()):
                changed = True
                continue
            if _is_collapsed_apply(part, key, plans):
                changed = True
                continue
            if (call and call.name == STAGE and key in replaced) or (
                response and response.name == STAGE and key in replaced
            ):
                changed = True
                continue
            if response and response.name == STAGE and key in applied:
                changed = True  # `apply_staged_changes` carries the compact applied summary right below
                continue
            if call and call.name == PLAN_STAGE and key in plans["replaced"]:
                changed = True
                continue
            if response and response.name == PLAN_STAGE and key in plans["replaced"]:
                changed = True
                continue
            note = _placeholder(response) if response else None
            if note:
                part = part.model_copy(
                    update={"function_response": response.model_copy(update={"response": {"result": note}})}
                )
                changed = True
            else:
                new_part = (
                    _compact_plan(part, key, plans, ci)
                    or _compact_applied(part, key, applied)
                )
                if new_part is not None and new_part is not part:
                    part = new_part
                    changed = True
            if not (part.text or part.function_call or part.function_response or part.inline_data or part.file_data):
                changed = True
                continue
            parts.append(part)
        if not parts:
            compacted_by_idx[ev_idx] = None
        elif changed:
            compacted_by_idx[ev_idx] = event.model_copy(
                update={"content": event.content.model_copy(update={"parts": parts})}
            )
        else:
            compacted_by_idx[ev_idx] = event

    out: list[Event] = []
    for idx, event in enumerate(events):
        if idx not in compacted_by_idx:
            out.append(event)
        elif compacted_by_idx[idx] is not None:
            out.append(compacted_by_idx[idx])
    return out


class _CappedSummarizerLlm:
    """Wraps a summarizer LLM to enforce `MAX_SUMMARY_OUTPUT_TOKENS` on every compaction call."""

    def __init__(self, inner: BaseLlm):
        self._inner = inner
        self.model = getattr(inner, "model", "")

    def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        cfg = llm_request.config or types.GenerateContentConfig()
        llm_request.config = cfg.model_copy(update={"max_output_tokens": MAX_SUMMARY_OUTPUT_TOKENS})
        return self._inner.generate_content_async(llm_request, stream=stream)


class ReportMemorySummarizer(LlmEventSummarizer):
    """LLM summary of the conversation plus the latest report output, verbatim."""

    def __init__(self, llm: BaseLlm, prompt_template: Optional[str] = None):
        super().__init__(llm=_CappedSummarizerLlm(llm), prompt_template=prompt_template or COACH_SUMMARY_PROMPT)

    def _format_events_for_prompt(self, events: list[Event]) -> str:
        return super()._format_events_for_prompt(_prepare_events_for_summary(events))

    async def maybe_summarize_events(self, *, events: list[Event]) -> Optional[Event]:
        if _is_mid_plan_apply(events):
            return None
        compacted = await super().maybe_summarize_events(events=events)
        blocks = latest_report_blocks(events)
        if compacted is None or not blocks:
            return compacted
        content = compacted.actions.compaction.compacted_content
        memory = "\n\n".join([REPORT_MEMORY_HEADER, *blocks])
        content.parts = [*(content.parts or []), types.Part(text=memory)]
        return compacted


# ------------------------------------------------------------------------------
# Per request: only the latest report output and skill instructions
# ------------------------------------------------------------------------------

def _call_response_keys(contents: list[types.Content]) -> dict[tuple[int, int], str]:
    """Maps `(ci, pi)` to a stable correlation key, pairing `id=None` calls/responses positionally.

    Gemini's `_copy_content_for_request` strips `adk-*` client IDs to `None`; pairing by tool name in
    FIFO order keeps button-dispatched `apply_staged_changes` and `apply_training_plan` turns linked.
    """
    keys: dict[tuple[int, int], str] = {}
    pending_by_name: dict[str, list[str]] = {}
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            call, response = part.function_call, part.function_response
            if call:
                if call.id:
                    keys[(ci, pi)] = call.id
                else:
                    syn = f"@pos:{ci}:{pi}"
                    keys[(ci, pi)] = syn
                    pending_by_name.setdefault(call.name or "", []).append(syn)
            elif response:
                if response.id:
                    keys[(ci, pi)] = response.id
                else:
                    queue = pending_by_name.get(response.name or "")
                    keys[(ci, pi)] = queue.pop(0) if queue else f"@resp:{ci}:{pi}"
    return keys


def _skill_name(part: types.Part, key: Optional[str], call_skills: dict[str, str]) -> Optional[str]:
    response = part.function_response
    payload = response.response if isinstance(response.response, dict) else {}
    return payload.get("skill_name") or call_skills.get(key or response.id or "")


def _result_json(response: types.FunctionResponse) -> dict:
    try:
        parsed = json.loads(result_text(response))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def staging_status(
    contents: list[types.Content],
    keys: Optional[dict[tuple[int, int], str]] = None,
) -> tuple[set[str], set[str]]:
    """Keys of staged sets (replaced by a later staging, applied by a later apply)."""
    keys = keys if keys is not None else _call_response_keys(contents)
    replaced: set[str] = set()
    applied: set[str] = set()
    pending: Optional[str] = None
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            response = part.function_response
            if not response:
                continue
            key = keys.get((ci, pi))
            if response.name == STAGE and key and (_result_json(response).get("staged") or 0) > 0:
                if pending:
                    replaced.add(pending)
                pending = key
            elif response.name == APPLY and "results" in _result_json(response):
                if pending:
                    applied.add(pending)
                pending = None
    return replaced, applied


def superseded_failed_stagings(
    contents: list[types.Content],
    keys: Optional[dict[tuple[int, int], str]] = None,
    *,
    turn_start: Optional[int] = None,
) -> set[str]:
    """Keys of failed `stage_workout_changes` (`staged: 0`) superseded by a later staging or from an earlier turn."""
    keys = keys if keys is not None else _call_response_keys(contents)
    superseded: set[str] = set()
    failed_pending: set[str] = set()
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            response = part.function_response
            key = keys.get((ci, pi))
            if not response or not key or response.name != STAGE:
                continue
            result = _result_json(response)
            if (result.get("staged") or 0) > 0:
                superseded.update(failed_pending)
                failed_pending.clear()
            elif result.get("staged") == 0:
                superseded.update(failed_pending)
                failed_pending.clear()
                if turn_start is not None and ci < turn_start:
                    superseded.add(key)
                else:
                    failed_pending.add(key)
    return superseded


def _is_runner_turn_message(content: types.Content) -> bool:
    return content.role == "user" and any(
        (p.text and p.text.strip()) or p.inline_data or p.file_data
        for p in content.parts or []
        if not p.function_response
    )


def _last_runner_message(contents: list[types.Content]) -> int:
    """Index of the latest runner message (a user content with non-empty runner input)."""
    return max((i for i, c in enumerate(contents) if _is_runner_turn_message(c)), default=0)


def _has_active_llm_routing_step(contents: list[types.Content], turn_start: int) -> bool:
    """True on Step 2+ of an LLM-routed turn (Call 1 already ran and warmed `contents[:turn_start + 1]`).

    Pre-dispatched turns stamp `_SYNTHETIC_THOUGHT_SIG` on `contents[turn_start + 1]` and pure-code apply
    actions (`apply_staged_changes`, `apply_training_plan`) never make a routing LLM call.
    """
    if not (0 <= turn_start < len(contents) - 1) or not _is_runner_turn_message(contents[turn_start]):
        return False
    first_step = contents[turn_start + 1]
    parts = first_step.parts or []
    call_names = [p.function_call.name for p in parts if p.function_call]
    if first_step.role != "model" or not call_names or any(n in (APPLY, PLAN_APPLY) for n in call_names):
        return False
    return not any(getattr(p, "thought_signature", None) == _SYNTHETIC_THOUGHT_SIG for p in parts)


def _compact_slice(contents: list[types.Content], *, turn_start: int) -> list[types.Content]:
    """Compacts a contiguous `contents` slice while keeping the latest report/skill/staging in that slice."""
    keys = _call_response_keys(contents)
    call_skills = {
        keys[(ci, pi)]: (p.function_call.args or {}).get("skill_name")
        for ci, c in enumerate(contents)
        for pi, p in enumerate(c.parts or [])
        if p.function_call and p.function_call.name == LOAD_SKILL and (ci, pi) in keys
    }
    schedule_detail_calls = {
        keys[(ci, pi)]
        for ci, c in enumerate(contents)
        for pi, p in enumerate(c.parts or [])
        if p.function_call
        and p.function_call.name == "get_schedule"
        and (ci, pi) in keys
        and bool((p.function_call.args or {}).get("include_details"))
    }

    # Pass 1: the position of the latest copy of each report / skill / plan context (later = newer).
    # When a narrow `get_schedule(include_details=True)` inspects days strictly inside an earlier unapplied
    # `get_schedule`, keep that enclosing week schedule verbatim too so the rest of the week is not lost.
    latest: dict[tuple[str, str], tuple[int, int, int]] = {}
    schedules_since_apply: list[tuple[int, int, tuple[str, str], bool]] = []
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            response = part.function_response
            key = keys.get((ci, pi), "")
            if response and response.name in (APPLY, PLAN_APPLY):
                schedules_since_apply.clear()
            if response and response.name in REPORT_LABELS and _is_usable(result_text(response)):
                latest[("report", response.name)] = (ci, pi, 0)
                if response.name == "get_schedule":
                    win = _schedule_window(result_text(response))
                    if win:
                        schedules_since_apply.append((ci, pi, win, key in schedule_detail_calls))
            elif response and response.name == PLAN_CONTEXT and _is_usable(result_text(response)):
                latest[("context", PLAN_CONTEXT)] = (ci, pi, 0)
            elif response and response.name == LOAD_SKILL and _skill_name(part, key, call_skills):
                latest[("skill", _skill_name(part, key, call_skills))] = (ci, pi, 0)
            elif part.text and not part.thought:
                for m in _REPORT_BLOCK_RE.finditer(part.text):
                    latest[("report", m.group("tool"))] = (ci, pi, m.start() + 1)
                    if m.group("tool") == "get_schedule":
                        schedules_since_apply.clear()

    kept_enclosing_schedules: set[tuple[int, int]] = set()
    if len(schedules_since_apply) >= 2 and schedules_since_apply[-1][3]:
        last_ci, last_pi, last_win, _ = schedules_since_apply[-1]
        if latest.get(("report", "get_schedule")) == (last_ci, last_pi, 0):
            for prev_ci, prev_pi, prev_win, _ in reversed(schedules_since_apply[:-1]):
                if prev_win[0] <= last_win[0] and last_win[1] <= prev_win[1] and prev_win != last_win:
                    kept_enclosing_schedules.add((prev_ci, prev_pi))
                    break

    # Pass 2: drop or point away from every older copy; compact what the app already settled.
    replaced, applied = staging_status(contents, keys)
    replaced = replaced | superseded_failed_stagings(contents, keys, turn_start=turn_start)
    plans = plan_status(contents, keys, turn_start=turn_start)
    out: list[types.Content] = []
    for ci, content in enumerate(contents):
        parts, changed = [], False
        for pi, part in enumerate(content.parts or []):
            key = keys.get((ci, pi))
            if _is_collapsed_apply(part, key, plans):
                changed = True  # an earlier week of a plan apply: the latest one carries the summary
                continue
            new = (
                _compact_plan(part, key, plans, ci)
                or _without_replaced_staging(part, key, replaced)
                or _compact_applied(part, key, applied)
                or _stale_skill_stub(part, ci, turn_start, key, call_skills)
                or _stale_guard_stub(part, ci, turn_start)
                or _keep_latest_in_part(part, ci, pi, latest, key, call_skills, kept_enclosing_schedules)
            )
            changed = changed or new is not part
            if new is not None:
                parts.append(new)
        if changed and not parts:
            continue  # only collapsed apply events were in this content
        if changed:
            content = content.model_copy(update={"parts": parts})
        out.append(content)
    return out


def keep_latest_reports_and_skills(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: one copy of each report's latest output and each skill's instructions.

    On Step 2+ of an LLM-routed turn, locks `contents[:turn_start + 1]` to the exact byte-for-byte slice
    Call 1 just sent so a new tool response never invalidates Call 1's warm KV prefix mid-turn; older
    superseded reports are then stubbed cleanly on the next turn.
    """
    contents = llm_request.contents or []
    turn_start = _last_runner_message(contents)
    if _has_active_llm_routing_step(contents, turn_start):
        prefix = _compact_slice(contents[: turn_start + 1], turn_start=turn_start)
        tail = _compact_slice(contents[turn_start + 1 :], turn_start=0)
        llm_request.contents = [*prefix, *tail]
    else:
        llm_request.contents = _compact_slice(contents, turn_start=turn_start)
    return None  # never short-circuits the model call


# ------------------------------------------------------------------------------
# Training plans: applied spec stubbed, per-week apply events collapsed
# ------------------------------------------------------------------------------

def plan_status(
    contents: list[types.Content],
    keys: Optional[dict[tuple[int, int], str]] = None,
    *,
    turn_start: Optional[int] = None,
) -> dict:
    """Applied/replaced plans in the request: {"stubs": {stage key: stub}, "replaced": set[str],
    "drop": apply keys of earlier weeks, "summaries": {latest apply key per plan: summary line},
    "last_apply_ci": int}."""
    keys = keys if keys is not None else _call_response_keys(contents)
    calls: dict[str, list[str]] = {}       # staged_id -> apply keys, in order
    responses: dict[str, dict] = {}        # apply key -> result JSON
    stages: dict[str, tuple[str, dict]] = {}  # stage key -> (staged_id, result JSON)
    replaced: set[str] = set()
    failed_pending: set[str] = set()
    pending_cid: Optional[str] = None
    pending_sid: Optional[str] = None
    last_apply_ci = -1
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            call, response = part.function_call, part.function_response
            key = keys.get((ci, pi))
            if call and call.name == PLAN_APPLY and key:
                staged_id = str((call.args or {}).get("staged_id") or "")
                calls.setdefault(staged_id, []).append(key)
                if pending_sid == staged_id:
                    pending_cid = None
                    pending_sid = None
            elif response and key and response.name == PLAN_APPLY:
                responses[key] = _result_json(response)
                last_apply_ci = ci
            elif response and key and response.name == PLAN_STAGE:
                result = _result_json(response)
                if result.get("staged_id"):
                    sid = result["staged_id"]
                    stages[key] = (sid, result)
                    replaced.update(failed_pending)
                    failed_pending.clear()
                    if pending_cid and pending_sid not in calls:
                        replaced.add(pending_cid)
                    pending_cid = key
                    pending_sid = sid
                elif result.get("staged") == 0:
                    if turn_start is not None and ci < turn_start:
                        replaced.add(key)
                    else:
                        failed_pending.add(key)
    stubs = {cid: APPLIED_PLAN_STUB.format(weeks=r.get("total_weeks", "?"), sessions=r.get("sessions", "?"))
             for cid, (sid, r) in stages.items() if sid in calls}
    for cid in replaced:
        stubs[cid] = REPLACED_PLAN_STUB
    drop = {cid for ids in calls.values() for cid in ids[:-1]}
    summaries = {ids[-1]: applied_plan_summary(sid, responses.get(ids[-1]) or {}) for sid, ids in calls.items()}
    return {"stubs": stubs, "replaced": replaced, "drop": drop, "summaries": summaries, "last_apply_ci": last_apply_ci}


def _week_ranges(weeks: list[int]) -> str:
    """[1, 2, 3, 5] -> '1-3, 5'."""
    ranges: list[list[int]] = []
    for w in sorted(weeks):
        if ranges and w == ranges[-1][1] + 1:
            ranges[-1][1] = w
        else:
            ranges.append([w, w])
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in ranges) or "none"


def applied_plan_summary(staged_id: str, result: dict) -> str:
    """One line for every apply event of a plan (the latest state); the runner saw the progress and confirmation."""
    state = result.get("applied_training_plan") or {}
    if not state:
        return f"Training plan {staged_id}: apply result: {json.dumps(result)[:200]}"
    line = (f"Training plan {staged_id} applied to TrainingPeaks (the app confirmed this to the runner): weeks "
            f"{_week_ranges(state.get('weeks_done') or [])} of {state.get('total_weeks')} done · "
            f"{state.get('created', 0)} created, {state.get('updated', 0)} updated, {state.get('deleted', 0)} removed, "
            f"{state.get('failed', 0)} failed")
    if state.get("failed_weeks"):
        line += f"; not saved: weeks {_week_ranges(state['failed_weeks'])}"
    return line


def _is_collapsed_apply(part: types.Part, key: Optional[str], plans: dict) -> bool:
    call, response = part.function_call, part.function_response
    return bool((call and call.name == PLAN_APPLY and key in plans["drop"])
                or (response and response.name == PLAN_APPLY and key in plans["drop"]))


def _compact_plan(part: types.Part, key: Optional[str], plans: dict, ci: int = 0) -> Optional[types.Part]:
    """Applied or replaced plan stage calls / contexts as stubs and the latest apply response as one line."""
    call, response = part.function_call, part.function_response
    if call and call.name == PLAN_STAGE and key in plans["stubs"]:
        args = {"plan": plans["stubs"][key]}
        if key not in plans["replaced"] and (call.args or {}).get("message"):
            args["message"] = call.args["message"]
        return part.model_copy(update={"function_call": call.model_copy(update={"args": args})})
    if response and response.name == PLAN_STAGE and key in plans["replaced"]:
        return part.model_copy(
            update={"function_response": response.model_copy(update={"response": REPLACED_PLAN_RESULT})}
        )
    if response and response.name == PLAN_APPLY and key in plans["summaries"]:
        compact = {"result": plans["summaries"][key]}
        return part.model_copy(update={"function_response": response.model_copy(update={"response": compact})})
    if response and response.name == PLAN_CONTEXT and ci < plans.get("last_apply_ci", -1):
        compact = {"result": APPLIED_PLAN_CONTEXT_STUB}
        return part.model_copy(update={"function_response": response.model_copy(update={"response": compact})})
    return None


def _without_replaced_staging(part: types.Part, key: Optional[str], replaced: set[str]) -> Optional[types.Part]:
    """The stubbed call / response of a replaced staged set (None when the part is not one)."""
    call, response = part.function_call, part.function_response
    if call and call.name == STAGE and key in replaced:
        return part.model_copy(update={"function_call": call.model_copy(update={"args": REPLACED_STAGE_ARGS})})
    if response and response.name == STAGE and key in replaced:
        return part.model_copy(update={"function_response": response.model_copy(update={"response": REPLACED_STAGE_RESULT})})
    return None


MAX_APPLIED_ITEM_LINES = 12


def applied_summary(response: types.FunctionResponse) -> str:
    """Compact summary of an applied change set (per-item with [id] for <= 12 items; counts + window for large sets)."""
    results = [r for r in (_result_json(response).get("results") or []) if isinstance(r, dict)]
    ok_items = [r for r in results if r.get("ok")]
    failed_items = [r for r in results if not r.get("ok")]
    if len(results) > MAX_APPLIED_ITEM_LINES:
        dates = sorted(str(r.get("date") or "")[:10] for r in results if str(r.get("date") or "")[:10])
        window = f" ({dates[0]}..{dates[-1]})" if dates else ""
        counts: dict[str, int] = {}
        for r in ok_items:
            act = str(r.get("action") or "updated")
            counts[act] = counts.get(act, 0) + 1
        parts = [f"{counts[k]} {k}" for k in ("create", "update", "delete") if counts.get(k)]
        summary = (
            f"Applied {len(ok_items)}/{len(results)}{window} (the app confirmed this to the runner): "
            + (", ".join(parts) or "none")
        )
        if failed_items:
            fail_bits = [
                f'{str(r.get("date") or "")[:10]} "{r.get("title") or ""}": {r.get("error") or "failed"}'
                for r in failed_items[:5]
            ]
            summary += "; FAILED: " + "; ".join(fail_bits)
        return summary

    items = []
    for r in results:
        what = r.get("kind") if r.get("kind") in ("note", "event") else r.get("sport") or "workout"
        item = f'{r.get("action") or "change"} {str(r.get("date") or "")[:10]} {what} "{r.get("title") or ""}"'
        if r.get("id"):
            item += f' [{r["id"]}]'
        if not r.get("ok"):
            item += f' FAILED: {r.get("error") or "unknown error"}'
        items.append(item)
    return f"Applied {len(ok_items)}/{len(results)} (the app confirmed this to the runner): " + "; ".join(items)


def _compact_applied(part: types.Part, key: Optional[str], applied: set[str]) -> Optional[types.Part]:
    """An apply result as one compact line, and the staged set it applied as a stub (keeping the message)."""
    call, response = part.function_call, part.function_response
    if response and response.name == APPLY and "results" in _result_json(response):
        compact = {"result": applied_summary(response)}
        return part.model_copy(update={"function_response": response.model_copy(update={"response": compact})})
    if call and call.name == STAGE and key in applied:
        args = {"changes": APPLIED_STAGE_CHANGES}
        if (call.args or {}).get("message"):
            args["message"] = call.args["message"]
        return part.model_copy(update={"function_call": call.model_copy(update={"args": args})})
    if response and response.name == STAGE and key in applied:
        return part.model_copy(update={"function_response": response.model_copy(update={"response": APPLIED_STAGE_RESULT})})
    return None


def _stale_skill_stub(
    part: types.Part, ci: int, turn_start: int, key: Optional[str], call_skills: dict[str, str]
) -> Optional[types.Part]:
    """Stubs all completed-turn `load_skill` rubrics (`ci < turn_start`). `load_skill` sits after report data in
    the tool-response content, so stubbing it preserves prefix caching on `system_instruction + tools + report`
    while saving ~1,000-1,400 uncached tokens on every follow-up turn."""
    response = part.function_response
    if not response or response.name != LOAD_SKILL or ci >= turn_start:
        return None
    skill = _skill_name(part, key, call_skills)
    if not skill:
        return None
    stub = {"skill_name": skill, "instructions": STALE_SKILL_STUB}
    return part.model_copy(update={"function_response": response.model_copy(update={"response": stub})})


def _stale_guard_stub(part: types.Part, ci: int, turn_start: int) -> Optional[types.Part]:
    """Stubs completed-turn `<tool> was not run:` guard responses while keeping active-turn guard guidance verbatim."""
    response = part.function_response
    if not response or ci >= turn_start:
        return None
    if not _NOT_RUN_RE.match(result_text(response).lstrip()):
        return None
    stub = {"result": STALE_GUARD_STUB.format(tool=response.name or "tool")}
    return part.model_copy(update={"function_response": response.model_copy(update={"response": stub})})


def _keep_latest_in_part(
    part: types.Part,
    ci: int,
    pi: int,
    latest: dict,
    key: Optional[str],
    call_skills: dict[str, str],
    kept_enclosing_schedules: Optional[set[tuple[int, int]]] = None,
) -> Optional[types.Part]:
    response = part.function_response
    if response and response.name in REPORT_LABELS:
        if not _is_usable(result_text(response)):
            return part
        if latest.get(("report", response.name), (ci, pi, 0)) == (ci, pi, 0):
            return part
        if response.name == "get_schedule" and kept_enclosing_schedules and (ci, pi) in kept_enclosing_schedules:
            return part
        note = f"[superseded: the latest {REPORT_LABELS[response.name]} output is further below]"
        return part.model_copy(update={"function_response": response.model_copy(update={"response": {"result": note}})})
    if response and response.name == PLAN_CONTEXT:
        if latest.get(("context", PLAN_CONTEXT), (ci, pi, 0)) == (ci, pi, 0):
            return part
        note = "[superseded: the latest plan context is further below]"
        return part.model_copy(update={"function_response": response.model_copy(update={"response": {"result": note}})})
    if response and response.name == LOAD_SKILL:
        skill = _skill_name(part, key, call_skills)
        if not skill or latest.get(("skill", skill), (ci, pi, 0)) == (ci, pi, 0):
            return part
        note = {"skill_name": skill, "instructions": "[same instructions as the later load_skill result below]"}
        return part.model_copy(update={"function_response": response.model_copy(update={"response": note})})
    if part.text and not part.thought and "<report " in part.text:
        def keep(m: re.Match) -> str:
            return m.group(0) if latest.get(("report", m.group("tool"))) == (ci, pi, m.start() + 1) else ""
        text = _REPORT_BLOCK_RE.sub(keep, part.text)
        if text == part.text:
            return part
        if not text.replace(REPORT_MEMORY_HEADER, "").replace("[model] said:", "").strip():
            return None  # only superseded reports were left in this part
        return part.model_copy(update={"text": text})
    return part
