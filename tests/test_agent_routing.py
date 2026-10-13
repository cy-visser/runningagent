"""Routing tests for profile_router: known runners must never be sent to onboarding."""

import asyncio
import json

import pytest

import running_coach.agent as agent
import running_coach.steps as steps
from running_coach.utils import RUNNER_ID_STATE_KEY

PROFILE = {"firstname": "Cyrille", "lastname": "Visser", "timeline": "2099-11-01", "location": "Utrecht"}
TP_PROFILE = {"content": [{"text": json.dumps({"name": "Cyrille Visser", "city": "Utrecht"})}]}


class FakeContext:
    def __init__(self, state=None):
        self.state: dict = dict(state or {})
        self.route = None


@pytest.fixture
def env(monkeypatch):
    calls = {"tp": 0, "firestore": []}
    store = {"cyrille_visser": dict(PROFILE)}

    async def fake_get_tp_tool(name):
        calls["tp"] += 1
        return object()

    async def fake_run(ctx, tool, **kwargs):
        return env.tp_response

    async def fake_get_user_profile(user_id):
        calls["firestore"].append(user_id)
        if env.firestore_error:
            raise RuntimeError("firestore down")
        return dict(store[user_id]) if user_id in store else None

    async def fake_coords(user_id, profile):
        return None

    monkeypatch.setattr(agent, "get_tp_tool", fake_get_tp_tool)
    monkeypatch.setattr(agent, "run_node_with_retry", fake_run)
    monkeypatch.setattr(steps, "get_user_profile", fake_get_user_profile)
    monkeypatch.setattr(steps, "_ensure_cached_coordinates", fake_coords)

    class Env:
        pass

    env = Env()
    env.calls, env.store = calls, store
    env.tp_response, env.firestore_error = TP_PROFILE, False
    return env


def route(ctx):
    asyncio.run(agent.profile_router._func(ctx))
    return ctx.route


class TestProfileRouter:
    def test_known_runner_skips_trainingpeaks(self, env):
        ctx = FakeContext({RUNNER_ID_STATE_KEY: "cyrille_visser"})
        assert route(ctx) == agent.ROUTE_COACHING
        assert env.calls["tp"] == 0
        assert ctx.state["user_profile"]["firstname"] == "Cyrille"

    def test_first_session_identifies_via_tp_and_remembers_runner(self, env):
        ctx = FakeContext()
        assert route(ctx) == agent.ROUTE_COACHING
        assert env.calls["tp"] == 1
        assert ctx.state[RUNNER_ID_STATE_KEY] == "cyrille_visser"

    def test_tp_failure_does_not_onboard(self, env, monkeypatch):
        async def boom(name):
            raise RuntimeError("unhandled errors in a TaskGroup")

        monkeypatch.setattr(agent, "get_tp_tool", boom)
        assert route(FakeContext()) == agent.ROUTE_UNAVAILABLE

    def test_genuinely_new_runner_is_onboarded(self, env):
        env.store.clear()
        ctx = FakeContext()
        assert route(ctx) == agent.ROUTE_ONBOARDING
        assert ctx.state["temp_onboarding_data"]["firstname"] == "Cyrille"


class TestCreateProfileGuard:
    def test_refuses_to_save_without_name(self, monkeypatch):
        saved = []

        async def fake_save(user_id, profile):
            saved.append(user_id)

        monkeypatch.setattr(steps, "save_user_profile", fake_save)
        ctx = FakeContext({"temp_onboarding_data": {}, "onboarding_answers": {}})
        assert asyncio.run(steps.create_profile_step(ctx)) is False
        assert saved == []
