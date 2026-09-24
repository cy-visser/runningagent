"""Routing tests for profile_router: known runners must never be sent to onboarding."""

import asyncio
import json

import pytest

import running_coach.agent as agent
import running_coach.steps as steps
import running_coach.services.tp_mcp as tp_mcp
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

    def test_profile_already_in_session_skips_everything(self, env):
        ctx = FakeContext({"user_profile": dict(PROFILE)})
        assert route(ctx) == agent.ROUTE_COACHING
        assert env.calls == {"tp": 0, "firestore": []}

    def test_first_session_identifies_via_tp_and_remembers_runner(self, env):
        ctx = FakeContext()
        assert route(ctx) == agent.ROUTE_COACHING
        assert env.calls["tp"] == 1
        assert ctx.state[RUNNER_ID_STATE_KEY] == "cyrille_visser"

    def test_stale_runner_id_falls_back_to_tp(self, env):
        ctx = FakeContext({RUNNER_ID_STATE_KEY: "ghost_runner"})
        assert route(ctx) == agent.ROUTE_COACHING
        assert env.calls["tp"] == 1
        assert ctx.state[RUNNER_ID_STATE_KEY] == "cyrille_visser"

    def test_tp_failure_does_not_onboard(self, env, monkeypatch):
        async def boom(name):
            raise RuntimeError("unhandled errors in a TaskGroup")

        monkeypatch.setattr(agent, "get_tp_tool", boom)
        assert route(FakeContext()) == agent.ROUTE_UNAVAILABLE

    @pytest.mark.parametrize("response", [None, {}, {"content": [{"text": json.dumps({"name": ""})}]}])
    def test_unparseable_tp_profile_does_not_onboard(self, env, response):
        env.tp_response = response
        assert route(FakeContext()) == agent.ROUTE_UNAVAILABLE

    def test_firestore_error_on_known_runner_does_not_onboard(self, env):
        env.firestore_error = True
        ctx = FakeContext({RUNNER_ID_STATE_KEY: "cyrille_visser"})
        assert route(ctx) == agent.ROUTE_UNAVAILABLE
        assert env.calls["tp"] == 0

    def test_firestore_error_on_first_session_does_not_onboard(self, env):
        env.firestore_error = True
        assert route(FakeContext()) == agent.ROUTE_UNAVAILABLE

    def test_genuinely_new_runner_is_onboarded(self, env):
        env.store.clear()
        ctx = FakeContext()
        assert route(ctx) == agent.ROUTE_ONBOARDING
        assert ctx.state["temp_onboarding_data"]["firstname"] == "Cyrille"

    def test_reonboard_request_is_honoured(self, env):
        ctx = FakeContext({RUNNER_ID_STATE_KEY: "cyrille_visser", "reonboard_requested": True})
        assert route(ctx) == agent.ROUTE_ONBOARDING


class TestCreateProfileGuard:
    def test_refuses_to_save_without_name(self, monkeypatch):
        saved = []

        async def fake_save(user_id, profile):
            saved.append(user_id)

        monkeypatch.setattr(steps, "save_user_profile", fake_save)
        ctx = FakeContext({"temp_onboarding_data": {}, "onboarding_answers": {}})
        assert asyncio.run(steps.create_profile_step(ctx)) is False
        assert saved == []


class TestTpMcpTimeout:
    def test_toolset_uses_explicit_connect_timeout(self, monkeypatch):
        captured = {}

        class FakeToolset:
            def __init__(self, connection_params):
                captured["params"] = connection_params

            async def get_tools(self):
                return [type("T", (), {"name": "tp_get_profile"})()]

        monkeypatch.setattr(tp_mcp, "_tp_toolset", None)
        monkeypatch.setattr(tp_mcp, "McpToolset", FakeToolset)
        monkeypatch.setattr(tp_mcp, "inject_production_secrets", lambda: None)

        asyncio.run(tp_mcp.get_tp_tool("tp_get_profile"))
        params = captured["params"]
        assert isinstance(params, tp_mcp.StdioConnectionParams)
        assert params.timeout == tp_mcp.TP_MCP_CONNECT_TIMEOUT_S >= 30
