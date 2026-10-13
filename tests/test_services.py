"""Tests for service-layer caching and secret access."""

import asyncio
import os

import pytest

import running_coach.services.secrets as secrets
import running_coach.services.tp_mcp as tp_mcp


class TestTpToolCache:
    def test_two_lookups_fetch_tools_once(self, monkeypatch):
        calls = {"get_tools": 0}

        class FakeToolset:
            async def get_tools(self):
                calls["get_tools"] += 1
                return [type("T", (), {"name": n})() for n in ("tp_get_profile", "tp_get_workouts")]

        monkeypatch.setattr(tp_mcp, "_tp_toolset", FakeToolset())
        monkeypatch.setattr(tp_mcp, "_tp_tools_by_name", {})

        async def lookups():
            await tp_mcp.get_tp_tool("tp_get_profile")
            await tp_mcp.get_tp_tool("tp_get_workouts")

        asyncio.run(lookups())
        assert calls["get_tools"] == 1


class TestGetTpCookie:
    def test_reads_secret_manager_and_ignores_env_cookie(self, monkeypatch):
        from google.cloud import secretmanager

        monkeypatch.setenv("TP_AUTH_COOKIE", "local-ignored")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
        requested = {}

        class FakeClient:
            def access_secret_version(self, request):
                requested.update(request)
                payload = type("P", (), {"data": b" secret-cookie \n"})()
                return type("R", (), {"payload": payload})()

        monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", FakeClient)
        assert secrets.get_tp_cookie() == "secret-cookie"
        assert os.environ["TP_AUTH_COOKIE"] == "local-ignored"
        assert requested["name"].startswith("projects/")
        assert requested["name"].endswith("/versions/latest")
