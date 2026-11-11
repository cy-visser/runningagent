"""Report memory: report output survives compaction verbatim; each request keeps only the latest copies."""

import json

from google.adk.events.event import Event
from google.adk.flows.llm_flows.contents import _process_compaction_events
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from running_coach.coach.report_memory import (
    APPLIED_STAGE_CHANGES,
    APPLIED_STAGE_RESULT,
    REPLACED_STAGE_ARGS,
    REPLACED_STAGE_RESULT,
    STALE_SKILL_STUB,
    ReportMemorySummarizer,
    keep_latest_reports_and_skills,
    replaced_stagings,
)

SKILL_TEXT = "# Plan Audit & Assessment Skill\n" + "Audit protocol step. " * 200
AUDIT = (
    "### Training Plan Audit\n* Nov 09 - Nov 15: 0 km run\n"
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
        _event("coaching_agent", 2.0, "i1", _call("load_skill", "c1", skill_name="plan-audit"),
               _call("fetch_plan_audit_data", "c2", start_date="2026-11-02", end_date="2026-11-29")),
        _event("coaching_agent", 3.0, "i1", _resp("load_skill", "c1", {"skill_name": "plan-audit", "instructions": SKILL_TEXT}),
               _resp("fetch_plan_audit_data", "c2", {"result": AUDIT})),
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


def test_an_applied_set_is_compacted_and_a_failed_restaging_keeps_the_earlier_set():
    results = [{"ok": True, "id": "w1", "action": "update", "date": "2026-11-03", "sport": "Run",
                "title": "Threshold 4x2km", "description": "15' WU ..." * 50, "structure": {"steps": ["..."] * 40}},
               {"ok": False, "error": "TP 500", "action": "create", "date": "2026-11-04T00:00:00", "sport": "Run",
                "title": "Recovery Run"},
               {"ok": True, "id": "n1", "kind": "note", "action": "create", "date": "2026-11-04", "title": "Travel"}]
    applied = [types.Content(role="model", parts=[_call("apply_staged_changes", "a1")]),
               types.Content(role="user", parts=[_resp("apply_staged_changes", "a1",
                                                       {"result": json.dumps({"success": True, "results": results})})])]
    request = _staging_request(*applied)
    request.contents[0].parts[0].function_call.args["message"] = "Swap for recovery: TSB -18."
    original = list(request.contents)  # the session's contents: must never be mutated
    keep_latest_reports_and_skills(None, request)
    parts = _stage_parts(request)
    # The applied set: stub, but the coach's message stays; the current set s2 stays verbatim.
    assert parts[("call", "s1")] == {"changes": APPLIED_STAGE_CHANGES, "message": "Swap for recovery: TSB -18."}
    assert parts[("resp", "s1")] == APPLIED_STAGE_RESULT
    assert parts[("call", "s2")] == {"changes": [{"date_str": "s2"}]}
    # The apply result: one compact line per change, ids and failures kept, no bulky payload.
    (apply_resp,) = [p.function_response.response for c in request.contents for p in c.parts
                     if p.function_response and p.function_response.name == "apply_staged_changes"]
    assert apply_resp == {"result": (
        'Applied 2/3 (the app confirmed this to the runner): update 2026-11-03 Run "Threshold 4x2km" [w1]; '
        'create 2026-11-04 Run "Recovery Run" FAILED: TP 500; create 2026-11-04 note "Travel" [n1]')}
    # Only the request changes: the session's own contents keep the full set and results.
    assert original[0].parts[0].function_call.args["changes"] == [{"date_str": "s1"}]
    assert "description" in original[3].parts[0].function_response.response["result"]

    failed = [types.Content(role="model", parts=[_call("stage_workout_changes", "f1", changes=[])]),
              types.Content(role="user", parts=[_resp("stage_workout_changes", "f1",
                                                      {"result": json.dumps({"staged": 0, "needs_structure": [{}]})})])]
    request = _staging_request()
    request.contents[2:2] = failed  # s1, failed retry, then s2: only s2 replaces s1
    assert replaced_stagings(request.contents) == {"s1"}
    request = _staging_request()
    request.contents[2:] = failed  # s1 then only a failed retry: s1 is still the current set
    assert replaced_stagings(request.contents) == set()


def test_skill_instructions_of_completed_turns_become_a_stub_and_the_current_turn_keeps_them():
    from google.adk.models.llm_request import LlmRequest

    def load(call_id: str, skill: str) -> list[types.Content]:
        return [types.Content(role="model", parts=[_call("load_skill", call_id, skill_name=skill)]),
                types.Content(role="user", parts=[_resp("load_skill", call_id,
                                                        {"skill_name": skill, "instructions": SKILL_TEXT})])]

    request = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Audit my schedule")]),
        *load("k1", "plan-audit"),
        types.Content(role="model", parts=[types.Part(text="### Assessment")]),
        types.Content(role="user", parts=[types.Part(text="Add a tempo run on Thursday")]),
        *load("k2", "workout-creator"),
    ])
    keep_latest_reports_and_skills(None, request)
    skills = {p.function_response.response["skill_name"]: p.function_response.response["instructions"]
              for c in request.contents for p in c.parts
              if p.function_response and p.function_response.name == "load_skill"}
    assert skills == {"plan-audit": STALE_SKILL_STUB, "workout-creator": SKILL_TEXT}


def test_an_applied_plan_is_stubbed_and_its_week_applies_collapse_into_one_line():
    from google.adk.models.llm_request import LlmRequest

    from running_coach.coach.report_memory import APPLIED_PLAN_STUB

    sid = "0f8fad5b-d9cb-469f-a165-70867728950e"
    spec = {"start_date": "2026-11-02", "weeks": [{"week": n, "days": {"Tue": "I 6x1k r2'"}} for n in range(1, 25)]}
    staged = {"staged_id": sid, "total_weeks": 24, "sessions": 148, "weeks": ["W1 ...", "W2 ..."]}

    def apply(call_id: str, week: int) -> list[types.Content]:
        state = {"staged_id": sid, "total_weeks": 24, "weeks_done": list(range(1, week + 1)), "created": 5 * week,
                 "updated": week, "deleted": 0, "failed": 0, "failed_weeks": [], "done": week == 24}
        return [types.Content(role="user", parts=[types.Part(text="")]),
                types.Content(role="model", parts=[_call("apply_training_plan", call_id, staged_id=sid, week=week)]),
                types.Content(role="user", parts=[_resp("apply_training_plan", call_id, {"result": json.dumps(
                    {"success": True, "week": week, "applied_training_plan": state})})])]

    request = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Build my marathon plan")]),
        types.Content(role="model", parts=[_call("stage_training_plan", "p1", plan=spec, message="Base, build, taper.")]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "p1", {"result": json.dumps(staged)})]),
        *apply("a1", 1), *apply("a2", 2), *apply("a3", 3),
    ])
    original = list(request.contents)
    keep_latest_reports_and_skills(None, request)

    calls = {p.function_call.id: p.function_call.args for c in request.contents for p in c.parts if p.function_call}
    assert calls["p1"] == {"plan": APPLIED_PLAN_STUB.format(weeks=24, sessions=148), "message": "Base, build, taper."}
    assert [cid for cid in calls if cid.startswith("a")] == ["a3"]           # earlier weeks collapsed
    (summary,) = [p.function_response.response["result"] for c in request.contents for p in c.parts
                  if p.function_response and p.function_response.name == "apply_training_plan"]
    assert summary == (f"Training plan {sid} applied to TrainingPeaks (the app confirmed this to the runner): weeks "
                       "1-3 of 24 done · 15 created, 3 updated, 0 removed, 0 failed")
    # Only the request changes: the session's contents keep the full spec and every apply event.
    assert original[1].parts[0].function_call.args["plan"] == spec and len(original) == 12
