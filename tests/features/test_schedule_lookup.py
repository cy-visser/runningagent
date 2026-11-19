"""Behavioural tests for `get_schedule` (lightweight calendar peek), synthesis guard, and typed pre-dispatch."""

import asyncio
from datetime import date, datetime
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import app
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.coach.coaching.quick_actions import infer_typed_quick_action
from running_coach.features.plan_audit.helpers.web_report import AUDIT_REPORT_STATE_KEY
from running_coach.features.schedule_lookup.get_schedule_tool import MAX_SCHEDULE_DAYS, get_schedule
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL


def test_get_schedule_defaults_to_current_iso_week_includes_dup_ids_and_opens_no_report_card(runner):
    # TODAY in fakes is Tue 2026-10-27 -> current ISO week is 2026-10-26..2026-11-01.
    # Add two planned runs on Sunday 2026-11-01 so duplicate-sport [workout_id] emission is exercised.
    runner.workouts.extend([
        {
            "id": "w_am",
            "date": "2026-11-01",
            "start_time": "2026-11-01T08:00:00",
            "title": "Morning Shakeout",
            "sport": "Run",
            "type": "planned",
            "distance_planned_km": 6.0,
            "duration_planned": 0.55,
            "tss_planned": 36.0,
        },
        {
            "id": "w_pm",
            "date": "2026-11-01",
            "start_time": "2026-11-01T17:00:00",
            "title": "Evening Easy",
            "sport": "Run",
            "type": "planned",
            "distance_planned_km": 5.0,
            "duration_planned": 0.45,
            "tss_planned": 30.0,
        },
    ])
    ctx = runner.ctx()
    runner.tp_calls.clear()

    out = asyncio.run(get_schedule(ctx))
    assert out.startswith("### Schedule (2026-10-26 – 2026-11-01)")
    assert "[w_am]" in out and "[w_pm]" in out
    assert "Work trip to Berlin | Hotel gym available" in out
    assert AUDIT_REPORT_STATE_KEY not in ctx.state
    # Only workouts + notes fetched (no tp_get_fitness, no prior-week fetch):
    assert sorted(name for name, _ in runner.tp_calls) == ["tp_get_workouts", "tp_list_notes"]
    for _, kw in runner.tp_calls:
        assert kw["start_date"] == "2026-10-26" and kw["end_date"] == "2026-11-01"


def test_get_schedule_clamps_long_windows_and_surfaces_tp_outage_cleanly(runner):
    ctx = runner.ctx()
    clamped = asyncio.run(get_schedule(ctx, start_date="2026-11-02", end_date="2027-03-01"))
    assert f"Capped to {MAX_SCHEDULE_DAYS} days ending 2026-12-13" in clamped

    runner.failing_tools.add("tp_get_workouts")
    err = asyncio.run(get_schedule(ctx, start_date="2026-11-02", end_date="2026-11-08"))
    assert err.startswith("Error: Could not load TrainingPeaks workouts")
    assert "do NOT tell the runner the calendar is empty" in err


def test_typed_schedule_peek_pre_dispatches_in_one_call_and_conversational_peek_guards_step2(runner, monkeypatch):
    today = date(2026, 11, 18)  # Wednesday -> Monday is 2026-11-16
    assert infer_typed_quick_action("Pull up this week", today) == {"skill": "schedule-lookup", "args": {}}
    assert infer_typed_quick_action("What's on my schedule next week?", today) == {
        "skill": "schedule-lookup",
        "args": {"start_date": "2026-11-23", "end_date": "2026-11-29"},
    }
    assert infer_typed_quick_action("Pull up the week of Dec 21", today) == {
        "skill": "schedule-lookup",
        "args": {"start_date": "2026-12-21", "end_date": "2026-12-27"},
    }
    assert infer_typed_quick_action("Show my schedule from Dec 14th to Dec 27th", today) == {
        "skill": "schedule-lookup",
        "args": {"start_date": "2026-12-14", "end_date": "2026-12-27"},
    }
    # Conversational / multi-clause / mutation prompts stay on normal LLM routing:
    for non_match in (
        "Pull up this week and move Friday's tempo to Saturday",
        "I will be on a cruise between Dec 20th and Dec 26th. Can you pull up the week and lets see how we can organize the runs",
    ):
        assert infer_typed_quick_action(non_match, today) is None

    class ScheduleTestLlm(BaseLlm):
        requests: list = []

        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            self.requests.append(llm_request)
            idx = len(self.requests)
            if idx == 2:
                # Conversational cruise prompt Call 1 -> routes to get_schedule (no load_skill)
                yield LlmResponse(content=types.Content(role="model", parts=[
                    types.Part(function_call=types.FunctionCall(
                        id="gs-1",
                        name="get_schedule",
                        args={"start_date": "2026-10-26", "end_date": "2026-11-08"},
                    )),
                ]))
                return
            if idx == 3:
                # Conversational cruise prompt Call 2 -> synthesis guard drops stray tool call while keeping prefix!
                yield LlmResponse(content=types.Content(role="model", parts=[
                    types.Part(text="Swap Sat Dec 19 easy and Sun Dec 20 long run."),
                    types.Part(function_call=types.FunctionCall(
                        id="stray", name="get_weather", args={"dates": ["2026-10-26"]},
                    )),
                ]))
                return
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Here is your week.")]))

    runner.now = datetime(2026, 10, 27, 9, 0, 0)
    llm = ScheduleTestLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")

        async def turn(text: str):
            evs = []
            async for ev in r.run_async(
                user_id="web_runner",
                session_id=session.id,
                state_delta={AUTH_EMAIL_STATE_KEY: EMAIL},
                new_message=types.Content(role="user", parts=[types.Part(text=text)]),
            ):
                evs.append(ev)
            return evs

        e1 = await turn("Pull up this week")
        e2 = await turn(
            "I will be on a cruise between Oct 26th and Nov 7th. Can you pull up the week and lets see how we can organize the runs"
        )
        e3 = await turn("Pull up next week")
        return e1, e2, e3

    e1, e2, e3 = asyncio.run(scenario())
    # Turn 1 (fresh standalone peek): 1 LLM call, no load_skill, no audit report card, AND keeps full
    # (system_instruction + tools) prefix intact to warm the implicit prefix cache for Turn 2+!
    calls_1 = [p.function_call.name for e in e1 if e.content for p in e.content.parts or [] if p.function_call]
    assert calls_1 == ["get_schedule"]
    assert llm.requests[0].config.tools
    assert llm.requests[0].config.system_instruction == llm.requests[1].config.system_instruction
    assert llm.requests[0].config.tools == llm.requests[1].config.tools

    # Turn 2 (conversational 2-call peek): Call 2 keeps byte-identical system_instruction & tools as Call 1, drops stray get_weather!
    calls_2 = [p.function_call.name for e in e2 if e.content for p in e.content.parts or [] if p.function_call]
    assert calls_2 == ["get_schedule"]
    assert llm.requests[1].config.system_instruction == llm.requests[2].config.system_instruction
    assert llm.requests[1].config.tools == llm.requests[2].config.tools

    # Turn 3 (warm standalone peek): 1 LLM call AND keeps warm session prefix cache intact, while Turn 1's older get_schedule is stubbed!
    assert len(llm.requests) == 4
    assert llm.requests[3].config.system_instruction == llm.requests[2].config.system_instruction
    assert llm.requests[3].config.tools == llm.requests[2].config.tools
    earlier_sched_resps = [
        p.function_response.response
        for c in llm.requests[3].contents[:-1]
        for p in c.parts or []
        if p.function_response and p.function_response.name == "get_schedule"
    ]
    assert any("superseded: the latest Schedule output is further below" in str(r) for r in earlier_sched_resps)
