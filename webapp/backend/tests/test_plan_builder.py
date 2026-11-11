"""Behavioural test for the plan-builder BFF contract: apply quick-action validation and plan events."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from app.events import TurnEventTranslator
from app.profile_model import summarize_profile
from conftest import build_test_app

STAGED_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def test_plan_builder_apply_action_and_events_and_no_build_action():
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

    # Quick actions: plan-builder:apply is validated and forwarded as {skill, args}. The Build Plan button is a
    # plain chat turn, so a plan-builder action no longer exists and is rejected.
    app, _, agent = build_test_app()
    headers = {"X-Goog-IAP-JWT-Assertion": "valid-jwt"}
    with TestClient(app) as client:
        apply = client.post("/api/chat", headers=headers, json={
            "message": "Apply plan week 3", "session_id": "sess-new-1",
            "action": {"skill": "plan-builder:apply", "staged_id": STAGED_ID, "week": 3}})
        assert apply.status_code == 200
        assert agent.calls[0]["quick_action"] == {"skill": "plan-builder:apply", "args": {"staged_id": STAGED_ID, "week": 3}}

        # Build Plan: plan-builder:intake without arguments (the agent computes the window from the profile).
        intake = client.post("/api/chat", headers=headers, json={
            "message": "I'd like to build a new training plan", "action": {"skill": "plan-builder:intake"}})
        assert intake.status_code == 200
        assert agent.calls[1]["quick_action"] == {"skill": "plan-builder:intake", "args": {}}

        for bad in (
            {"skill": "plan-builder", "start_date": "2026-11-30", "end_date": "2027-05-16"},
            {"skill": "plan-builder:intake", "start_date": "2026-11-30"},
            {"skill": "plan-builder:apply", "staged_id": STAGED_ID},
            {"skill": "plan-builder:apply", "staged_id": STAGED_ID, "week": 0},
            {"skill": "plan-builder:apply", "staged_id": STAGED_ID, "week": 53},
            {"skill": "plan-builder:apply", "staged_id": "nope", "week": 1},
            {"skill": "plan-apply", "staged_id": STAGED_ID, "week": 1},
        ):
            assert client.post("/api/chat", json={"message": "x", "action": bad}, headers=headers).status_code == 422, bad
        assert len(agent.calls) == 2

    # The dashboard summary no longer carries a block start date (it only fed the old Build Plan action).
    single = {"goal_type": "single", "training_goal": "Sub-3:20", "timeline": "2027-05-16", "goal_set_date": "2026-11-05"}
    today = date(2026, 11, 11)
    assert "active_start_date" not in summarize_profile(single, today)

    # all_goals_planned: at least one future goal and every future goal planned.
    assert summarize_profile(single, today)["all_goals_planned"] is False
    assert summarize_profile({**single, "planned": True}, today)["all_goals_planned"] is True
    assert summarize_profile({**single, "planned": True}, date(2027, 6, 1))["all_goals_planned"] is False  # race passed
    plan = {"goal_type": "plan", "north_star": {"goal": "Sub-3:15", "race_date": "2028-04-23", "planned": True},
            "sub_goals": [{"goal": "5K", "race_date": "2026-10-20"},                       # past: ignored
                          {"goal": "10K", "race_date": "2027-02-14", "planned": False}]}
    assert summarize_profile(plan, today)["all_goals_planned"] is False
    plan["sub_goals"][1]["planned"] = True
    assert summarize_profile(plan, today)["all_goals_planned"] is True
