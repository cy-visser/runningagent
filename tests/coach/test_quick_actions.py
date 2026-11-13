"""Behavioural test for web quick actions: deterministic dispatch scoped to the feature turn only."""

import asyncio
import json
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import app
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.coach.coaching.quick_actions import (
    DISPATCHED_STATE_KEY,
    QUICK_ACTION_PART_PREFIX,
    QUICK_ACTION_STATE_KEY,
)
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL


class RecordingLlm(BaseLlm):
    """Fake Gemini: records every request and answers with plain text (never calls tools)."""

    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Coach reply")]))


def _system_text(req: LlmRequest) -> str:
    si = req.config.system_instruction if req.config else None
    if isinstance(si, str):
        return si
    return "".join(p.text or "" for p in getattr(si, "parts", None) or [])


def _tool_mode(req: LlmRequest):
    tc = req.config.tool_config if req.config else None
    return tc.function_calling_config.mode if tc and tc.function_calling_config else None


async def _turn(runner, session_id: str, text: str, action: dict | None = None) -> list:
    # Same transport as the web BFF in production: the action is an extra message part (Agent Runtime's
    # /api/run_sse drops state_delta, so no state carries it here).
    parts = [types.Part(text=text)]
    if action:
        parts.append(types.Part(text=QUICK_ACTION_PART_PREFIX + json.dumps(action)))
    events = []
    async for ev in runner.run_async(
        user_id="web_runner", session_id=session_id, state_delta={AUTH_EMAIL_STATE_KEY: EMAIL},
        new_message=types.Content(role="user", parts=parts),
    ):
        events.append(ev)
    return events


def _calls(events: list) -> list[tuple[str, dict]]:
    return [(p.function_call.name, dict(p.function_call.args or {}))
            for e in events if e.content for p in e.content.parts or [] if p.function_call]


def test_quick_action_dispatches_without_routing_and_chat_keeps_full_capabilities(runner, monkeypatch):
    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")

        # 1. Feature button: skill + data tool run without an LLM routing call; one LLM call writes the report.
        feature = await _turn(r, session.id, "Trend analysis for the past 6 months",
                              {"skill": "trend-analysis", "args": {"weeks": 12, "bogus": 1}})
        feature_requests = list(llm.requests)

        # 2. Typed chat in the same session: full instruction, catalog and tool calling.
        chat = await _turn(r, session.id, "What should I do tomorrow?")
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return feature, feature_requests, chat, s

    feature, feature_requests, chat, s = asyncio.run(scenario())

    assert _calls(feature) == [("load_skill", {"skill_name": "trend-analysis"}), ("fetch_trend_data", {"weeks": 12})]
    assert s.state.get("trend_report_data", {}).get("version") == 1          # the tool really ran
    assert len(feature_requests) == 1                                          # report call only
    report = feature_requests[0]
    assert _tool_mode(report) == types.FunctionCallingConfigMode.NONE
    assert report.config.tools == []                                           # zero tool schemas leaked on report
    report_si = _system_text(report)
    assert "SKILL ROUTING" not in report_si and "<available_skills>" not in report_si
    assert "CRITICAL COACHING CONTRACT" in report_si
    roles = [(c.role, [bool(p.function_call) for p in c.parts]) for c in report.contents]
    assert ("model", [True, True]) in roles                                    # synthesized calls in history

    assert _calls(chat) == []
    chat_req = llm.requests[-1]
    assert len(llm.requests) == 2
    assert _tool_mode(chat_req) is None
    chat_si = _system_text(chat_req)
    assert "SKILL ROUTING" in chat_si and "<available_skills>" in chat_si
    assert QUICK_ACTION_STATE_KEY not in s.state and DISPATCHED_STATE_KEY not in s.state
    # The action part never reaches the persisted history or any LLM request.
    user_texts = [p.text or "" for e in s.events if e.author == "user" for p in e.content.parts or []]
    assert "Trend analysis for the past 6 months" in user_texts
    assert not any(QUICK_ACTION_PART_PREFIX in t for t in user_texts)
    assert not any(QUICK_ACTION_PART_PREFIX in (p.text or "")
                   for req in llm.requests for c in req.contents for p in c.parts or [])


def test_update_trainingpeaks_button_applies_staged_changes_without_any_llm_call(runner, monkeypatch):
    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)
    staged_id = "0f8fad5b-d9cb-469f-a165-70867728950e"
    staged = {"staged_id": staged_id, "changes": [
        {"kind": "workout", "action": "update", "date": "2026-11-03", "sport": "Run", "title": "Threshold 4x2km",
         "workout_id": "w111", "replaces_title": "Threshold 2 x 15'", "distance_km": 12.0,
         "duration_minutes": 65.0, "tss_planned": 78.0},
        {"kind": "workout", "action": "create", "date": "2026-11-04", "sport": "Run", "title": "Recovery Run",
         "workout_id": None, "distance_km": 6.0, "duration_minutes": None, "tss_planned": None},
    ]}

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(
            app_name="running_coach", user_id="web_runner", state={"staged_workout_changes": staged})
        events = await _turn(r, session.id, "Update TrainingPeaks",
                             {"skill": "workout-creator", "args": {"staged_id": staged_id}})
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return events, s

    events, s = asyncio.run(scenario())

    assert llm.requests == []                                                   # zero LLM calls
    assert _calls(events) == [("apply_staged_changes", {"staged_id": staged_id})]  # no load_skill
    writes = sorted(name for name, _ in runner.tp_calls if name.startswith("tp_") and name != "tp_get_workouts")
    assert writes == ["tp_create_workout", "tp_update_workout"]
    final = [w.payload["data"]["text"] for e in events for w in e.actions.render_ui_widgets or []][-1]
    assert events[-1].is_final_response() and events[-1].actions.skip_summarization
    assert final.startswith("✅ **TrainingPeaks updated:** 2 workouts.")
    assert ("| Updated | Tue 03 Nov | **Threshold 2 x 15'** | **Threshold 4x2km** · 12 km · 65 min · TSS 78 |"
            in final)  # older staged set without `replaces`: Before falls back to replaces_title
    assert s.state.get("staged_workout_changes") is None
    assert s.state["applied_workout_changes"]["staged_id"] == staged_id


def test_a_tools_off_report_call_never_runs_a_function_call_the_model_returns_anyway():
    from running_coach.coach.coaching.quick_actions import drop_disabled_tool_calls
    from running_coach.tests.fakes import FakeContext

    response = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(text="### Report"),
        types.Part(function_call=types.FunctionCall(name="stage_workout_changes", args={"changes": []})),
    ]))
    report_call = FakeContext(state={DISPATCHED_STATE_KEY: "inv-1"})  # this invocation's report call
    dropped = drop_disabled_tool_calls(report_call, response)
    assert [p.text for p in dropped.content.parts] == ["### Report"]
    assert response.content.parts[1].function_call  # the original response object is untouched

    chat_turn = FakeContext(state={DISPATCHED_STATE_KEY: "an-earlier-invocation"})  # typed chat: tools on
    assert drop_disabled_tool_calls(chat_turn, response) is None
    assert drop_disabled_tool_calls(report_call, LlmResponse(content=types.Content(
        role="model", parts=[types.Part(text="only text")]))) is None


def test_build_plan_intake_reads_the_next_unplanned_goal_in_code_and_writes_one_short_opener(runner, monkeypatch):
    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)
    # The 5K sub goal is already past; mark the 10K planned so the north star is the next unplanned goal.
    runner.profiles["cyrille_visser"]["sub_goals"][1]["planned"] = True

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        events = await _turn(r, session.id, "I'd like to build a new training plan", {"skill": "plan-builder:intake", "args": {"x": 1}})
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return events, s

    events, s = asyncio.run(scenario())
    assert _calls(events) == [("fetch_plan_context", {})]          # in code: no load_skill, no routing call
    context = next(str(p.function_response.response) for e in events if e.content
                   for p in e.content.parts or [] if p.function_response)
    assert "PLAN CONTEXT (new): 2027-02-15 →" in context            # day after the 10K race: the north star
    assert len(llm.requests) == 1                                  # the opener is the only model call
    call = llm.requests[0]
    assert _tool_mode(call) == types.FunctionCallingConfigMode.NONE
    assert call.config.tools == []                                 # zero tool schemas leaked on intake
    assert call.config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    system = _system_text(call)
    assert "PLAN INTAKE" in system and "SKILL ROUTING" not in system
    assert "NEXT UNPLANNED GOAL: Sub-3:15 Marathon (London Marathon 2028)" in system


def test_turn_after_build_plan_intake_stages_in_one_llm_call_without_reading_history_twice(runner, monkeypatch):
    class StagingAndRevisingLlm(BaseLlm):
        requests: list = []

        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            self.requests.append(llm_request)
            if len(self.requests) == 1:
                yield LlmResponse(content=types.Content(
                    role="model", parts=[types.Part(text="Proposed block — how many days can you run?")]))
                return
            if len(self.requests) == 2:
                yield LlmResponse(content=types.Content(role="model", parts=[
                    types.Part(function_call=types.FunctionCall(
                        id="stage-1",
                        name="stage_training_plan",
                        args={
                            "plan": {"weeks": ["W1 | base | Aerobic base | Tue: E 8 | Thu: T 2x15' r2' | Sun: L 18"]},
                            "message": "### Block Strategy\n\n1. **Volume & Long Runs:** Four-day base progression.",
                        },
                    )),
                ]))
                return
            yield LlmResponse(content=types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(
                    id="stage-2",
                    name="stage_training_plan",
                    args={
                        "plan": {"weeks": ["W1 | build | Double threshold + MP | Tue: I 6x1k r2' | Thu: T 3x10' r2' | Sun: L 22 +6@M"]},
                        "message": "### Plan Update\n\n1. **Intensity & Rhythm:** Added VO2max + MP finish.",
                    },
                )),
            ]))

    llm = StagingAndRevisingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)
    runner.profiles["cyrille_visser"]["sub_goals"][1]["planned"] = True

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        await _turn(r, session.id, "I'd like to build a new training plan", {"skill": "plan-builder:intake"})
        runner.tp_calls.clear()
        turn2 = await _turn(r, session.id, "6 days a week, long run on Sunday, no travel — build it!")
        s2 = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        first_id = s2.state["staged_training_plan"]["staged_id"]
        runner.tp_calls.clear()
        turn3 = await _turn(r, session.id, "I want a ton of quality")
        s3 = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return turn2, turn3, first_id, s3

    turn2, turn3, first_id, s = asyncio.run(scenario())
    # Turn 1 (intake) + Turn 2 (stage) + Turn 3 (revise): exactly 1 LLM call per turn, all LOW thinking!
    assert len(llm.requests) == 3
    for req in llm.requests:
        assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW

    turn2_req, turn3_req = llm.requests[1], llm.requests[2]
    for req in (turn2_req, turn3_req):
        declared = {d.name for t in (req.config.tools or []) for d in (t.function_declarations or [])}
        assert "stage_training_plan" in declared
        assert "<plan_builder_protocol>" in _system_text(req)

    # Prefix-cache invariant: Turn 2 and Turn 3 have 100% byte-identical system_instruction (no mutating UUID),
    # <runner_profile> sits before <plan_builder_protocol>, and staged_id is already in Turn 3's tool response!
    turn2_sys, turn3_sys = _system_text(turn2_req), _system_text(turn3_req)
    assert turn2_sys == turn3_sys
    assert first_id not in turn3_sys
    assert turn3_sys.index("<runner_profile>") < turn3_sys.index("<plan_builder_protocol>")
    assert "ONLY the changed weeks" in turn3_sys and "delta-only `### Plan Update`" in turn3_sys
    assert "### Block Strategy" in turn3_sys and "<= 120 words" in turn3_sys
    assert any(
        p.function_response and first_id in str(p.function_response.response)
        for c in turn3_req.contents for p in c.parts or []
    )
    assert [name for name, _ in _calls(turn2)] == ["stage_training_plan"]
    assert [name for name, _ in _calls(turn3)] == ["stage_training_plan"]
    assert "tp_get_athlete_settings" not in {n for n, _ in runner.tp_calls}
    assert "tp_get_fitness" not in {n for n, _ in runner.tp_calls}
    assert s.state["staged_training_plan"]["staged_id"] != first_id
    assert s.state["staged_training_plan"]["weeks"][0]["start"] == "2027-02-15"
    assert s.state["staged_training_plan"]["weeks"][0]["phase"] == "build"

    # Compaction fallback: if staged_id was compacted out of contents, it is injected transiently in contents (never system_instruction).
    from types import SimpleNamespace
    from running_coach.coach.coaching.skill_toolset import skill_toolset

    compacted_req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="make W4 easier")])])
    asyncio.run(
        skill_toolset.process_llm_request(
            tool_context=SimpleNamespace(state={"staged_training_plan": {"staged_id": "compacted-sid"}}, invocation_id="i9"),
            llm_request=compacted_req,
        )
    )
    assert "compacted-sid" not in _system_text(compacted_req)
    assert any("compacted-sid" in (p.text or "") for c in compacted_req.contents for p in c.parts or [])


def test_a_stale_plan_builder_action_falls_back_to_routing(runner, monkeypatch):
    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)
    args = {"start_date": "2026-11-02", "end_date": "2027-01-31", "mode": "new"}

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        events = await _turn(r, session.id, "I'd like to build a new training plan", {"skill": "plan-builder", "args": args})
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return events, s

    events, s = asyncio.run(scenario())
    assert _calls(events) == []                                    # nothing dispatched in code
    assert len(llm.requests) == 1
    call = llm.requests[0]
    assert _tool_mode(call) is None                                # a normal chat turn: tools on
    assert {"record_key_event", "fetch_plan_context", "stage_training_plan"} <= set(call.tools_dict)
    system = _system_text(call)
    assert "NEXT UNPLANNED GOAL" in system and "KEY EVENTS:" in system and "PLAN INTAKE" not in system
    assert DISPATCHED_STATE_KEY not in s.state


def test_apply_plan_button_writes_one_week_without_any_llm_call(runner, monkeypatch):
    from running_coach.features.plan_builder.stage_training_plan_tool import stage_training_plan

    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)
    ctx = runner.ctx()
    plan = {"start_date": "2026-11-02", "weeks": [
        {"week": n, "phase": "base", "days": {"Tue": "I 6x1k r2'", "Wed": "S 30' core-hips", "Sun": "L 20"}}
        for n in (1, 2)]}
    staged_id = json.loads(asyncio.run(stage_training_plan(ctx, plan)))["staged_id"]
    staged = ctx.state["staged_training_plan"]
    runner.tp_calls.clear()

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(
            app_name="running_coach", user_id="web_runner", state={"staged_training_plan": staged})
        events = await _turn(r, session.id, "", {"skill": "plan-builder:apply",
                                                 "args": {"staged_id": staged_id, "week": 1}})
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return events, s

    events, s = asyncio.run(scenario())
    assert llm.requests == []                                                     # zero LLM calls
    assert _calls(events) == [("apply_training_plan", {"staged_id": staged_id, "week": 1})]  # no load_skill
    writes = sorted({kw.get("date", "")[:10] for n, kw in runner.tp_calls if n in ("tp_create_workout", "tp_update_workout")})
    assert writes and all(d <= "2026-11-08" for d in writes)                      # week 1 only
    assert s.state["applied_training_plan"]["weeks_done"] == [1]
    assert events[-1].actions.skip_summarization
    assert not [w for e in events for w in e.actions.render_ui_widgets or []]    # intermediate week: no bubble
