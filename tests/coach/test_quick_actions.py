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
    PLAN_INTAKE_STATE_KEY,
    QUICK_ACTION_PART_PREFIX,
    QUICK_ACTION_STATE_KEY,
    SYNTHESIS_GUARD_STATE_KEY,
    SYNTHETIC_THOUGHT_SIGNATURE,
    TREND_PROTOCOL_START,
    TREND_SYNTHESIS_STATE_KEY,
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

        # 2. Typed chat in the same session: full instruction, catalog, tool calling, AND byte-identical Turn-0 prefix.
        chat = await _turn(r, session.id, "What should I do tomorrow?")
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return feature, feature_requests, chat, s

    feature, feature_requests, chat, s = asyncio.run(scenario())

    assert _calls(feature) == [("fetch_trend_data", {"weeks": 12})]            # UI-only skill-free dispatch
    assert s.state.get("trend_report_data", {}).get("version") == 1          # the tool really ran
    assert len(feature_requests) == 1                                          # report call only
    report = feature_requests[0]
    assert _tool_mode(report) is None
    assert report.config.tools                                                 # full prefix kept to warm cache
    declared = {d.name for t in report.config.tools for d in getattr(t, "function_declarations", None) or []}
    assert "fetch_trend_data" not in declared                                  # hidden from LLM tool declarations
    report_si = _system_text(report)
    assert "SKILL ROUTING" in report_si and "<available_skills>" in report_si
    assert "trend-analysis" not in report_si and "fetch_trend_data" not in report_si
    assert "CRITICAL COACHING CONTRACT" in report_si
    roles = [(c.role, [bool(p.function_call) for p in c.parts]) for c in report.contents]
    assert ("model", [True]) in roles                                          # synthesized fetch_trend_data only
    # Transient trend synthesis rubric sits after the tool response on Turn 0 only (never persisted).
    assert report.contents[3].role == "user"
    assert TREND_PROTOCOL_START in (report.contents[3].parts[0].text or "")
    assert "### 🎯 Next Block: Top 3" in (report.contents[3].parts[0].text or "")

    assert _calls(chat) == []
    chat_req = llm.requests[-1]
    assert len(llm.requests) == 2
    assert _tool_mode(chat_req) is None
    # Prefix-cache & token invariant across Turn 0 -> Turn 1: thinking_level, system_instruction, tools,
    # and contents[0..2] (including SYNTHETIC_THOUGHT_SIGNATURE and Turn-0 trend data) stay byte-identical,
    # while the transient Turn-0 rubric is completely absent from Turn 1 (0 rubric tokens carried forward).
    assert report.config.thinking_config == chat_req.config.thinking_config
    assert _system_text(report) == _system_text(chat_req)
    assert report.config.tools == chat_req.config.tools
    assert report.contents[:3] == chat_req.contents[:3]
    assert not any(
        TREND_PROTOCOL_START in (p.text or "") for c in chat_req.contents for p in c.parts or []
    )
    assert chat_req.contents[1].parts[0].thought_signature == SYNTHETIC_THOUGHT_SIGNATURE
    assert QUICK_ACTION_STATE_KEY not in s.state and SYNTHESIS_GUARD_STATE_KEY not in s.state
    assert TREND_SYNTHESIS_STATE_KEY not in s.state
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
    for state_key in (SYNTHESIS_GUARD_STATE_KEY, PLAN_INTAKE_STATE_KEY):
        guarded = FakeContext(state={state_key: "inv-1"}, invocation_id="inv-1")
        dropped = drop_disabled_tool_calls(guarded, response)
        assert [p.text for p in dropped.content.parts] == ["### Report"]
        assert response.content.parts[1].function_call  # the original response object is untouched

        chat_turn = FakeContext(state={state_key: "an-earlier-invocation"}, invocation_id="inv-2")
        assert drop_disabled_tool_calls(chat_turn, response) is None
        assert drop_disabled_tool_calls(guarded, LlmResponse(content=types.Content(
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
    assert "- North star: Sub-3:15 Marathon (London Marathon 2028)" in system
    assert "NEXT UNPLANNED GOAL (window 2027-02-15..2028-04-23)" in system


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
    # Turn 1 (intake: LOW) + Turn 2 (stage: MEDIUM) + Turn 3 (revise: MEDIUM): 1 LLM call per turn.
    assert len(llm.requests) == 3
    assert llm.requests[0].config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert llm.requests[1].config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
    assert llm.requests[2].config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM

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
    assert {"get_schedule", "fetch_plan_context", "stage_training_plan"} <= set(call.tools_dict)
    assert "record_key_event" not in call.tools_dict
    system = _system_text(call)
    assert "NEXT UNPLANNED GOAL" in system and "KEY EVENTS" not in system and "PLAN INTAKE" not in system
    assert PLAN_INTAKE_STATE_KEY not in s.state and SYNTHESIS_GUARD_STATE_KEY not in s.state


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


def test_typed_standalone_workout_and_report_prompts_pre_dispatch_and_auto_align_sport_skill(runner, monkeypatch):
    from datetime import date
    from running_coach.coach.coaching.quick_actions import infer_typed_quick_action

    today = date(2026, 11, 15)
    assert infer_typed_quick_action("Analyze todays bike session", today) == {
        "skill": "bike-workout-analysis",
        "args": {"date_str": "today", "sport": "bike"},
    }
    assert infer_typed_quick_action("Analyze oct 15th", today) == {
        "skill": "workout-analysis",
        "args": {"date_str": "2026-10-15"},
    }
    assert infer_typed_quick_action("Analyze oct 15th — why was my HR so high?", today) == {
        "skill": "workout-analysis",
        "args": {"date_str": "2026-10-15"},
    }
    assert infer_typed_quick_action(
        "Analyze today's tempo run. Did my HR drift too much in the last 3 km?", today
    ) == {
        "skill": "workout-analysis",
        "args": {"date_str": "today", "sport": "run"},
    }
    assert infer_typed_quick_action(
        "Can you analyze yesterday's bike ride?\nMy power faded in block 3.", today
    ) == {
        "skill": "bike-workout-analysis",
        "args": {"date_str": "2026-11-14", "sport": "bike"},
    }
    assert infer_typed_quick_action(
        "Analyze today's 10k run. Did I push too hard early?", today
    ) == {
        "skill": "workout-analysis",
        "args": {"date_str": "today", "sport": "run"},
    }
    assert infer_typed_quick_action(
        "Analyze oct 22nd. Did my cadence drop in the second half?", today
    ) == {
        "skill": "workout-analysis",
        "args": {"date_str": "2026-10-22"},
    }
    assert infer_typed_quick_action("Audit my plan", today) == {"skill": "plan-audit", "args": {}}
    # Mutations, comparisons, injuries, races, goals, or open questions stay on normal LLM routing.
    for non_match in (
        "Analyze today's run and move Thursday's tempo",
        "Analyze today's run. Compare it with Oct 15th.",
        "Analyze today's run. My calf started hurting at km 8.",
        "Analyze today's race. Did I pace it right?",
        "Analyze my marathon goal",
        "My calf hurt on today's run",
        "What should I do tomorrow?",
    ):
        assert infer_typed_quick_action(non_match, today) is None, non_match

    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        # 1. Explicit bike typed prompt -> 1 LLM call, bike-workout-analysis loaded, full prefix kept for caching.
        bike_events = await _turn(r, session.id, "Analyze oct 22nd bike session")
        # 2. Multi-sentence date-only typed prompt on a bike-only day (2026-10-22 is Z2 Spin) -> pre-dispatches
        #    without sport, keeps the runner's question verbatim, and align_workout_skill auto-swaps to bike!
        date_only_events = await _turn(r, session.id, "Analyze oct 22nd. Did my cadence drop in the second half?")
        return bike_events, date_only_events

    bike_events, date_only_events = asyncio.run(scenario())
    assert _calls(bike_events) == [
        ("analyze_workout", {"date_str": "2026-10-22", "sport": "bike"}),
        ("load_skill", {"skill_name": "bike-workout-analysis"}),
    ]
    assert _calls(date_only_events) == [
        ("analyze_workout", {"date_str": "2026-10-22"}),
        ("load_skill", {"skill_name": "workout-analysis"}),
    ]
    assert len(llm.requests) == 2
    for req in llm.requests:
        assert req.config.tools
        assert "SKILL ROUTING" in _system_text(req)
    assert _system_text(llm.requests[0]) == _system_text(llm.requests[1])
    assert llm.requests[0].config.tools == llm.requests[1].config.tools
    assert any("cadence drop" in (p.text or "") for c in llm.requests[1].contents for p in c.parts or [])
    # Date-only synthesis request received the swapped bike-workout-analysis protocol:
    swapped_resps = [
        p.function_response.response
        for p in llm.requests[1].contents[-1].parts or []
        if p.function_response and p.function_response.name == "load_skill"
    ]
    assert len(swapped_resps) == 1 and swapped_resps[0]["skill_name"] == "bike-workout-analysis"
    assert "# Bike Workout Analysis Skill" in swapped_resps[0]["instructions"]


def test_typed_dated_audit_and_trend_questions_pre_dispatch_in_one_call_and_fallback_trims_step2(runner, monkeypatch):
    from datetime import date, datetime
    from running_coach.coach.coaching.quick_actions import infer_typed_quick_action

    today = date(2026, 11, 16)
    rich_audit_prompt = (
        "Audit my 5k block from Nov 30th until feb 7th. "
        "Im aiming to run a 5k on Feb 7th between 20:40 and 20:55. "
        "I want to know if my threshold and intervals are progressive enough and will set me up to reach my goal. "
        "I have a week of holiday planned between Dec 19th and Dec 26th."
    )
    expected_5k_audit = {
        "skill": "plan-audit",
        "args": {"start_date": "2026-11-30", "end_date": "2027-02-07"},
    }
    assert infer_typed_quick_action(rich_audit_prompt, today) == expected_5k_audit
    # Multi-paragraph, semicolon-separated, "build" noun, and long (>90 words) briefs all pre-dispatch with no length cap:
    assert infer_typed_quick_action(
        "Audit my 5k block from Nov 30th until Feb 7th.\n\n"
        "Target: 20:40-20:55 on Feb 7th.\n"
        "Are my threshold sessions progressive enough given my Dec 19-26 holiday?",
        today,
    ) == expected_5k_audit
    assert infer_typed_quick_action(
        "Audit my 5k build from Nov 30th until Feb 7th; are my easy runs too fast for recovery?",
        today,
    ) == expected_5k_audit
    long_brief = (
        "Audit my 5k block from Nov 30th until Feb 7th. "
        "I am targeting a sub-21 5k on Feb 7th and want a thorough look at how the progression builds across December and January. "
        "Specifically I care about whether my threshold volume, VO2max intervals, and recovery weeks align well with my current fitness, "
        "and whether my planned holiday between Dec 19th and Dec 26th leaves enough ramp-up before peak week and taper. "
        "Which key session in January will give me the clearest signal that sub-21 shape is realistic?"
    )
    assert len(long_brief.split()) > 80
    assert infer_typed_quick_action(long_brief, today) == expected_5k_audit
    assert infer_typed_quick_action("Audit my plan for the next 6 weeks. Is my taper enough?", today) == {
        "skill": "plan-audit",
        "args": {"start_date": "2026-11-16", "end_date": "2026-12-28"},
    }
    assert infer_typed_quick_action("Audit the next 6 weeks", today) == {
        "skill": "plan-audit",
        "args": {"start_date": "2026-11-16", "end_date": "2026-12-28"},
    }
    assert infer_typed_quick_action("Audit the next 3 months. Are my volume trends sustainable?", today) == {
        "skill": "plan-audit",
        "args": {"start_date": "2026-11-16", "end_date": "2027-02-16"},
    }
    assert infer_typed_quick_action("Audit my plan for the next 2 months", date(2026, 12, 31)) == {
        "skill": "plan-audit",
        "args": {"start_date": "2026-12-31", "end_date": "2027-02-28"},
    }
    assert infer_typed_quick_action("Audit my plan. Am I ramping too fast?", today) == {
        "skill": "plan-audit",
        "args": {},
    }
    assert infer_typed_quick_action("Weekly check-in. Am I ready for Sunday's long run?", today) == {
        "skill": "check-in-report",
        "args": {},
    }
    # Year-boundary rollovers in both directions:
    assert infer_typed_quick_action("Audit my block from Jan 4th until Mar 15th", date(2026, 12, 20)) == {
        "skill": "plan-audit",
        "args": {"start_date": "2027-01-04", "end_date": "2027-03-15"},
    }
    assert infer_typed_quick_action("Audit my block from Dec 15th until Feb 14th", date(2027, 1, 5)) == {
        "skill": "plan-audit",
        "args": {"start_date": "2026-12-15", "end_date": "2027-02-14"},
    }
    # Typed trend prompts (UI-button-only), mutation/staging/weather/event, tail date-window, second report,
    # pasted plan, or undated named/vague blocks stay on LLM routing (never pre-dispatched to trend-analysis):
    for non_match in (
        "Analyze my trends for the last 12 weeks. Are my easy paces improving?",
        "Trend analysis for the past 6 months",
        "Analyze my trends for the last 3 weeks",
        "Analyze my trends. Look at the last 16 weeks.",
        "Audit the next few months",
        "Audit my plan. Look at the next 3 months.",
        "Audit my plan from Nov 30 to Feb 7 and move Friday S&C",
        "Audit my plan and drop Friday's S&C",
        "Audit my Amsterdam Half block",
        "Audit my plan. Specifically look at Nov 30th until Feb 7th.",
        "Audit my 5k block from Nov 30th until Feb 7th. Also analyze yesterday's run.",
        "Audit my 5k block from Nov 30th until Feb 7th. Can you rework the January weeks?",
        "Audit my 5k block from Nov 30th until Feb 7th. Build me a new January block.",
        "Audit my plan:\n- Mon: 10k\n- Tue: 12k",
        "Audit my plan. What should my race carb loading be?",
        "Check in report — I strained my calf yesterday",
        "I am going on a holiday between Dec 20th and Dec 26th. Can you look at my calendar and tell me what runs are scheduled?",
    ):
        assert infer_typed_quick_action(non_match, today) is None, non_match

    # End-to-end:
    # 1. Fresh-session rich 57-word typed audit runs in 1 LLM call AND keeps the full prefix to warm cache.
    # 2. Fallback undated named-block audit ("Audit my Amsterdam Half block") routes on Call 1 with byte-identical
    #    Turn-1 prefix, emits real thought_signature on Call 1, keeps Call 2 identical, and drops stray calls.
    # 3. Fallback audit + mutation keeps tools active AND inherits Turn 2's completed thought_signature verbatim
    #    (preventing Turn-1 prefix-cache invalidation on 2-call turns!).
    # 4. Warm-session typed pre-dispatch ("Audit my plan") skips Call 1 in code AND keeps the full warm prefix
    #    byte-identical on Turn 5 (including Turn 4's report + non-plan-builder skill verbatim!).
    real_sig = b"real-model-thought-signature"

    class RoutingFallbackLlm(BaseLlm):
        requests: list = []

        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            self.requests.append(llm_request)
            idx = len(self.requests)
            if idx in (2, 4):
                yield LlmResponse(content=types.Content(role="model", parts=[
                    types.Part(text="routing thought...", thought=True),
                    types.Part(
                        function_call=types.FunctionCall(
                            id=f"fa-{idx}",
                            name="fetch_plan_audit_data",
                            args={"start_date": "2026-11-30", "end_date": "2027-02-07"},
                        ),
                        thought_signature=real_sig,
                    ),
                    types.Part(
                        function_call=types.FunctionCall(
                            id=f"ls-{idx}", name="load_skill", args={"skill_name": "plan-audit"},
                        ),
                        thought_signature=real_sig,
                    ),
                ]))
                return
            if idx == 3:
                yield LlmResponse(content=types.Content(role="model", parts=[
                    types.Part(text="### Assessment\n- **Benchmark:** Jan 24 5x1km."),
                    types.Part(function_call=types.FunctionCall(
                        id="stray-weather", name="get_weather", args={"dates": ["2026-11-30"]},
                    )),
                ]))
                return
            yield LlmResponse(content=types.Content(
                role="model", parts=[types.Part(text="### Assessment\n- **Benchmark:** Jan 24 5x1km.")]
            ))

    runner.now = datetime(2026, 11, 16, 9, 0, 0)
    llm = RoutingFallbackLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        e1 = await _turn(r, session.id, rich_audit_prompt)
        e2 = await _turn(r, session.id, "Audit my Amsterdam Half block")
        e3 = await _turn(r, session.id, "Audit my plan from Nov 30 to Feb 7 and move Friday S&C")
        e4 = await _turn(r, session.id, "Audit my plan")
        e5 = await _turn(r, session.id, "On Jan 26th, 6x1k or 3x1.6k?")
        return e1, e2, e3, e4, e5

    e1, e2, e3, e4, e5 = asyncio.run(scenario())

    # Turn 1 (fresh session): rich 57-word audit pre-dispatches -> 1 LLM call (idx 0), full prefix kept, tail preserved.
    assert _calls(e1) == [
        ("fetch_plan_audit_data", {"start_date": "2026-11-30", "end_date": "2027-02-07"}),
        ("load_skill", {"skill_name": "plan-audit"}),
    ]
    req1_report = llm.requests[0]
    assert req1_report.config.tools
    assert _tool_mode(req1_report) is None
    assert "SKILL ROUTING" in _system_text(req1_report) and "<available_skills>" in _system_text(req1_report)
    assert any("Dec 19th and Dec 26th" in (p.text or "") for c in req1_report.contents for p in c.parts or [])

    # Turn 2: fallback read-only report -> Call 1 keeps Turn 1's report data verbatim while stubbing Turn 1's
    # completed load_skill rubric; Call 2 keeps byte-identical system_instruction + tools AND drops stray tool calls!
    from running_coach.coach.report_memory import STALE_SKILL_STUB

    req2_route, req2_synth = llm.requests[1], llm.requests[2]
    assert _system_text(req1_report) == _system_text(req2_route) == _system_text(req2_synth)
    assert req1_report.config.tools == req2_route.config.tools == req2_synth.config.tools
    assert req1_report.contents[:2] == req2_route.contents[:2]
    assert req1_report.contents[2].parts[0] == req2_route.contents[2].parts[0]
    assert req2_route.contents[2].parts[1].function_response.response["instructions"] == STALE_SKILL_STUB
    assert _tool_mode(req2_synth) is None
    assert _calls(e2) == [
        ("fetch_plan_audit_data", {"start_date": "2026-11-30", "end_date": "2027-02-07"}),
        ("load_skill", {"skill_name": "plan-audit"}),
    ]  # stray get_weather dropped by drop_disabled_tool_calls

    # Turn 3: fallback report + mutation intent -> inherits Turn 2's completed real thought_signature verbatim
    # (thought text stripped, signatures untouched, completed load_skill stubbed), and Call 2 keeps stage_workout_changes!
    req3_route, req3_step2 = llm.requests[3], llm.requests[4]
    turn2_model_fc = req3_route.contents[len(req2_route.contents)]
    assert [p.thought_signature for p in turn2_model_fc.parts] == [real_sig, real_sig]
    assert all(not p.thought for p in turn2_model_fc.parts)
    turn2_tool_resp = req3_route.contents[len(req2_route.contents) + 1]
    assert turn2_tool_resp.parts[0] == req2_synth.contents[-1].parts[0]
    assert turn2_tool_resp.parts[1].function_response.response["instructions"] == STALE_SKILL_STUB
    assert req3_route.config.tools
    declared_step2 = [d.name for t in (req3_step2.config.tools or []) for d in (t.function_declarations or [])]
    assert "stage_workout_changes" in declared_step2
    assert "SKILL ROUTING" in _system_text(req3_step2)

    # Turn 4 (warm session): pre-dispatches in 1 LLM call (idx 5) while keeping the warm full-prompt prefix intact,
    # AND Turn 5 keeps Turn 4's report data verbatim while stubbing Turn 4's completed plan-audit rubric!
    assert len(llm.requests) == 7
    assert _calls(e4) == [
        ("fetch_plan_audit_data", {}),
        ("load_skill", {"skill_name": "plan-audit"}),
    ]
    req4_warm, req5_followup = llm.requests[5], llm.requests[6]
    assert _system_text(req4_warm) == _system_text(req3_step2) == _system_text(req5_followup)
    assert req4_warm.config.tools == req3_step2.config.tools == req5_followup.config.tools
    assert [p.function_response.name for p in req4_warm.contents[-1].parts] == ["fetch_plan_audit_data", "load_skill"]
    assert req4_warm.contents[:-1] == req5_followup.contents[: len(req4_warm.contents) - 1]
    assert req4_warm.contents[-1].parts[0] == req5_followup.contents[len(req4_warm.contents) - 1].parts[0]
    assert req5_followup.contents[len(req4_warm.contents) - 1].parts[1].function_response.response["instructions"] == STALE_SKILL_STUB




