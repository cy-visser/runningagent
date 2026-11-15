"""Behavioural tests for /api/race-predictor, cold-cache auto-compute, goal invalidation, and goal_type='none'."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import EMAIL, build_test_app

HEADERS = {"X-Goog-IAP-JWT-Assertion": "valid-jwt"}


def _plan_user() -> dict:
    return {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": EMAIL,
        "goal_type": "plan",
        "north_star": {
            "goal": "Sub-3:15 Marathon",
            "race_name": "London Marathon 2028",
            "race_date": "2028-04-23",
        },
        "sub_goals": [
            {
                "goal": "Sub-21 5K",
                "race_name": "Amsterdam 5K",
                "start_date": "2025-08-01",
                "race_date": "2025-10-20",
                "result": {"time": "20:45", "time_s": 1245},
            },
            {
                "goal": "Sub-43 10K",
                "race_name": "Schoorl 10K",
                "start_date": "2026-11-16",
                "race_date": "2027-02-14",
                "result": None,
                "planned": True,
            },
        ],
    }


def _sample_cache_doc(goal_key: str = "sub_goal:sub-43 10k:2027-02-14", trigger: str = "workout_analysis") -> dict:
    return {
        "version": 1,
        "updated_at": "2026-11-15T09:00:00Z",
        "as_of_date": "2026-11-15",
        "trigger": trigger,
        "trigger_workout": {
            "workout_id": "w102",
            "date": "2026-11-14",
            "title": "Threshold 2 x 15'",
            "quality_km": 6.4,
        },
        "goal_key": goal_key,
        "active_goal": {
            "kind": "sub_goal",
            "training_goal": "Sub-43 10K",
            "race_name": "Schoorl 10K",
            "race_date": "2027-02-14",
            "start_date": "2026-11-16",
            "goal_label": "10K",
            "planned": True,
            "before_start": False,
            "weeks_remaining": 13.0,
            "sub_goal_step": 2,
            "sub_goal_total": 2,
        },
        "north_star": {
            "training_goal": "Sub-3:15 Marathon",
            "goal_label": "Marathon",
            "race_name": "London Marathon 2028",
            "race_date": "2028-04-23",
            "target_s": 11700,
            "equivalent_s": 11910,
            "gap_s": 210,
        },
        "window_weeks": 12,
        "key_sessions_count": 9,
        "projection": {
            "goal_label": "10K",
            "today_s": 2610,
            "race_day_s": 2565,
            "today_pace_s_per_km": 261.0,
            "race_pace_s_per_km": 256.5,
            "goal_s": 2580,
            "gap_s": -15,
            "range_s": [2535, 2595],
            "confidence": "High",
            "stale": False,
            "readiness": "🟢",
            "durability": "strong",
            "signals": ["Threshold", "Goal-pace", "HR efficiency"],
            "drivers": [
                {"driver": "Threshold", "evidence": "4:16/km @ 171 bpm", "implied": "42:45"},
            ],
        },
    }


def test_race_predictor_returns_cached_subgoal_projection_without_calling_agent():
    app, store, agent = build_test_app()
    store.users["cyrille_visser"] = _plan_user()
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}
    store.race_projections["cyrille_visser"] = _sample_cache_doc()

    client = TestClient(app)
    res = client.get("/api/race-predictor", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ready"
    assert body["cached"] is True
    assert body["active_goal"]["kind"] == "sub_goal"
    assert body["active_goal"]["training_goal"] == "Sub-43 10K"
    assert body["data"]["north_star"]["training_goal"] == "Sub-3:15 Marathon"
    assert body["data"]["projection"]["race_day_s"] == 2565
    assert agent.ephemeral_calls == []


def test_race_predictor_cold_cache_and_manual_refresh_invoke_ephemeral_quick_action():
    app, store, agent = build_test_app()
    store.users["cyrille_visser"] = _plan_user()
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}

    def populate_cache(_call: dict) -> None:
        store.race_projections["cyrille_visser"] = _sample_cache_doc(trigger="manual_refresh")

    agent.on_ephemeral_action = populate_cache
    client = TestClient(app)

    # Cold cache -> auto-computes via check-in-report:project
    cold = client.get("/api/race-predictor", headers=HEADERS)
    assert cold.status_code == 200
    cold_body = cold.json()
    assert cold_body["status"] == "ready"
    assert cold_body["cached"] is False
    assert len(agent.ephemeral_calls) == 1
    assert agent.ephemeral_calls[0]["quick_action"] == {"skill": "check-in-report:project", "args": {}}

    # Subsequent GET hits Firestore cache with zero new agent calls
    warm = client.get("/api/race-predictor", headers=HEADERS)
    assert warm.status_code == 200
    assert warm.json()["cached"] is True
    assert len(agent.ephemeral_calls) == 1

    # Explicit POST /api/race-predictor/refresh forces recomputation
    refreshed = client.post("/api/race-predictor/refresh", headers=HEADERS)
    assert refreshed.status_code == 200
    assert refreshed.json()["cached"] is False
    assert len(agent.ephemeral_calls) == 2


def test_race_predictor_no_goal_past_race_and_non_race_goal_states():
    app, store, agent = build_test_app()
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}
    client = TestClient(app)

    # 1. Explicit goal_type="none"
    store.users["cyrille_visser"] = {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": EMAIL,
        "goal_type": "none",
    }
    res_none = client.get("/api/race-predictor", headers=HEADERS)
    assert res_none.status_code == 200
    assert res_none.json()["status"] == "no_goal"
    assert res_none.json()["reason"] == "no_goal"

    # 2. Past final race date
    store.users["cyrille_visser"] = {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": EMAIL,
        "goal_type": "single",
        "training_goal": "Sub-3:30 Marathon",
        "timeline": "2020-04-12",
    }
    res_past = client.get("/api/race-predictor", headers=HEADERS)
    assert res_past.status_code == 200
    assert res_past.json()["status"] == "no_goal"
    assert res_past.json()["reason"] == "race_passed"

    # 3. Non-distance fitness goal
    store.users["cyrille_visser"] = {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": EMAIL,
        "goal_type": "single",
        "training_goal": "Run injury-free 4x per week",
        "timeline": "2027-06-01",
    }
    res_non_race = client.get("/api/race-predictor", headers=HEADERS)
    assert res_non_race.status_code == 200
    assert res_non_race.json()["status"] == "no_goal"
    assert res_non_race.json()["reason"] == "non_race_goal"
    assert agent.ephemeral_calls == []


def test_put_profile_goal_change_invalidates_projection_cache_and_supports_no_goal_mode():
    app, store, _ = build_test_app()
    store.users["cyrille_visser"] = _plan_user()
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}
    store.race_projections["cyrille_visser"] = _sample_cache_doc()

    client = TestClient(app)

    # Non-goal profile edit (injury note) preserves cached race projection
    keep_res = client.put(
        "/api/profile",
        headers=HEADERS,
        json={
            "goal_type": "plan",
            "north_star": {"goal": "Sub-3:15 Marathon", "race_name": "London Marathon 2028", "race_date": "2028-04-23"},
            "sub_goals": [
                {"goal": "Sub-21 5K", "race_name": "Amsterdam 5K", "start_date": "2025-08-01", "race_date": "2025-10-20"},
                {"goal": "Sub-43 10K", "race_name": "Schoorl 10K", "start_date": "2026-11-16", "race_date": "2027-02-14", "planned": True},
            ],
            "injuries": "Mild calf tightness",
        },
    )
    assert keep_res.status_code == 200
    assert "cyrille_visser" in store.race_projections

    # Switching to "No Goal" ("goal_type": "none") keeps profile_state == "ready" and clears cached projection
    clear_res = client.put(
        "/api/profile",
        headers=HEADERS,
        json={"goal_type": "none", "location": "Amsterdam"},
    )
    assert clear_res.status_code == 200
    clear_body = clear_res.json()
    assert clear_body["profile_state"] == "ready"
    assert clear_body["profile"]["goal_type"] == "none"
    assert "north_star" not in clear_body["profile"]
    assert "sub_goals" not in clear_body["profile"]
    assert clear_body["profile"].get("training_goal") is None
    assert "cyrille_visser" not in store.race_projections


def test_agent_runtime_client_deletes_ephemeral_session_even_on_stream_error():
    import asyncio
    import httpx
    import pytest
    from app.agent_client import AgentRuntimeClient
    from app.settings import Settings

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"id": "ephemeral-123"})
        if request.method == "POST" and request.url.path.endswith("/run_sse"):
            body = 'data: {"errorMessage": "boom"}\n\n'
            return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": "text/event-stream"})
        if request.method == "DELETE" and request.url.path.endswith("/sessions/ephemeral-123"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    settings = Settings(
        auth_mode="dev",
        iap_audience=None,
        dev_user_email=EMAIL,
        project_id="firestore-cyvisser",
        firestore_database="running-coach",
        tp_cookie_kms_key=None,
        agent_runtime_resource=None,
        agent_base_url="http://agent.local",
        agent_app_name="running_coach",
        static_dir="/tmp/nonexistent-static",
        k_service=None,
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AgentRuntimeClient(settings=settings, http_client=http_client)

    async def run():
        try:
            with pytest.raises(RuntimeError, match="boom"):
                await client.run_ephemeral_quick_action(
                    adk_user_id=f"web_{EMAIL}",
                    auth_email=EMAIL,
                    quick_action={"skill": "check-in-report:project", "args": {}},
                )
        finally:
            await http_client.aclose()

    asyncio.run(run())
    assert seen == [
        ("POST", f"/apps/running_coach/users/web_{EMAIL}/sessions"),
        ("POST", "/run_sse"),
        ("DELETE", f"/apps/running_coach/users/web_{EMAIL}/sessions/ephemeral-123"),
    ]

