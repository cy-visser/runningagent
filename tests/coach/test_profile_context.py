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
from running_coach.coach.coaching.instruction import (
    PROFILE_CONTEXT_END,
    PROFILE_CONTEXT_START,
    build_profile_context,
    format_profile_summary,
)
from running_coach.coach.coaching.profile_context import ensure_profile_context, inject_profile_context
from running_coach.coach.coaching.quick_actions import QUICK_ACTION_STATE_KEY
from running_coach.coach.profile_lookup import PROFILE_UNAVAILABLE_MESSAGE
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL, PLAN_PROFILE, SINGLE_PROFILE, FakeContext


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
        assert si.count("RUNNER PROFILE:") == 1 and si.count("GOAL PLAN LENS:") == 1
        assert "Name: Cyrille Visser (Age: 38)" in si and "Past left Achilles tendinopathy" in si
        assert "Current Block: Race: Schoorl 10K, Block start: 2026-11-16" in si
        assert "None" not in si.split(PROFILE_CONTEXT_START)[1]                           # no empty fields
        # The profile is per-call system context only: it never piles up in conversation history.
        assert "RUNNER PROFILE" not in _contents_text(req)


def test_profile_summary_is_complete_and_injection_is_idempotent(runner):
    summary = format_profile_summary({**SINGLE_PROFILE, "taper_weeks": 2, "injuries": "", "shoe_rotation": None})
    assert "Current Block: Block start: 2026-08-01, Taper override: 2 weeks" in summary
    assert "Injuries" not in summary and "Shoe Rotation" not in summary and "None" not in summary

    req = LlmRequest(config=types.GenerateContentConfig(system_instruction="Coach rules."))
    inject_profile_context(req, build_profile_context(dict(PLAN_PROFILE)))
    inject_profile_context(req, build_profile_context(dict(SINGLE_PROFILE)))           # e.g. callback runs twice
    si = req.config.system_instruction
    assert si.startswith("Coach rules.\n\n") and si.count(PROFILE_CONTEXT_START) == 1
    assert "Sub-3:30 Marathon" in si and "Sub-3:15 Marathon" not in si                 # replaced, not appended


def test_missing_profile_is_reloaded_or_the_call_is_refused(runner):
    # Profile dropped from state mid-session -> reloaded from Firestore and injected.
    ctx = FakeContext(state={AUTH_EMAIL_STATE_KEY: EMAIL})
    req = LlmRequest(config=types.GenerateContentConfig(system_instruction="Coach rules."))
    assert asyncio.run(ensure_profile_context(ctx, req)) is None
    assert ctx.state["user_profile"]["email"] == EMAIL
    assert req.config.system_instruction.count("RUNNER PROFILE:") == 1

    # Unknown caller -> no coaching without a profile: the model call is short-circuited.
    ctx = FakeContext(state={AUTH_EMAIL_STATE_KEY: "stranger@x.com"})
    req = LlmRequest(config=types.GenerateContentConfig(system_instruction="Coach rules."))
    resp = asyncio.run(ensure_profile_context(ctx, req))
    assert resp.content.parts[0].text == PROFILE_UNAVAILABLE_MESSAGE
    assert "RUNNER PROFILE" not in req.config.system_instruction
