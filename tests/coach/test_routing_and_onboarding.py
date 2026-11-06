"""Behavioural test for profile routing, profile safety guards, and re-onboarding merge."""

import asyncio

import running_coach.agent as agent
import running_coach.steps as steps
from running_coach.tests.fakes import EMAIL, FakeContext
from running_coach.utils import AUTH_EMAIL_STATE_KEY, merge_profile_data


def _route(ctx: FakeContext) -> str:
    asyncio.run(agent.profile_router._func(ctx))
    return ctx.route


def test_router_outcomes_profile_guards_and_sub_goal_result_preservation(runner):
    # Web-authenticated known runner -> COACHING.
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: EMAIL}, user_id=f"web_{EMAIL}")) == agent.ROUTE_COACHING

    # Bare-email session.user_id without user:auth_email is NOT trusted -> NOT_LINKED.
    assert _route(FakeContext(user_id=EMAIL)) == agent.ROUTE_NOT_LINKED

    # Unknown web email -> NOT_LINKED.
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: "stranger@x.com"})) == agent.ROUTE_NOT_LINKED

    # Pending onboarding -> ONBOARDING.
    runner.profiles["jane_doe"] = {
        "firstname": "Jane",
        "lastname": "Doe",
        "email": "jane@x.com",
        "onboarding_pending": True,
    }
    runner.connected_runners.add("jane_doe")
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: "jane@x.com"})) == agent.ROUTE_ONBOARDING

    # Missing TrainingPeaks credential -> TP_NOT_CONNECTED.
    runner.connected_runners.remove("cyrille_visser")
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: EMAIL})) == agent.ROUTE_TP_NOT_CONNECTED

    # Profile creation guards: empty name and email takeover are rejected.
    no_name = FakeContext(state={"temp_onboarding_data": {}, "onboarding_answers": {}})
    assert asyncio.run(steps.create_profile_step(no_name)) == steps.PROFILE_NO_NAME

    conflict = FakeContext(state={
        "temp_onboarding_data": {"firstname": "Cyrille", "lastname": "Visser", "email": "attacker@x.com"},
        "onboarding_answers": {"goal_type": "single", "training_goal": "Sub-20 5K", "timeline": "2027-06-01"},
    })
    assert asyncio.run(steps.create_profile_step(conflict)) == steps.PROFILE_EMAIL_CONFLICT

    # Re-onboarding preserves previously saved sub-goal race results.
    saved = {"time": "20:45", "time_s": 1245, "workout_id": "w_race_5k"}
    merged = merge_profile_data(
        answers={
            "goal_type": "plan",
            "north_star_goal": "Sub-3:15 Marathon",
            "north_star_race_date": "2028-04-23",
            "sub_goals": [
                {"goal": "Sub-43 10K", "start_date": "2027-02-15", "race_date": "2027-05-02"},
                {"goal": "Sub-21 5K", "start_date": "2026-08-01", "race_date": "2026-10-20"},
            ],
        },
        temp_data={
            "firstname": "Cyrille",
            "lastname": "Visser",
            "sub_goals": [{"goal": "sub-21 5k", "race_date": "2026-10-20", "result": saved}],
        },
    )
    assert [s["goal"] for s in merged["sub_goals"]] == ["Sub-21 5K", "Sub-43 10K"]
    assert merged["sub_goals"][0]["result"] == saved
