"""Report memory: report output survives compaction verbatim; each request keeps only the latest copies."""

import json

from google.adk.events.event import Event
from google.adk.flows.llm_flows.contents import _process_compaction_events
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from running_coach.coach.report_memory import (
    REPLACED_STAGE_ARGS,
    REPLACED_STAGE_RESULT,
    ReportMemorySummarizer,
    keep_latest_reports_and_skills,
    replaced_stagings,
)

SKILL_TEXT = "# Schedule Audit & Assessment Skill\n" + "Audit protocol step. " * 200
AUDIT = (
    "### Training Schedule Audit\n* Nov 09 - Nov 15: 0 km run\n"
    "  - Fri 13 Nov · Strength · General S&C Work · 45 min [3937622001]"
)
ANALYSIS_OLD = "Workout analysis: Easy Run 2026-11-05, Pa:Hr 3.1%, weather 9°C"
ANALYSIS_NEW = "Workout analysis: Threshold 2026-11-06, 4x2km @ 4:47/km, weather 11°C"


class FakeLlm:
    model = "fake-summarizer"

    def __init__(self):
        self.prompts: list[str] = []

    async def generate_content_async(self, llm_request, stream=False):
        self.prompts.append(llm_request.contents[0].parts[0].text)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Runner audited the plan.")]))


def _call(name: str, call_id: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, id=call_id, args=args))


def _resp(name: str, call_id: str, payload: dict) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(name=name, id=call_id, response=payload))


def _event(author: str, ts: float, inv: str, *parts: types.Part) -> Event:
    role = "model" if author != "user" else "user"
    return Event(author=author, timestamp=ts, invocation_id=inv, content=types.Content(role=role, parts=list(parts)))


def _session_events() -> list[Event]:
    return [
        _event("user", 1.0, "i1", types.Part(text="Audit my schedule")),
        _event("coaching_agent", 2.0, "i1", _call("load_skill", "c1", skill_name="schedule-audit"),
               _call("fetch_schedule_audit_data", "c2", start_date="2026-11-02", end_date="2026-11-29")),
        _event("coaching_agent", 3.0, "i1", _resp("load_skill", "c1", {"skill_name": "schedule-audit", "instructions": SKILL_TEXT}),
               _resp("fetch_schedule_audit_data", "c2", {"result": AUDIT})),
        _event("coaching_agent", 4.0, "i1", types.Part(text="### Assessment ... move Wed to Thu")),
        _event("user", 5.0, "i2", types.Part(text="Analyze Thursday")),
        _event("coaching_agent", 6.0, "i2", _call("analyze_workout", "c3", date_str="2026-11-05")),
        _event("coaching_agent", 7.0, "i2", _resp("analyze_workout", "c3", {"result": ANALYSIS_OLD})),
        _event("user", 8.0, "i3", types.Part(text="And Friday?")),
        _event("coaching_agent", 9.0, "i3", _call("analyze_workout", "c4", date_str="2026-11-06")),
        _event("coaching_agent", 10.0, "i3", _resp("analyze_workout", "c4", {"result": ANALYSIS_NEW})),
    ]


async def _compact(events: list[Event]):
    llm = FakeLlm()
    compacted = await ReportMemorySummarizer(llm=llm).maybe_summarize_events(events=events)
    return compacted, llm.prompts[0]


def test_compacted_history_reaches_the_model_with_the_report_memory():
    import asyncio

    events = _session_events()
    compacted, _ = asyncio.run(_compact(events))
    later = _event("user", 11.0, "i4", types.Part(text="ok add strength training on Nov 13th"))
    processed = _process_compaction_events([*events, compacted, later])
    texts = [p.text for e in processed for p in (e.content.parts if e.content else []) if p.text]
    assert any("[3937622001]" in t for t in texts)  # the planned strength session is still visible
    assert texts[-1] == "ok add strength training on Nov 13th"


def _staging_request(*middle: types.Content) -> "LlmRequest":
    from google.adk.models.llm_request import LlmRequest

    def stage(call_id: str, staged: int) -> list[types.Content]:
        return [types.Content(role="model", parts=[_call("stage_workout_changes", call_id, changes=[{"date_str": call_id}])]),
                types.Content(role="user", parts=[_resp("stage_workout_changes", call_id,
                                                        {"result": json.dumps({"staged": staged, "changes": [call_id]})})])]
    return LlmRequest(contents=[*stage("s1", 3), *middle, *stage("s2", 4)])


def _stage_parts(request) -> dict:
    out = {}
    for c in request.contents:
        for p in c.parts:
            if p.function_call and p.function_call.name == "stage_workout_changes":
                out[("call", p.function_call.id)] = p.function_call.args
            if p.function_response and p.function_response.name == "stage_workout_changes":
                out[("resp", p.function_response.id)] = p.function_response.response
    return out


def test_a_replaced_staged_set_is_cut_to_a_pointer_and_the_current_set_stays_verbatim():
    request = _staging_request()
    keep_latest_reports_and_skills(None, request)
    parts = _stage_parts(request)
    assert parts[("call", "s1")] == REPLACED_STAGE_ARGS and parts[("resp", "s1")] == REPLACED_STAGE_RESULT
    assert parts[("call", "s2")] == {"changes": [{"date_str": "s2"}]} and "s2" in parts[("resp", "s2")]["result"]


def test_an_applied_set_and_a_failed_restaging_keep_the_earlier_set():
    applied = [types.Content(role="model", parts=[_call("apply_staged_changes", "a1")]),
               types.Content(role="user", parts=[_resp("apply_staged_changes", "a1",
                                                       {"result": json.dumps({"success": True, "results": []})})])]
    request = _staging_request(*applied)
    keep_latest_reports_and_skills(None, request)
    assert _stage_parts(request)[("call", "s1")] == {"changes": [{"date_str": "s1"}]}  # applied: history

    failed = [types.Content(role="model", parts=[_call("stage_workout_changes", "f1", changes=[])]),
              types.Content(role="user", parts=[_resp("stage_workout_changes", "f1",
                                                      {"result": json.dumps({"staged": 0, "needs_structure": [{}]})})])]
    request = _staging_request()
    request.contents[2:2] = failed  # s1, failed retry, then s2: only s2 replaces s1
    assert replaced_stagings(request.contents) == {"s1"}
    request = _staging_request()
    request.contents[2:] = failed  # s1 then only a failed retry: s1 is still the current set
    assert replaced_stagings(request.contents) == set()
