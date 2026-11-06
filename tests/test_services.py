"""Tests for per-cookie MCP toolset caching and KMS per-runner credential resolution."""

import asyncio

import pytest

import running_coach.services.tp_credentials as tp_credentials
import running_coach.services.tp_mcp as tp_mcp
from running_coach.services.tp_credentials import TrainingPeaksNotConnected


class TestTpToolCache:
    def test_per_cookie_toolset_fetches_tools_once(self, monkeypatch):
        calls = {"built": [], "get_tools": 0}

        class FakeToolset:
            def __init__(self, cookie):
                self.cookie = cookie

            async def get_tools(self):
                calls["get_tools"] += 1
                return [type("T", (), {"name": n})() for n in ("tp_get_profile", "tp_get_workouts")]

        def fake_build(cookie):
            calls["built"].append(cookie)
            return FakeToolset(cookie)

        tp_mcp.reset_tp_tool_cache()
        monkeypatch.setattr(tp_mcp, "_build_toolset", fake_build)

        async def lookups():
            await tp_mcp.get_tp_tool("tp_get_profile", "cookie-a")
            await tp_mcp.get_tp_tool("tp_get_workouts", "cookie-a")
            await tp_mcp.get_tp_tool("tp_get_workouts", "cookie-b")

        asyncio.run(lookups())
        assert calls["built"] == ["cookie-a", "cookie-b"]
        assert calls["get_tools"] == 2
        tp_mcp.reset_tp_tool_cache()


class TestResolveTpCookie:
    def test_prefers_runner_cookie_then_dev_fallback_else_raises(self, monkeypatch):
        tp_credentials.clear_tp_credential_cache()
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
        monkeypatch.delenv("DEV_RUNNER_EMAIL", raising=False)

        docs = {
            "cyrille_visser": {"cookie_ciphertext": b"enc-cyrille"},
        }

        async def fake_read(path, doc_id):
            runner_id = path.split("/")[1]
            return docs.get(runner_id)

        async def fake_by_email(email):
            if email == "cyrille@cyvisser.altostrat.com":
                return ("cyrille_visser", {"firstname": "Cyrille", "lastname": "Visser"})
            return None

        class FakeKms:
            def decrypt(self, request):
                assert request["additional_authenticated_data"] == b"users/cyrille_visser"
                return type("R", (), {"plaintext": b" decrypted-cookie \n"})()

        monkeypatch.setattr(tp_credentials, "read_document", fake_read)
        monkeypatch.setattr(tp_credentials, "find_user_profile_by_email", fake_by_email)
        monkeypatch.setattr(tp_credentials, "_get_kms_client", lambda: FakeKms())

        own = asyncio.run(
            tp_credentials.resolve_tp_cookie(
                {"user_profile": {"firstname": "Cyrille", "lastname": "Visser"}}
            )
        )
        assert own == "decrypted-cookie"

        # Synthetic eval profile without its own credential raises when DEV_RUNNER_EMAIL is unset.
        synth_state = {"user_profile": {"firstname": "Alex", "lastname": "Runner"}}
        with pytest.raises(TrainingPeaksNotConnected):
            asyncio.run(tp_credentials.resolve_tp_cookie(synth_state))

        # Local DEV_RUNNER_EMAIL supplies the credential for synthetic eval profiles.
        monkeypatch.setenv("DEV_RUNNER_EMAIL", "cyrille@cyvisser.altostrat.com")
        fallback = asyncio.run(tp_credentials.resolve_tp_cookie(synth_state))
        assert fallback == "decrypted-cookie"
        tp_credentials.clear_tp_credential_cache()


def test_create_session_always_creates_new_session(monkeypatch):
    from google.adk.integrations.firestore.firestore_session_service import FirestoreSessionService
    from google.adk.sessions.session import Session
    from running_coach.services.session_service import CoachFirestoreSessionService

    created = []

    async def fake_super_create(self, *, app_name, user_id, state=None, session_id=None):
        sid = session_id or f"generated-{len(created) + 1}"
        created.append((app_name, user_id, sid, state))
        return Session(id=sid, app_name=app_name, user_id=user_id, state=dict(state or {}))

    async def fake_append_event(self, session, event):
        return event

    monkeypatch.setattr(FirestoreSessionService, "create_session", fake_super_create)
    monkeypatch.setattr(CoachFirestoreSessionService, "append_event", fake_append_event)

    svc = CoachFirestoreSessionService.__new__(CoachFirestoreSessionService)
    s1 = asyncio.run(svc.create_session(app_name="running_coach", user_id="web_u@x.com", state={"__k": 1}))
    s2 = asyncio.run(svc.create_session(app_name="running_coach", user_id="web_u@x.com"))
    assert s1.id == "generated-1" and s2.id == "generated-2"
    assert s1.state == {"__k": 1}
    assert len(created) == 2

