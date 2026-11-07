"""Report data tools render a report card only as the turn's report, never as a data lookup."""

import asyncio
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import app
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.coach.coaching.report_tool_guard import is_turn_report
from running_coach.features.check_in_report.helpers.web_report import CHECKIN_REPORT_STATE_KEY
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL


def _load(skill: str) -> dict:
    return {"name": "load_skill", "skill": skill}


def _tool(name: str) -> dict:
    return {"name": name}


def test_report_tool_is_allowed_as_the_turns_report():
    # Routing step: load_skill + data tool in parallel.
    assert is_turn_report("fetch_checkin_data", [[_load("check-in-report"), _tool("fetch_checkin_data")]])
    # Skill already in the conversation: data tool alone in the first step.
    assert is_turn_report("fetch_checkin_data", [[_tool("fetch_checkin_data")]])
    # Web quick action: dispatched before the model, nothing recorded.
    assert is_turn_report("fetch_trend_data", [])
    # load_skill first, data tool in the next step.
    assert is_turn_report("fetch_schedule_audit_data", [[_load("schedule-audit")], [_tool("fetch_schedule_audit_data")]])


def test_report_tool_is_blocked_as_a_lookup():
    # The reported trace: workout-creator loaded, then fetch_checkin_data to find workout ids.
    assert not is_turn_report("fetch_checkin_data", [[_load("workout-creator")], [_tool("fetch_checkin_data")]])
    # Another skill loaded in the same step.
    assert not is_turn_report("fetch_checkin_data", [[_load("workout-creator"), _tool("fetch_checkin_data")]])
    # Other work earlier in the turn.
    assert not is_turn_report("fetch_trend_data", [[_tool("get_weather")], [_tool("fetch_trend_data")]])
    assert not is_turn_report(
        "fetch_schedule_audit_data", [[_tool("stage_workout_changes")], [_tool("fetch_schedule_audit_data")]]
    )
    # Another report's skill.
    assert not is_turn_report("fetch_checkin_data", [[_load("schedule-audit")], [_tool("fetch_checkin_data")]])


class ScriptedLlm(BaseLlm):
    """Fake Gemini: answers each model step of the turn from a script of part lists."""

    script: list = []
    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        step = self.script[len(self.requests) - 1] if len(self.requests) <= len(self.script) else [
            types.Part(text="Coach reply")]
        yield LlmResponse(content=types.Content(role="model", parts=step))


def _call(name: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args=args))


def _run_turn(monkeypatch, script: list):
    llm = ScriptedLlm(model="fake")
    llm.script, llm.requests = script, []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        events = []
        async for ev in r.run_async(
            user_id="web_runner", session_id=session.id, state_delta={AUTH_EMAIL_STATE_KEY: EMAIL},
            new_message=types.Content(role="user", parts=[types.Part(text="So what should I do in the last week of Nov?")]),
        ):
            events.append(ev)
        s = await r.session_service.get_session(app_name="running_coach", user_id="web_runner", session_id=session.id)
        return events, s

    return asyncio.run(scenario())


def _responses(events: list, name: str) -> list:
    return [p.function_response.response for e in events if e.content for p in e.content.parts or []
            if p.function_response and p.function_response.name == name]


def _report_deltas(events: list) -> list:
    return [e for e in events if CHECKIN_REPORT_STATE_KEY in (e.actions.state_delta or {})]


def test_follow_up_lookup_opens_no_checkin_report(runner, monkeypatch):
    events, s = _run_turn(monkeypatch, [
        [_call("load_skill", skill_name="workout-creator")],
        [_call("fetch_checkin_data", start_date="2026-11-23", end_date="2026-11-29")],
    ])
    (resp,) = _responses(events, "fetch_checkin_data")
    assert "was not run" in resp["result"]
    assert not _report_deltas(events)
    assert s.state.get(CHECKIN_REPORT_STATE_KEY) is None
    assert not any(name == "tp_get_fitness" for name, _ in runner.tp_calls)  # tool body never ran


def test_requested_checkin_still_opens_the_report(runner, monkeypatch):
    events, s = _run_turn(monkeypatch, [
        [_call("load_skill", skill_name="check-in-report"), _call("fetch_checkin_data")],
    ])
    (resp,) = _responses(events, "fetch_checkin_data")
    assert "was not run" not in str(resp)
    assert _report_deltas(events)
    assert isinstance(s.state.get(CHECKIN_REPORT_STATE_KEY), dict)
