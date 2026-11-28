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
    staging_status,
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
    assert staging_status(request.contents)[0] == {"s1"}
    request = _staging_request()
    request.contents[2:] = failed  # s1 then only a failed retry: s1 is still the current set
    assert staging_status(request.contents)[0] == set()


def test_completed_turn_skills_are_stubbed_while_active_turn_skill_stays_verbatim_and_large_apply_bounds():
    from google.adk.models.llm_request import LlmRequest
    from running_coach.coach.report_memory import applied_summary

    def load(call_id: str, skill: str) -> list[types.Content]:
        return [types.Content(role="model", parts=[_call("load_skill", call_id, skill_name=skill)]),
                types.Content(role="user", parts=[_resp("load_skill", call_id,
                                                        {"skill_name": skill, "instructions": SKILL_TEXT})])]

    # All completed-turn skills become STALE_SKILL_STUB (after report data in msg[2]), while the active
    # turn's loaded skill stays verbatim.
    request = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Audit my schedule")]),
        *load("k1", "plan-audit"),
        types.Content(role="model", parts=[types.Part(text="### Assessment")]),
        types.Content(role="user", parts=[types.Part(text="Build my plan")]),
        *load("k_pb", "plan-builder"),
        types.Content(role="model", parts=[types.Part(text="Staged plan")]),
        types.Content(role="user", parts=[types.Part(text="Analyze my run today")]),
        *load("k2", "workout-analysis"),
    ])
    keep_latest_reports_and_skills(None, request)
    skills = {p.function_response.response["skill_name"]: p.function_response.response["instructions"]
              for c in request.contents for p in c.parts
              if p.function_response and p.function_response.name == "load_skill"}
    assert skills == {
        "plan-audit": STALE_SKILL_STUB,
        "plan-builder": STALE_SKILL_STUB,
        "workout-analysis": SKILL_TEXT,
    }

    # Reloading plan-audit in the active turn keeps the newest copy verbatim while older completed copies stay stubbed.
    reload_req = LlmRequest(contents=[
        *request.contents,
        types.Content(role="model", parts=[types.Part(text="Solid aerobic session.")]),
        types.Content(role="user", parts=[types.Part(text="Audit my schedule again")]),
        *load("k3", "plan-audit"),
    ])
    keep_latest_reports_and_skills(None, reload_req)
    by_id = {p.function_response.id: p.function_response.response["instructions"]
             for c in reload_req.contents for p in c.parts
             if p.function_response and p.function_response.name == "load_skill"}
    assert by_id["k1"] == STALE_SKILL_STUB
    assert by_id["k2"] == STALE_SKILL_STUB
    assert by_id["k_pb"] == STALE_SKILL_STUB
    assert by_id["k3"] == SKILL_TEXT

    # Large batch applies (> 12 workouts) collapse into one compact counts + window line instead of 100 item rows.
    hundred = [
        {"ok": True, "action": "create" if i < 60 else "update", "date": f"2027-01-{(i % 28) + 1:02d}",
         "sport": "Run", "title": f"Session {i}", "id": f"w_{i}"}
        for i in range(100)
    ]
    summary = applied_summary(_resp("apply_staged_changes", "ap1", {"result": json.dumps({"results": hundred})}).function_response)
    assert "Applied 100/100 (2027-01-01..2027-01-28" in summary
    assert "60 create, 40 update" in summary
    assert len(summary) < 160


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


def test_superseded_and_applied_plan_contexts_are_compacted():
    from google.adk.models.llm_request import LlmRequest
    from running_coach.coach.report_memory import APPLIED_PLAN_CONTEXT_STUB

    request = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Build plan")]),
        types.Content(role="model", parts=[_call("fetch_plan_context", "pc1")]),
        types.Content(role="user", parts=[_resp("fetch_plan_context", "pc1", {"result": "PLAN CONTEXT (new): old"})]),
        types.Content(role="model", parts=[_call("fetch_plan_context", "pc2")]),
        types.Content(role="user", parts=[_resp("fetch_plan_context", "pc2", {"result": "PLAN CONTEXT (overhaul): new"})]),
    ])
    keep_latest_reports_and_skills(None, request)
    resps = {p.function_response.id: p.function_response.response["result"]
             for c in request.contents for p in c.parts if p.function_response}
    assert resps == {
        "pc1": "[superseded: the latest plan context is further below]",
        "pc2": "PLAN CONTEXT (overhaul): new",
    }

    applied_req = LlmRequest(contents=[
        *request.contents,
        types.Content(role="model", parts=[_call("apply_training_plan", "ap1", staged_id="s1", week=1)]),
        types.Content(role="user", parts=[_resp("apply_training_plan", "ap1", {"result": '{"success": true}'})]),
    ])
    keep_latest_reports_and_skills(None, applied_req)
    after = {p.function_response.id: p.function_response.response["result"]
             for c in applied_req.contents for p in c.parts
             if p.function_response and p.function_response.name == "fetch_plan_context"}
    assert after == {"pc1": APPLIED_PLAN_CONTEXT_STUB, "pc2": APPLIED_PLAN_CONTEXT_STUB}


def test_replaced_unapplied_staged_plan_is_stubbed_dropping_superseded_message_and_keeping_latest_draft():
    from google.adk.models.llm_request import LlmRequest
    from running_coach.coach.report_memory import REPLACED_PLAN_RESULT, REPLACED_PLAN_STUB

    first_spec = {"start_date": "2027-08-02", "weeks": ["W1 | base | Aerobic | Tue: E 8 | Sun: L 18"]}
    second_spec = {"start_date": "2027-08-02", "weeks": ["W1 | build | Quality | Tue: I 6x1k r2' | Sun: L 22 +6@M"]}
    request = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="6 days running")]),
        types.Content(role="model", parts=[_call("stage_training_plan", "p1", plan=first_spec, message="Initial base block.")]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "p1", {"result": json.dumps(
            {"staged_id": "sid-1", "total_weeks": 13, "sessions": 96})})]),
        types.Content(role="user", parts=[types.Part(text="I want a ton of quality")]),
        types.Content(role="model", parts=[_call("stage_training_plan", "p2", plan=second_spec, message="High-quality block.")]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "p2", {"result": json.dumps(
            {"staged_id": "sid-2", "total_weeks": 13, "sessions": 104})})]),
        types.Content(role="user", parts=[types.Part(text="Make week 4 a down week")]),
    ])
    keep_latest_reports_and_skills(None, request)
    calls = {p.function_call.id: p.function_call.args for c in request.contents for p in c.parts if p.function_call}
    resps = {p.function_response.id: p.function_response.response for c in request.contents for p in c.parts if p.function_response}
    assert calls["p1"] == {"plan": REPLACED_PLAN_STUB}
    assert resps["p1"] == REPLACED_PLAN_RESULT
    assert calls["p2"] == {"plan": second_spec, "message": "High-quality block."}
    assert json.loads(resps["p2"]["result"])["staged_id"] == "sid-2"

    # A failed staging (staged: 0) stays intact during its active retry, then becomes a stub once a retry succeeds.
    in_retry = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="6 days running")]),
        types.Content(role="model", parts=[_call("stage_training_plan", "f0", plan=first_spec, message="Draft.")]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "f0", {"result": json.dumps(
            {"staged": 0, "errors": [{"week": 13, "day": "Race week"}]})})]),
    ])
    after_retry = LlmRequest(contents=[
        *in_retry.contents,
        types.Content(role="model", parts=[_call("stage_training_plan", "p3", plan=second_spec, message="Fixed.")]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "p3", {"result": json.dumps(
            {"staged_id": "sid-3", "total_weeks": 13, "sessions": 96})})]),
        types.Content(role="user", parts=[types.Part(text="Looks great, shift W4")]),
    ])
    keep_latest_reports_and_skills(None, in_retry)
    assert in_retry.contents[1].parts[0].function_call.args["plan"] == first_spec  # needed for the live retry!

    keep_latest_reports_and_skills(None, after_retry)
    retry_calls = {p.function_call.id: p.function_call.args for c in after_retry.contents for p in c.parts if p.function_call}
    retry_resps = {p.function_response.id: p.function_response.response for c in after_retry.contents for p in c.parts if p.function_response}
    assert retry_calls["f0"] == {"plan": REPLACED_PLAN_STUB} and retry_resps["f0"] == REPLACED_PLAN_RESULT
    assert retry_calls["p3"] == {"plan": second_spec, "message": "Fixed."}


def test_superseded_failed_workout_stagings_are_compacted_while_active_retry_stays_intact():
    from google.adk.models.llm_request import LlmRequest

    f1_changes = [{"date_str": "2026-11-18", "distance_km": 10}]
    f2_changes = [{"date_str": "2026-11-18", "structure": {"steps": []}}]
    s3_changes = [{"date_str": "2026-11-18", "code": "E 10"}]

    # Call 3 (f1 failed, then f2 failed): f1 is stubbed out, f2 stays verbatim for the live retry.
    in_second_retry = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Apply audit recommendations")]),
        types.Content(role="model", parts=[_call("stage_workout_changes", "f1", changes=f1_changes)]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "f1", {"result": json.dumps(
            {"staged": 0, "needs_structure": [{"why": "missing"}]})})]),
        types.Content(role="model", parts=[_call("stage_workout_changes", "f2", changes=f2_changes)]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "f2", {"result": json.dumps(
            {"staged": 0, "needs_structure": [{"why": "empty steps"}]})})]),
    ])
    keep_latest_reports_and_skills(None, in_second_retry)
    parts_mid = _stage_parts(in_second_retry)
    assert parts_mid[("call", "f1")] == REPLACED_STAGE_ARGS and parts_mid[("resp", "f1")] == REPLACED_STAGE_RESULT
    assert parts_mid[("call", "f2")] == {"changes": f2_changes}
    assert "empty steps" in parts_mid[("resp", "f2")]["result"]

    # Once s3 succeeds, both f1 and f2 are stubbed on subsequent turns while s3 stays verbatim.
    settled = LlmRequest(contents=[
        *in_second_retry.contents,
        types.Content(role="model", parts=[_call("stage_workout_changes", "s3", changes=s3_changes)]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "s3", {"result": json.dumps(
            {"staged": 1, "staged_id": "sid-ok"})})]),
        types.Content(role="user", parts=[types.Part(text="Looks good!")]),
    ])
    keep_latest_reports_and_skills(None, settled)
    parts_done = _stage_parts(settled)
    assert parts_done[("call", "f1")] == REPLACED_STAGE_ARGS
    assert parts_done[("call", "f2")] == REPLACED_STAGE_ARGS and parts_done[("resp", "f2")] == REPLACED_STAGE_RESULT
    assert parts_done[("call", "s3")] == {"changes": s3_changes}


def test_blocked_guard_responses_and_narrow_detail_peeks_preserve_active_schedule():
    from google.adk.models.llm_request import LlmRequest

    week_sched = "### Schedule (2026-11-30 – 2026-12-06)\n\n* **2026-11-30 – Dec 06**: 48.2 km"
    day_detail = "### Schedule (2026-12-04 – 2026-12-04)\n\n* **2026-11-30 – Dec 06**: 10.0 km [w_ext]"

    # 1. A blocked `... was not run:` guard response never supersedes the active report/schedule.
    blocked_req = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Check next week")]),
        types.Content(role="model", parts=[_call("get_schedule", "g1", start_date="2026-11-30", end_date="2026-12-06")]),
        types.Content(role="user", parts=[_resp("get_schedule", "g1", {"result": week_sched})]),
        types.Content(role="user", parts=[types.Part(text="Check Tuesday")]),
        types.Content(role="model", parts=[_call("get_schedule", "g2", start_date="2026-12-01", end_date="2026-12-01")]),
        types.Content(role="user", parts=[_resp("get_schedule", "g2", {
            "result": "get_schedule was not run: 2026-12-01..2026-12-01 is already in the active ### Schedule"
        })]),
    ])
    keep_latest_reports_and_skills(None, blocked_req)
    by_id = {p.function_response.id: p.function_response.response["result"]
             for c in blocked_req.contents for p in c.parts if p.function_response}
    assert by_id["g1"] == week_sched

    # 2. A narrow `include_details=True` inspection inside the active week keeps BOTH the week and the detail output.
    detail_req = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Check next week")]),
        types.Content(role="model", parts=[_call("get_schedule", "g1", start_date="2026-11-30", end_date="2026-12-06")]),
        types.Content(role="user", parts=[_resp("get_schedule", "g1", {"result": week_sched})]),
        types.Content(role="user", parts=[types.Part(text="Inspect Friday's external tempo builder")]),
        types.Content(role="model", parts=[_call(
            "get_schedule", "g_det", start_date="2026-12-04", end_date="2026-12-04", include_details=True
        )]),
        types.Content(role="user", parts=[_resp("get_schedule", "g_det", {"result": day_detail})]),
    ])
    keep_latest_reports_and_skills(None, detail_req)
    by_id_det = {p.function_response.id: p.function_response.response["result"]
                 for c in detail_req.contents for p in c.parts if p.function_response}
    assert by_id_det["g1"] == week_sched
    assert by_id_det["g_det"] == day_detail


def test_idless_quick_action_applies_and_plan_applies_compact_cleanly():
    """Regressions from traces 079f66f4620024f5 & 5d1dd74faea6189c: ADK strips `adk-*` IDs to `None` on Gemini,
    which used to leave button-applied stagings uncompacted, misclassify prior applied sets as `replaced`,
    label applied `event` entries as `workout`, and fail to collapse per-week `apply_training_plan` turns."""
    from google.adk.models.llm_request import LlmRequest
    from running_coach.coach.report_memory import APPLIED_PLAN_STUB

    ev_results = [{"ok": True, "id": 41502856, "kind": "event", "action": "create",
                   "date": "2027-06-12", "title": "Helsinki Half Marathon"}]
    wk_results = [{"ok": True, "id": "3925887632", "kind": "workout", "sport": "Run", "action": "update",
                   "date": "2027-04-14", "title": "Race Pace 6x1.5km", "description": "15' WU..." * 30}]

    req = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Stage Helsinki event")]),
        types.Content(role="model", parts=[_call("stage_workout_changes", "s_ev",
                                                 changes=["2027-06-12: event A RunningRoad 21.1k Helsinki HM"],
                                                 message="Staged A-priority Helsinki HM event.")]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "s_ev",
                                                {"result": json.dumps({"staged": 1, "staged_id": "sid-ev"})})]),
        types.Content(role="user", parts=[types.Part(text="Update TrainingPeaks")]),
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            name="apply_staged_changes", id=None, args={"staged_id": "sid-ev"}))]),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="apply_staged_changes", id=None, response={"result": json.dumps({"success": True, "results": ev_results})}))]),
        types.Content(role="user", parts=[types.Part(text="Stage threshold fixes")]),
        types.Content(role="model", parts=[_call("stage_workout_changes", "s_wk",
                                                 changes=["2027-04-14: P 6x1.5k @4:18 r2'"],
                                                 message="Staged Apr 14 progression fix.")]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "s_wk",
                                                {"result": json.dumps({"staged": 1, "staged_id": "sid-wk"})})]),
        types.Content(role="user", parts=[types.Part(text="Update TrainingPeaks")]),
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            name="apply_staged_changes", id=None, args={"staged_id": "sid-wk"}))]),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="apply_staged_changes", id=None, response={"result": json.dumps({"success": True, "results": wk_results})}))]),
        types.Content(role="user", parts=[types.Part(text="Should MLRs be 16k?")]),
    ])
    keep_latest_reports_and_skills(None, req)
    parts = _stage_parts(req)
    # Neither applied staging is misclassified as replaced; both preserve `message` and stub `changes` + response.
    assert parts[("call", "s_ev")] == {"changes": APPLIED_STAGE_CHANGES, "message": "Staged A-priority Helsinki HM event."}
    assert parts[("resp", "s_ev")] == APPLIED_STAGE_RESULT
    assert parts[("call", "s_wk")] == {"changes": APPLIED_STAGE_CHANGES, "message": "Staged Apr 14 progression fix."}
    assert parts[("resp", "s_wk")] == APPLIED_STAGE_RESULT

    apply_lines = [p.function_response.response["result"] for c in req.contents for p in c.parts
                   if p.function_response and p.function_response.name == "apply_staged_changes"]
    assert apply_lines == [
        'Applied 1/1 (the app confirmed this to the runner): create 2027-06-12 event "Helsinki Half Marathon" [41502856]',
        'Applied 1/1 (the app confirmed this to the runner): update 2027-04-14 Run "Race Pace 6x1.5km" [3925887632]',
    ]

    # 24-week `id=None` `apply_training_plan` sequence collapses to a single summary line.
    sid = "sid-plan-24"
    plan_contents = [
        types.Content(role="user", parts=[types.Part(text="Build marathon plan")]),
        types.Content(role="model", parts=[_call("stage_training_plan", "p24", plan={"weeks": ["W1"] * 24}, message="24w build.")]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "p24", {"result": json.dumps(
            {"staged_id": sid, "total_weeks": 24, "sessions": 144})})]),
    ]
    for w in range(1, 25):
        state = {"staged_id": sid, "total_weeks": 24, "weeks_done": list(range(1, w + 1)),
                 "created": 6 * w, "updated": 0, "deleted": 0, "failed": 0, "failed_weeks": [], "done": w == 24}
        plan_contents += [
            types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
                name="apply_training_plan", id=None, args={"staged_id": sid, "week": w}))]),
            types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
                name="apply_training_plan", id=None, response={"result": json.dumps(
                    {"success": True, "week": w, "applied_training_plan": state})}))]),
        ]
    plan_req = LlmRequest(contents=plan_contents)
    keep_latest_reports_and_skills(None, plan_req)
    assert plan_req.contents[1].parts[0].function_call.args == {
        "plan": APPLIED_PLAN_STUB.format(weeks=24, sessions=144),
        "message": "24w build.",
    }
    apply_resps = [p.function_response.response["result"] for c in plan_req.contents for p in c.parts
                   if p.function_response and p.function_response.name == "apply_training_plan"]
    assert len(apply_resps) == 1 and "weeks 1-24 of 24 done · 144 created" in apply_resps[0]


def test_summarizer_strips_thoughts_skills_and_raw_apply_json_and_skips_mid_plan_apply():
    import asyncio

    heavy_results = [{"ok": True, "id": "3925887632", "kind": "workout", "sport": "Run", "action": "update",
                      "date": "2027-04-14", "title": "Race Pace 6x1.5km",
                      "description": "15' WU · 6x1.5km @ 4:18/km · 10' CD " * 25,
                      "replaces": {"title": "Old Threshold", "description_summary": "5x1.5km " * 20}}]
    events = [
        _event("user", 1.0, "i1", types.Part(text="Audit HM block")),
        _event("coaching_agent", 2.0, "i1",
               types.Part(text="Deep internal physiological reasoning. " * 40, thought=True),
               _call("fetch_plan_audit_data", "c_aud", start_date="2027-03-22", end_date="2027-06-12"),
               _call("load_skill", "c_sk", skill_name="plan-audit")),
        _event("user", 3.0, "i1",
               _resp("fetch_plan_audit_data", "c_aud", {"result": AUDIT}),
               _resp("load_skill", "c_sk", {"skill_name": "plan-audit", "instructions": SKILL_TEXT})),
        _event("coaching_agent", 4.0, "i1", types.Part(text="### Assessment\n- Smooth Wed thresholds.")),
        _event("user", 5.0, "i2", types.Part(text="Stage the fixes")),
        _event("coaching_agent", 6.0, "i2", _call("stage_workout_changes", "s_fail", changes=["bad code"])),
        _event("user", 7.0, "i2", _resp("stage_workout_changes", "s_fail", {"result": json.dumps(
            {"staged": 0, "needs_structure": [{"why": "bad code"}], "message": "Fallback schema " * 40})})),
        _event("coaching_agent", 8.0, "i2", _call("stage_workout_changes", "s_ok",
                                                  changes=["2027-04-14: P 6x1.5k @4:18 r2'"],
                                                  message="Staged Apr 14 fix.")),
        _event("user", 9.0, "i2", _resp("stage_workout_changes", "s_ok", {"result": json.dumps(
            {"staged": 1, "staged_id": "sid-1", "changes": ["updated 2027-04-14 Run"]})})),
        _event("user", 10.0, "i3", types.Part(text="Update TrainingPeaks")),
        _event("coaching_agent", 11.0, "i3", types.Part(function_call=types.FunctionCall(
            name="apply_staged_changes", id=None, args={"staged_id": "sid-1"}))),
        _event("user", 12.0, "i3", types.Part(function_response=types.FunctionResponse(
            name="apply_staged_changes", id=None, response={"result": json.dumps({"success": True, "results": heavy_results})}))),
    ]
    compacted, prompt = asyncio.run(_compact(events))
    assert compacted is not None
    assert "Deep internal physiological reasoning" not in prompt
    assert "load_skill" not in prompt
    assert "Fallback schema" not in prompt
    assert "Old Threshold" not in prompt
    assert 'Applied 1/1 (the app confirmed this to the runner): update 2027-04-14 Run "Race Pace 6x1.5km" [3925887632]' in prompt
    assert "<= 160 words" in prompt and "APPLIED" in prompt and "STAGED/PROPOSED" in prompt

    # Mid-stream `apply_training_plan` (`done: False`) skips compaction completely (`0` LLM calls).
    mid_apply_events = [
        *events,
        _event("coaching_agent", 13.0, "i4", _call("apply_training_plan", "ap_w1", staged_id="p1", week=1)),
        _event("user", 14.0, "i4", _resp("apply_training_plan", "ap_w1", {"result": json.dumps(
            {"success": True, "week": 1, "applied_training_plan": {"done": False, "weeks_done": [1], "total_weeks": 20}})})),
    ]
    llm = FakeLlm()
    skipped = asyncio.run(ReportMemorySummarizer(llm=llm).maybe_summarize_events(events=mid_apply_events))
    assert skipped is None and llm.prompts == []


def test_intra_turn_routing_locks_call1_prefix_on_call2_then_stubs_superseded_report_next_turn():
    """Regression for trace 3c13079daa2eb72e: when Call 1 of a conversational turn routes to `get_schedule`,
    Call 2 (860ms later) must keep `contents[:len(call1.contents)]` 100% byte-identical to Call 1 so Vertex's
    KV cache hits through the entire prior conversation, then stub the older schedule on the next turn."""
    from google.adk.models.llm_request import LlmRequest
    from running_coach.coach.coaching.quick_actions import SYNTHETIC_THOUGHT_SIGNATURE
    from running_coach.coach.report_memory import _SYNTHETIC_THOUGHT_SIG

    assert _SYNTHETIC_THOUGHT_SIG == SYNTHETIC_THOUGHT_SIGNATURE

    jan_sched = "### Schedule (2027-01-11 – 2027-02-07)\n\n* **2027-02-01 – Feb 07**: 29.4 km"
    dec_sched = "### Schedule (2026-11-16 – 2026-12-27)\n\n* **2026-11-30 – Dec 06**: 48.2 km"

    base_history = [
        types.Content(role="user", parts=[types.Part(text="Im looking at race week of feb 7th")]),
        types.Content(role="model", parts=[_call("get_schedule", "gs_jan", start_date="2027-01-11", end_date="2027-02-07")]),
        types.Content(role="user", parts=[_resp("get_schedule", "gs_jan", {"result": jan_sched})]),
        types.Content(role="model", parts=[types.Part(text="29.4 km is too aggressive.")]),
        types.Content(role="user", parts=[types.Part(text="Keep Sunday as is, stage the rest")]),
        types.Content(role="model", parts=[_call("stage_workout_changes", "s_feb", changes=["2027-02-03: E 10"], message="Staged.")]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "s_feb", {"result": '{"staged": 1, "staged_id": "sid-feb"}'})]),
        types.Content(role="user", parts=[types.Part(text="Update TrainingPeaks")]),
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            name="apply_staged_changes", id=None, args={"staged_id": "sid-feb"}))]),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="apply_staged_changes", id=None, response={"result": json.dumps({"success": True, "results": [
                {"ok": True, "id": "w1", "action": "update", "date": "2027-02-03", "sport": "Run", "title": "Easy Run 10 km"}
            ]})}))]),
        types.Content(role="user", parts=[types.Part(text="So next week I strat with interval and threshold, is 6x 400m not too little?")]),
    ]

    # Call 1 (routing): compacts applied staging at s_feb and keeps jan_sched verbatim.
    call1_req = LlmRequest(contents=list(base_history))
    keep_latest_reports_and_skills(None, call1_req)

    # Call 2 (synthesis, same turn): real LLM routing call (no synthetic signature) + dec_sched response.
    call2_req = LlmRequest(contents=[
        *base_history,
        types.Content(role="model", parts=[_call("get_schedule", "gs_dec", start_date="2026-11-16", end_date="2027-01-03")]),
        types.Content(role="user", parts=[_resp("get_schedule", "gs_dec", {"result": dec_sched})]),
    ])
    keep_latest_reports_and_skills(None, call2_req)
    assert call2_req.contents[: len(call1_req.contents)] == call1_req.contents
    assert call2_req.contents[-1].parts[0].function_response.response["result"] == dec_sched

    # Next turn (Turn 6): jan_sched is now stubbed cleanly while dec_sched stays verbatim.
    turn6_req = LlmRequest(contents=[
        *call2_req.contents,
        types.Content(role="model", parts=[types.Part(text="6x400m is the right ceiling for Week 1.")]),
        types.Content(role="user", parts=[types.Part(text="And what about Friday's threshold?")]),
    ])
    keep_latest_reports_and_skills(None, turn6_req)
    by_id = {p.function_response.id: p.function_response.response["result"]
             for c in turn6_req.contents for p in c.parts
             if p.function_response and p.function_response.name == "get_schedule"}
    assert by_id["gs_jan"] == "[superseded: the latest Schedule output is further below]"
    assert by_id["gs_dec"] == dec_sched

    # 1-call pre-dispatched turns (carrying SYNTHETIC_THOUGHT_SIGNATURE) had no Call 1, so they stub immediately.
    predispatched_req = LlmRequest(contents=[
        *base_history[:-1],
        types.Content(role="user", parts=[types.Part(text="Pull up next week")]),
        types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name="get_schedule", id="qa_dec", args={}),
            thought_signature=SYNTHETIC_THOUGHT_SIGNATURE,
        )]),
        types.Content(role="user", parts=[_resp("get_schedule", "qa_dec", {"result": dec_sched})]),
    ])
    keep_latest_reports_and_skills(None, predispatched_req)
    pre_by_id = {p.function_response.id: p.function_response.response["result"]
                 for c in predispatched_req.contents for p in c.parts
                 if p.function_response and p.function_response.name == "get_schedule"}
    assert pre_by_id["gs_jan"] == "[superseded: the latest Schedule output is further below]"
    assert pre_by_id["qa_dec"] == dec_sched


def test_abandoned_failed_stagings_stale_guard_messages_and_summarizer_token_cap():
    import asyncio
    from google.adk.models.llm_request import LlmRequest
    from running_coach.coach.report_memory import (
        MAX_SUMMARY_OUTPUT_TOKENS,
        REPLACED_PLAN_RESULT,
        REPLACED_PLAN_STUB,
    )

    req = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Stage something custom")]),
        types.Content(role="model", parts=[_call("stage_workout_changes", "ab_wk", changes=["bad"])]),
        types.Content(role="user", parts=[_resp("stage_workout_changes", "ab_wk", {"result": json.dumps(
            {"staged": 0, "needs_structure": [{"why": "missing steps"}], "message": "Schema dump " * 50})})]),
        types.Content(role="model", parts=[_call("stage_training_plan", "ab_pl", plan={"weeks": ["bad"]})]),
        types.Content(role="user", parts=[_resp("stage_training_plan", "ab_pl", {"result": json.dumps(
            {"staged": 0, "errors": [{"week": 1, "why": "bad"}]})})]),
        types.Content(role="model", parts=[_call("fetch_plan_audit_data", "g_old")]),
        types.Content(role="user", parts=[_resp("fetch_plan_audit_data", "g_old", {
            "result": "fetch_plan_audit_data was not run: it renders the plan audit report..."
        })]),
        types.Content(role="model", parts=[types.Part(text="Which distance did you mean?")]),
        # Next turn: runner pivots without re-staging; active turn also has a live guard message.
        types.Content(role="user", parts=[types.Part(text="Never mind, should I wear carbon shoes?")]),
        types.Content(role="model", parts=[_call("get_schedule", "g_live")]),
        types.Content(role="user", parts=[_resp("get_schedule", "g_live", {
            "result": "get_schedule was not run: 2026-12-01..2026-12-07 is already in the active ### Schedule"
        })]),
    ])
    keep_latest_reports_and_skills(None, req)

    calls = {p.function_call.id: p.function_call.args for c in req.contents for p in c.parts if p.function_call}
    resps = {p.function_response.id: p.function_response.response for c in req.contents for p in c.parts if p.function_response}
    assert calls["ab_wk"] == REPLACED_STAGE_ARGS and resps["ab_wk"] == REPLACED_STAGE_RESULT
    assert calls["ab_pl"] == {"plan": REPLACED_PLAN_STUB} and resps["ab_pl"] == REPLACED_PLAN_RESULT
    assert resps["g_old"] == {"result": "[fetch_plan_audit_data skipped earlier]"}
    assert "already in the active ### Schedule" in resps["g_live"]["result"]

    # Summarizer enforces MAX_SUMMARY_OUTPUT_TOKENS on every compaction request.
    seen_configs = []

    class ConfigCapturingLlm(FakeLlm):
        async def generate_content_async(self, llm_request, stream=False):
            seen_configs.append(llm_request.config)
            async for item in super().generate_content_async(llm_request, stream=stream):
                yield item

    asyncio.run(ReportMemorySummarizer(llm=ConfigCapturingLlm()).maybe_summarize_events(events=_session_events()))
    assert len(seen_configs) == 1 and seen_configs[0].max_output_tokens == MAX_SUMMARY_OUTPUT_TOKENS





