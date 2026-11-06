"""Routing, profile safety guards and ADK callbacks."""

import asyncio
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
import pytest

import running_coach.agent as agent
from running_coach.callbacks import (
    TREND_PLACEHOLDER,
    TREND_TABLES_STATE_KEY,
    apply_thinking_policy,
    no_workout_reply,
    splice_tables,
)
import running_coach.steps as steps
from running_coach.utils import AUTH_EMAIL_STATE_KEY
from running_coach.utils.workouts import format_no_workout

EMAIL = "cyrille@cyvisser.altostrat.com"
PROFILE = {"firstname": "Cyrille", "lastname": "Visser", "email": EMAIL,
           "training_goal": "Sub-3:30 Marathon", "timeline": "2099-11-01", "location": "Utrecht"}


class FakeContext:
    def __init__(self, state=None, user_id=None):
        self.state: dict = dict(state or {})
        self.session = SimpleNamespace(user_id=user_id)
        self.route = None


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv("DEV_RUNNER_EMAIL", raising=False)
    store = {"cyrille_visser": dict(PROFILE)}
    connected = {"cyrille_visser"}

    async def fake_find_by_email(email):
        for rid, doc in store.items():
            if (doc.get("email") or "").lower() == email.lower():
                return rid, dict(doc)
        return None

    async def fake_has_credential(runner_id):
        return runner_id in connected

    async def fake_coords(user_id, profile):
        return None

    monkeypatch.setattr(steps, "find_user_profile_by_email", fake_find_by_email)
    monkeypatch.setattr(agent, "has_tp_credential", fake_has_credential)
    monkeypatch.setattr(steps, "_ensure_cached_coordinates", fake_coords)
    return SimpleNamespace(store=store, connected=connected)


def _route(ctx):
    asyncio.run(agent.profile_router._func(ctx))
    return ctx.route


def test_profile_router_outcomes(env):
    assert _route(FakeContext(user_id=EMAIL)) == agent.ROUTE_COACHING
    assert _route(FakeContext(user_id="unknown@cyvisser.altostrat.com")) == agent.ROUTE_NOT_LINKED

    env.store["jane_doe"] = {"firstname": "Jane", "lastname": "Doe", "email": "jane@x.com", "onboarding_pending": True}
    env.connected.add("jane_doe")
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: "jane@x.com"}, user_id="web_jane@x.com")) == agent.ROUTE_ONBOARDING

    env.connected.remove("cyrille_visser")
    assert _route(FakeContext(user_id=EMAIL)) == agent.ROUTE_TP_NOT_CONNECTED


def test_create_profile_guards_prevent_empty_name_and_email_takeover(monkeypatch):
    saved = []

    async def fake_get(user_id):
        return dict(PROFILE)

    async def fake_save(user_id, profile):
        saved.append(user_id)

    monkeypatch.setattr(steps, "get_user_profile", fake_get)
    monkeypatch.setattr(steps, "save_user_profile", fake_save)

    assert asyncio.run(steps.create_profile_step(FakeContext({"temp_onboarding_data": {}, "onboarding_answers": {}}))) == steps.PROFILE_NO_NAME
    conflict = FakeContext({
        "temp_onboarding_data": {"firstname": "Cyrille", "lastname": "Visser", "email": "other@x.com"},
        "onboarding_answers": {"goal_type": "single", "training_goal": "Sub-20 5K", "timeline": "2027-06-01"},
    })
    assert asyncio.run(steps.create_profile_step(conflict)) == steps.PROFILE_EMAIL_CONFLICT
    assert saved == []


def test_thinking_policy_and_table_splicing():
    req = LlmRequest(contents=[types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name="create_workout", response={"result": "ok"}))
    ])], config=types.GenerateContentConfig())
    apply_thinking_policy(FakeContext(), req)
    assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW

    ctx = FakeContext({TREND_TABLES_STATE_KEY: "| Marker | Latest |\n|---|---|\n| CTL | 62.5 |\n"})
    resp = LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"## Overview\n{TREND_PLACEHOLDER}\n## Progress")]))
    spliced = splice_tables(ctx, resp).content.parts[0].text
    assert TREND_PLACEHOLDER not in spliced and "| CTL | 62.5 |" in spliced


def test_no_workout_reply_short_circuits_model():
    msg = format_no_workout(
        "2026-11-06",
        [{"title": "Easy Run", "sport": "Run", "date": "2026-11-06"}],
        [{"title": "Tempo Run", "sport": "Run", "date": "2026-11-04", "type": "completed"}],
    )
    assert "No completed workout on 2026-11-06" in msg
    assert "Planned that day: Easy Run." in msg
    assert "Tempo Run on 2026-11-04" in msg

    req = LlmRequest(contents=[types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name="analyze_workout", response={"result": msg}))
    ])])
    res = no_workout_reply(FakeContext(), req)
    assert res is not None and res.content.parts[0].text == msg

    # Normal workout analysis passes through to the model.
    ok_req = LlmRequest(contents=[types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name="analyze_workout", response={"result": "### Workout Analysis [1]"}))
    ])])
    assert no_workout_reply(FakeContext(), ok_req) is None


def test_goal_plan_lens_only_for_goal_plans(monkeypatch):
    ctx = SimpleNamespace(state={"user_profile": dict(PROFILE)})
    monkeypatch.setattr(agent, "format_goal_plan", lambda profile, today: "")
    assert "GOAL PLAN LENS" not in agent.build_coach_instruction(ctx)
    monkeypatch.setattr(agent, "format_goal_plan", lambda profile, today: "GOAL PLAN (north star with sub goals):")
    instruction = agent.build_coach_instruction(ctx)
    assert "GOAL PLAN LENS" in instruction and "CRITICAL COACHING CONTRACT" in instruction

