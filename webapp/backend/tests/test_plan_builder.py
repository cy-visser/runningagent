"""Behavioural test for the plan-builder BFF contract: quick-action validation, plan events and block start date."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.events import TurnEventTranslator
from app.profile_model import summarize_profile
from conftest import build_test_app

STAGED_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def test_plan_builder_actions_events_and_active_start_date():
    # Plan events: staged plan -> "plan_staged" (backend-only spec/zones stripped); apply progress -> "plan_applied".
    week = {"week": 1, "start": "2026-11-30", "phase": "base", "rows": []}
    staged = {"version": 1, "staged_id": STAGED_ID, "title": "Plan", "weeks": [week],
              "spec": {"weeks": []}, "zones": {"E": "5:30"}}
    tr = TurnEventTranslator()
    assert tr.feed({"author": "coaching_agent", "actions": {"stateDelta": {"staged_training_plan": staged}},
                    "content": {"parts": [{"functionResponse": {"name": "stage_training_plan", "response": {}}}]}}) == [
        ("plan_staged", {"version": 1, "staged_id": STAGED_ID, "title": "Plan", "weeks": [week]}),
        ("tool", {"name": "stage_training_plan", "label": "Building your plan", "state": "done"}),
    ]
    applied = {"staged_id": STAGED_ID, "total_weeks": 24, "weeks_done": [1], "created": 5, "updated": 1,
               "deleted": 0, "failed": 0, "failed_weeks": [], "done": False}
    assert TurnEventTranslator().feed({"author": "coaching_agent", "actions": {
        "skipSummarization": True, "stateDelta": {"applied_training_plan": applied}}}) == [("plan_applied", applied)]
    assert TurnEventTranslator().feed({"author": "coaching_agent", "content": {"parts": [
        {"functionCall": {"name": "fetch_plan_context"}}]}}) == [
        ("tool", {"name": "fetch_plan_context", "label": "Reading your training history", "state": "start"})]

    # Quick actions: plan-builder and plan-builder:apply are validated and forwarded as {skill, args}.
    app, _, agent = build_test_app()
    headers = {"X-Goog-IAP-JWT-Assertion": "valid-jwt"}
    with TestClient(app) as client:
        build = client.post("/api/chat", headers=headers, json={
            "message": "Build my training plan", "action": {
                "skill": "plan-builder", "start_date": "2026-11-30", "end_date": "2027-05-16"}})
        assert build.status_code == 200
        assert agent.calls[0]["quick_action"] == {
            "skill": "plan-builder", "args": {"start_date": "2026-11-30", "end_date": "2027-05-16", "mode": "new"}}

        apply = client.post("/api/chat", headers=headers, json={
            "message": "Apply plan week 3", "session_id": "sess-new-1",
            "action": {"skill": "plan-builder:apply", "staged_id": STAGED_ID, "week": 3}})
        assert apply.status_code == 200
        assert agent.calls[1]["quick_action"] == {"skill": "plan-builder:apply", "args": {"staged_id": STAGED_ID, "week": 3}}

        for bad in (
            {"skill": "plan-builder", "start_date": "2026-11-30"},
            {"skill": "plan-builder", "start_date": "30 Nov", "end_date": "2027-05-16"},
            {"skill": "plan-builder", "start_date": "2026-11-30", "end_date": "2027-05-16", "mode": "rewrite"},
            {"skill": "plan-builder:apply", "staged_id": STAGED_ID},
            {"skill": "plan-builder:apply", "staged_id": STAGED_ID, "week": 0},
            {"skill": "plan-builder:apply", "staged_id": STAGED_ID, "week": 53},
            {"skill": "plan-builder:apply", "staged_id": "nope", "week": 1},
            {"skill": "plan-apply", "staged_id": STAGED_ID, "week": 1},
        ):
            assert client.post("/api/chat", json={"message": "x", "action": bad}, headers=headers).status_code == 422, bad
        assert len(agent.calls) == 2

    # active_start_date: single goal -> goal_set_date; plan -> active sub-goal start, else north-star start.
    today = date(2026, 11, 11)
    single = {"goal_type": "single", "training_goal": "Sub-3:20", "timeline": "2027-05-16", "goal_set_date": "2026-11-05"}
    assert summarize_profile(single, today)["active_start_date"] == "2026-11-05"
    assert summarize_profile({"goal_type": "single", "training_goal": "x"}, today)["active_start_date"] is None
    plan = {
        "goal_type": "plan",
        "north_star": {"goal": "Sub-3:15 Marathon", "race_date": "2028-04-23"},
        "sub_goals": [
            {"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07"},
            {"goal": "Sub-43 10K", "start_date": "2027-02-15", "race_date": "2027-05-02"},
        ],
    }
    summary = summarize_profile(plan, today)
    assert (summary["active_goal"], summary["active_start_date"], summary["active_date"]) == (
        "Sub-21 5K", "2026-11-30", "2027-02-07")
    # After the last sub-goal race, the north-star block starts the day after it.
    late = summarize_profile(plan, date(2027, 6, 1))
    assert (late["active_goal"], late["active_start_date"]) == ("Sub-3:15 Marathon", "2027-05-03")
