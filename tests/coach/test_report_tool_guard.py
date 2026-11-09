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
from running_coach.features.check_in_report.helpers.web_report import CHECKIN_REPORT_STATE_KEY
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL


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
