"""Routing, profile safety guards and ADK callbacks."""

import asyncio
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
import pytest

import running_coach.agent as agent
from running_coach.callbacks import (
    ELIDED_SKILL,
    ELIDED_TOOL,
    TREND_PLACEHOLDER,
    TREND_TABLES_STATE_KEY,
    apply_thinking_policy,
    before_model,
    prune_stale_history,
    splice_tables,
)
import running_coach.steps as steps
from running_coach.utils import AUTH_EMAIL_STATE_KEY

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


def _fr(name, payload):
    return types.Part(function_response=types.FunctionResponse(id=f"id-{name}", name=name, response={"result": payload}))


def _history():
    """Earlier check-in turn + current schedule turn, as ADK sends it to the model."""
    return [
        types.Content(role="user", parts=[types.Part(text="Checking in")]),
        types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name="load_skill", args={"skill_name": "check-in-report"})),
            types.Part(function_call=types.FunctionCall(name="fetch_checkin_data", args={})),
        ]),
        types.Content(role="user", parts=[_fr("load_skill", "# Check-In Report Skill ..."),
                                          _fr("fetch_checkin_data", "### Weekly Check-In ...")]),
        types.Content(role="model", parts=[types.Part(text="### Check-In Overview ...")]),
        types.Content(role="user", parts=[types.Part(text="Review my plan")]),
        types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name="fetch_schedule_audit_data", args={}))]),
        types.Content(role="user", parts=[_fr("fetch_schedule_audit_data", "### Training Schedule Audit ...")]),
    ]


def test_prune_stale_history_stubs_only_earlier_turns_without_mutating_session():
    session_contents = _history()
    snapshot = [c.model_copy(deep=True) for c in session_contents]
    req = LlmRequest(contents=list(session_contents), config=types.GenerateContentConfig())

    assert prune_stale_history(req) == 2
    old = req.contents[2].parts
    assert old[0].function_response.name == "load_skill"
    assert old[0].function_response.response == {"result": ELIDED_SKILL}
    assert old[0].function_response.id == "id-load_skill"
    assert old[1].function_response.response == {"result": ELIDED_TOOL}
    # Calls, replies, user messages and the current turn's tool output are untouched.
    assert req.contents[1] is session_contents[1] and req.contents[3] is session_contents[3]
    assert req.contents[6].parts[0].function_response.response == {"result": "### Training Schedule Audit ..."}
    # Session-owned objects are never mutated.
    assert session_contents == snapshot


def test_prune_keeps_current_turn_and_combined_callback_applies_thinking_policy():
    contents = _history()[:3]  # still inside the check-in turn
    req = LlmRequest(contents=contents, config=types.GenerateContentConfig())
    assert prune_stale_history(req) == 0

    req = LlmRequest(contents=_history() + [
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="create_workout", args={}))]),
        types.Content(role="user", parts=[_fr("create_workout", "ok")]),
    ], config=types.GenerateContentConfig())
    before_model(FakeContext(), req)
    assert req.contents[2].parts[1].function_response.response == {"result": ELIDED_TOOL}
    assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW


def test_goal_plan_lens_only_for_goal_plans(monkeypatch):
    ctx = SimpleNamespace(state={"user_profile": dict(PROFILE)})
    monkeypatch.setattr(agent, "format_goal_plan", lambda profile, today: "")
    assert "GOAL PLAN LENS" not in agent.build_coach_instruction(ctx)
    monkeypatch.setattr(agent, "format_goal_plan", lambda profile, today: "GOAL PLAN (north star with sub goals):")
    instruction = agent.build_coach_instruction(ctx)
    assert "GOAL PLAN LENS" in instruction and "CRITICAL COACHING CONTRACT" in instruction

