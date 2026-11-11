"""Report memory: report output survives session compaction, verbatim and only the latest of each kind.

Session history is compacted every N runner messages (`agent.py`). ADK's `LlmEventSummarizer` cuts
every tool result to 2,000 characters and paraphrases the rest, so a schedule audit's calendar (with
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
  is compacted: an apply result becomes one line per change (with ids) and the staged set it applied
  a stub (its `message` kept). Skill instructions from completed turns become a stub (the coach
  reloads a skill with its data tool). The stored session (and so the UI) is never changed.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

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
    "fetch_schedule_audit_data": "Schedule audit",
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
STALE_SKILL_STUB = "[skill instructions from an earlier turn: call load_skill again before following this skill]"

_REPORT_BLOCK_RE = re.compile(r'\n*<report tool="(?P<tool>[^"]+)"[^>]*>.*?</report>', re.DOTALL)
REPORT_MEMORY_HEADER = (
    "REPORT MEMORY: the latest report output from this part of the conversation, verbatim. Use it to "
    "answer follow-ups (planned sessions carry their [workout_id])."
)

COACH_SUMMARY_PROMPT = (
    "The following is a conversation between a runner and their AI running coach. It may start from "
    "an earlier summary. Write a concise summary that keeps: the runner's requests, preferences and "
    "constraints; the coach's recommendations and the decisions taken, with their dates; workout and "
    "calendar changes that were staged or applied in TrainingPeaks; and open questions. Report data "
    "and skill instructions are kept separately: do not restate report numbers or calendars.\n\n"
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
    return bool(text.strip()) and not text.lstrip().startswith("Error")


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
    if response.name in REPORT_LABELS:
        return "[report output kept verbatim in the report memory]"
    if response.name == LOAD_SKILL:
        return "[skill instructions omitted]"
    return None


def _without_bulky_responses(event: Event) -> Event:
    """The event with report output and skill instructions replaced by short placeholders."""
    if not event.content or not event.content.parts:
        return event
    parts, changed = [], False
    for part in event.content.parts:
        note = _placeholder(part.function_response) if part.function_response else None
        if note:
            response = part.function_response.model_copy(update={"response": {"result": note}})
            part = part.model_copy(update={"function_response": response})
            changed = True
        parts.append(part)
    if not changed:
        return event
    return event.model_copy(update={"content": event.content.model_copy(update={"parts": parts})})


class ReportMemorySummarizer(LlmEventSummarizer):
    """LLM summary of the conversation plus the latest report output, verbatim."""

    def __init__(self, llm: BaseLlm, prompt_template: Optional[str] = None):
        super().__init__(llm=llm, prompt_template=prompt_template or COACH_SUMMARY_PROMPT)

    def _format_events_for_prompt(self, events: list[Event]) -> str:
        return super()._format_events_for_prompt([_without_bulky_responses(e) for e in events])

    async def maybe_summarize_events(self, *, events: list[Event]) -> Optional[Event]:
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

def _skill_name(part: types.Part, call_skills: dict[str, str]) -> Optional[str]:
    response = part.function_response
    payload = response.response if isinstance(response.response, dict) else {}
    return payload.get("skill_name") or call_skills.get(response.id or "")


def _result_json(response: types.FunctionResponse) -> dict:
    try:
        parsed = json.loads(result_text(response))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def staging_status(contents: list[types.Content]) -> tuple[set[str], set[str]]:
    """Call ids of staged sets (replaced by a later staging, applied by a later apply)."""
    replaced: set[str] = set()
    applied: set[str] = set()
    pending: Optional[str] = None
    for content in contents:
        for part in content.parts or []:
            response = part.function_response
            if not response or not response.id:
                continue
            if response.name == STAGE and (_result_json(response).get("staged") or 0) > 0:
                if pending:
                    replaced.add(pending)
                pending = response.id
            elif response.name == APPLY and "results" in _result_json(response):
                if pending:
                    applied.add(pending)
                pending = None
    return replaced, applied


def replaced_stagings(contents: list[types.Content]) -> set[str]:
    """Call ids of staged sets replaced by a later staging; an apply in between keeps them (history)."""
    return staging_status(contents)[0]


def _last_runner_message(contents: list[types.Content]) -> int:
    """Index of the latest runner message (a user content that is not only tool responses)."""
    return max(
        (i for i, c in enumerate(contents)
         if c.role == "user" and any(not p.function_response for p in c.parts or [])),
        default=0,
    )


def keep_latest_reports_and_skills(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: one copy of each report's latest output and each skill's instructions."""
    contents = llm_request.contents or []
    call_skills = {
        p.function_call.id: (p.function_call.args or {}).get("skill_name")
        for c in contents for p in c.parts or []
        if p.function_call and p.function_call.name == LOAD_SKILL and p.function_call.id
    }

    # Pass 1: the position of the latest copy of each report / skill (later in the request = newer).
    latest: dict[tuple[str, str], tuple[int, int, int]] = {}
    for ci, content in enumerate(contents):
        for pi, part in enumerate(content.parts or []):
            response = part.function_response
            if response and response.name in REPORT_LABELS and _is_usable(result_text(response)):
                latest[("report", response.name)] = (ci, pi, 0)
            elif response and response.name == LOAD_SKILL and _skill_name(part, call_skills):
                latest[("skill", _skill_name(part, call_skills))] = (ci, pi, 0)
            elif part.text and not part.thought:
                for m in _REPORT_BLOCK_RE.finditer(part.text):
                    latest[("report", m.group("tool"))] = (ci, pi, m.start() + 1)

    # Pass 2: drop or point away from every older copy; compact what the app already settled.
    replaced, applied = staging_status(contents)
    turn_start = _last_runner_message(contents)
    out: list[types.Content] = []
    for ci, content in enumerate(contents):
        parts, changed = [], False
        for pi, part in enumerate(content.parts or []):
            new = (
                _without_replaced_staging(part, replaced)
                or _compact_applied(part, applied)
                or _stale_skill_stub(part, ci, turn_start, call_skills)
                or _keep_latest_in_part(part, ci, pi, latest, call_skills)
            )
            changed = changed or new is not part
            if new is not None:
                parts.append(new)
        if changed:
            content = content.model_copy(update={"parts": parts})
        out.append(content)
    llm_request.contents = out
    return None  # never short-circuits the model call


def _without_replaced_staging(part: types.Part, replaced: set[str]) -> Optional[types.Part]:
    """The stubbed call / response of a replaced staged set (None when the part is not one)."""
    call, response = part.function_call, part.function_response
    if call and call.name == STAGE and call.id in replaced:
        return part.model_copy(update={"function_call": call.model_copy(update={"args": REPLACED_STAGE_ARGS})})
    if response and response.name == STAGE and response.id in replaced:
        return part.model_copy(update={"function_response": response.model_copy(update={"response": REPLACED_STAGE_RESULT})})
    return None


def applied_summary(response: types.FunctionResponse) -> str:
    """One compact line per applied change (ids kept for later edits); the runner saw the full table."""
    results = _result_json(response).get("results") or []
    ok = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    items = []
    for r in results:
        if not isinstance(r, dict):
            continue
        what = r.get("kind") if r.get("kind") == "note" else r.get("sport") or "workout"
        item = f'{r.get("action") or "change"} {str(r.get("date") or "")[:10]} {what} "{r.get("title") or ""}"'
        if r.get("id"):
            item += f' [{r["id"]}]'
        if not r.get("ok"):
            item += f' FAILED: {r.get("error") or "unknown error"}'
        items.append(item)
    return f"Applied {ok}/{len(results)} (the app confirmed this to the runner): " + "; ".join(items)


def _compact_applied(part: types.Part, applied: set[str]) -> Optional[types.Part]:
    """An apply result as one compact line, and the staged set it applied as a stub (keeping the message)."""
    call, response = part.function_call, part.function_response
    if response and response.name == APPLY and "results" in _result_json(response):
        compact = {"result": applied_summary(response)}
        return part.model_copy(update={"function_response": response.model_copy(update={"response": compact})})
    if call and call.name == STAGE and call.id in applied:
        args = {"changes": APPLIED_STAGE_CHANGES}
        if (call.args or {}).get("message"):
            args["message"] = call.args["message"]
        return part.model_copy(update={"function_call": call.model_copy(update={"args": args})})
    if response and response.name == STAGE and response.id in applied:
        return part.model_copy(update={"function_response": response.model_copy(update={"response": APPLIED_STAGE_RESULT})})
    return None


def _stale_skill_stub(part: types.Part, ci: int, turn_start: int, call_skills: dict[str, str]) -> Optional[types.Part]:
    """Skill instructions from a completed turn as a stub (the coach reloads the skill with its data tool)."""
    response = part.function_response
    if not response or response.name != LOAD_SKILL or ci >= turn_start:
        return None
    skill = _skill_name(part, call_skills)
    if not skill:
        return None
    stub = {"skill_name": skill, "instructions": STALE_SKILL_STUB}
    return part.model_copy(update={"function_response": response.model_copy(update={"response": stub})})


def _keep_latest_in_part(
    part: types.Part, ci: int, pi: int, latest: dict, call_skills: dict[str, str]
) -> Optional[types.Part]:
    response = part.function_response
    if response and response.name in REPORT_LABELS:
        if latest.get(("report", response.name), (ci, pi, 0)) == (ci, pi, 0):
            return part
        note = f"[superseded: the latest {REPORT_LABELS[response.name]} output is further below]"
        return part.model_copy(update={"function_response": response.model_copy(update={"response": {"result": note}})})
    if response and response.name == LOAD_SKILL:
        skill = _skill_name(part, call_skills)
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
