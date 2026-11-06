"""Behavioural test for ADK-to-UI SSE event translation and end-to-end connect -> onboarding -> chat flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.events import TurnEventTranslator
from conftest import EMAIL, build_test_app


def test_event_translator_and_connect_onboarding_chat_sse_flow():
    tr = TurnEventTranslator()

    # Thinking part -> status thinking (no raw thought text leaked)
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [{"thought": True, "text": "secret plan"}]}}) == [
        ("status", {"phase": "thinking"})
    ]

    # Tool call
    assert tr.feed({"author": "coaching_agent", "content": {"parts": [{"functionCall": {"name": "fetch_checkin_data"}}]}}) == [
        ("tool", {"name": "fetch_checkin_data", "label": "Pulling 14 days of TrainingPeaks data", "state": "start"})
    ]

    # Tool response with both whitelisted checkin_report_data and internal non-whitelisted state keys
    evs = tr.feed(
        {
            "author": "coaching_agent",
            "actions": {
                "stateDelta": {
                    "user_profile": {"email": "private"},
                    "checkin_tables": "| table |",
                    "checkin_report_data": {"version": 1, "ctl": {"current": 62.4}},
                }
            },
            "content": {"parts": [{"functionResponse": {"name": "fetch_checkin_data", "response": {"result": "ok"}}}]},
        }
    )
    assert evs == [
        ("report", {"kind": "checkin", "data": {"version": 1, "ctl": {"current": 62.4}}}),
        ("tool", {"name": "fetch_checkin_data", "label": "Pulling 14 days of TrainingPeaks data", "state": "done"}),
    ]

    # Partial text chunk + final spliced text
    assert tr.feed({"author": "coaching_agent", "partial": True, "content": {"parts": [{"text": "## Check-in"}]}}) == [
        ("delta", {"text": "## Check-in"})
    ]
    assert tr.feed({"author": "coaching_agent", "partial": False, "content": {"parts": [{"text": "## Check-in\nFull"}]}}) == [
        ("message", {"text": "## Check-in\nFull", "kind": "checkin"})
    ]

    # Audit report payload is also whitelisted
    tr_audit = TurnEventTranslator()
    audit_evs = tr_audit.feed(
        {
            "author": "coaching_agent",
            "actions": {"stateDelta": {"audit_report_data": {"version": 1, "weeks": []}}},
            "content": {"parts": [{"text": "Audit summary"}]},
        }
    )
    assert audit_evs == [
        ("report", {"kind": "audit", "data": {"version": 1, "weeks": []}}),
        ("message", {"text": "Audit summary", "kind": "audit"}),
    ]

    # End-to-end API flow: connect -> onboarding profile edit -> chat SSE & session lifecycle
    app, _, agent = build_test_app()
    headers = {"X-Goog-IAP-JWT-Assertion": "valid-jwt"}
    with TestClient(app) as client:
        me0 = client.get("/api/me", headers=headers)
        assert me0.status_code == 200
        assert "Content-Security-Policy" in me0.headers
        assert me0.json()["profile_state"] == "none"

        conn = client.post("/api/trainingpeaks/connect", json={"cookie": "validcookie123"}, headers=headers)
        assert conn.status_code == 200
        assert conn.json()["profile_state"] == "needs_onboarding"

        edited = client.put(
            "/api/profile",
            headers=headers,
            json={
                "location": "Utrecht",
                "goal_type": "single",
                "training_goal": "Sub-3:30 Marathon",
                "timeline": "2027-04-11",
                "shoe_rotation": "Asics Superblast 2",
            },
        )
        assert edited.status_code == 200
        assert edited.json()["profile_state"] == "ready"
        assert edited.json()["profile"]["email"] == EMAIL

        assert client.get("/api/session", headers=headers).status_code == 404

        chat = client.post("/api/chat", json={"message": "Checking in"}, headers=headers)
        assert chat.status_code == 200
        assert "event: message" in chat.text
        assert "event: done" in chat.text
        assert agent.created_sessions == 1
        assert agent.calls[0]["session_id"] == "sess-new-1"
        assert agent.calls[0]["user_id"] == f"web_{EMAIL}"
        assert agent.calls[0]["auth_email"] == EMAIL

        chat2 = client.post(
            "/api/chat",
            json={"message": "Follow up", "session_id": "sess-new-1"},
            headers=headers,
        )
        assert chat2.status_code == 200
        assert agent.created_sessions == 1
        assert agent.calls[1]["session_id"] == "sess-new-1"

        # Another quick-action button click (no session_id) starts a brand-new session
        chat3 = client.post(
            "/api/chat",
            json={"message": "Analyze today's run"},
            headers=headers,
        )
        assert chat3.status_code == 200
        assert agent.created_sessions == 2
        assert agent.calls[2]["session_id"] == "sess-new-2"

        # Clicking "New conversation" creates a new session immediately
        new_sess = client.post("/api/session/new", headers=headers)
        assert new_sess.status_code == 200
        assert new_sess.json()["session_id"] == "sess-new-3"
        assert agent.created_sessions == 3

        # Next message uses the session created by "New conversation"
        chat4 = client.post(
            "/api/chat",
            json={"message": "Hello in new session", "session_id": "sess-new-3"},
            headers=headers,
        )
        assert chat4.status_code == 200
        assert agent.created_sessions == 3
        assert agent.calls[3]["session_id"] == "sess-new-3"
