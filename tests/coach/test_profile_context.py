"""Behavioural test: the runner profile is in every coach model call exactly once, and never in history."""

import asyncio
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import root_agent
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.coach.coaching.instruction import PROFILE_CONTEXT_END, PROFILE_CONTEXT_START
from running_coach.coach.coaching.quick_actions import QUICK_ACTION_STATE_KEY
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
    return si if isinstance(si, str) else ""


def _contents_text(req: LlmRequest) -> str:
    return "".join(p.text or "" for c in req.contents or [] for p in c.parts or [])


async def _turn(runner, session_id: str, text: str, action: dict | None = None) -> list:
    state_delta = {AUTH_EMAIL_STATE_KEY: EMAIL}
    if action:
        state_delta[QUICK_ACTION_STATE_KEY] = action
    return [
        ev async for ev in runner.run_async(
            user_id="web_runner", session_id=session_id, state_delta=state_delta,
            new_message=types.Content(role="user", parts=[types.Part(text=text)]),
        )
    ]


def test_profile_is_in_every_model_call_exactly_once_and_never_in_history(runner, monkeypatch):
    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(agent=root_agent, app_name="running_coach")
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        await _turn(r, session.id, "How was my week?")                                   # typed chat
        await _turn(r, session.id, "Trends", {"skill": "trend-analysis", "args": {"weeks": 6}})  # after tools
        await _turn(r, session.id, "And tomorrow?")                                       # later chat

    asyncio.run(scenario())

    assert len(llm.requests) == 3
    for req in llm.requests:
        si = _system_text(req)
        assert si.count(PROFILE_CONTEXT_START) == 1 and si.count(PROFILE_CONTEXT_END) == 1
        assert si.count("RUNNER PROFILE:") == 1 and si.count("GOAL REASONING") == 1
        assert "Name: Cyrille Visser (Age: 38)" in si and "Past left Achilles tendinopathy" in si
        assert "Current Block: Race: Schoorl 10K, Block start: 2026-11-16" in si
        assert "None" not in si.split(PROFILE_CONTEXT_START)[1]                           # no empty fields
        # The profile is per-call system context only: it never piles up in conversation history.
        assert "RUNNER PROFILE" not in _contents_text(req)
