"""Behavioural test for profile routing, profile safety guards, and re-onboarding merge."""

import asyncio

from running_coach.coach.onboarding import profile_creation
from running_coach.coach import profile_router
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL, FakeContext


def _route(ctx: FakeContext) -> str:
    asyncio.run(profile_router.profile_router._func(ctx))
    return ctx.route


def test_router_outcomes_profile_guards_and_sub_goal_result_preservation(runner):
    # Web-authenticated known runner -> COACHING.
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: EMAIL}, user_id=f"web_{EMAIL}")) == profile_router.ROUTE_COACHING

    # Bare-email session.user_id without user:auth_email is NOT trusted -> NOT_LINKED.
    assert _route(FakeContext(user_id=EMAIL)) == profile_router.ROUTE_NOT_LINKED

    # Unknown web email -> NOT_LINKED.
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: "stranger@x.com"})) == profile_router.ROUTE_NOT_LINKED

    # Pending onboarding -> ONBOARDING.
    runner.profiles["jane_doe"] = {
        "firstname": "Jane",
        "lastname": "Doe",
        "email": "jane@x.com",
        "onboarding_pending": True,
    }
    runner.connected_runners.add("jane_doe")
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: "jane@x.com"})) == profile_router.ROUTE_ONBOARDING

    # Missing TrainingPeaks credential -> TP_NOT_CONNECTED.
    runner.connected_runners.remove("cyrille_visser")
    assert _route(FakeContext(state={AUTH_EMAIL_STATE_KEY: EMAIL})) == profile_router.ROUTE_TP_NOT_CONNECTED

    # Profile creation guards: empty name and email takeover are rejected.
    no_name = FakeContext(state={"temp_onboarding_data": {}, "onboarding_answers": {}})
    assert asyncio.run(profile_creation.create_profile_step(no_name)) == profile_creation.PROFILE_NO_NAME

    conflict = FakeContext(state={
        "temp_onboarding_data": {"firstname": "Cyrille", "lastname": "Visser", "email": "attacker@x.com"},
        "onboarding_answers": {"goal_type": "single", "training_goal": "Sub-20 5K", "timeline": "2027-06-01"},
    })
    assert asyncio.run(profile_creation.create_profile_step(conflict)) == profile_creation.PROFILE_EMAIL_CONFLICT

    # Re-onboarding preserves previously saved sub-goal race results.
    saved = {"time": "20:45", "time_s": 1245, "workout_id": "w_race_5k"}
    merged = profile_creation.merge_profile_data(
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


def test_re_onboarding_keeps_the_coachs_key_events(runner):
    events = [{"date": "2026-10-20", "type": "race", "summary": "Amsterdam 5K: finished in 20:45", "source": "workout_analysis"}]
    runner.profiles["cyrille_visser"]["key_events"] = events
    ctx = FakeContext(state={
        "temp_onboarding_data": {"firstname": "Cyrille", "lastname": "Visser", "email": EMAIL},
        "onboarding_answers": {"goal_type": "single", "training_goal": "Sub-3:20 Marathon", "timeline": "2027-04-11"},
    })
    assert asyncio.run(profile_creation.create_profile_step(ctx)) == profile_creation.PROFILE_SAVED
    stored = runner.profiles["cyrille_visser"]
    assert stored["training_goal"] == "Sub-3:20 Marathon" and stored["key_events"] == events


def test_onboarding_stores_training_times_and_drops_the_legacy_strength_text():
    answers = {"goal_type": "single", "training_goal": "Sub-3:20 Marathon", "timeline": "2027-04-11",
               "run_time_of_day": "morning", "strength_time_of_day": "evening"}
    legacy = {"firstname": "Cyrille", "lastname": "Visser", "cross_training_strength": "2x cycling + 1x strength"}
    merged = profile_creation.merge_profile_data(answers=answers, temp_data=legacy)
    assert (merged["run_time_of_day"], merged["strength_time_of_day"]) == ("morning", "evening")
    assert "cross_training_strength" not in merged

    # Re-onboarding for a new goal keeps (and normalises) the times already on the profile.
    again = profile_creation.merge_profile_data(
        answers={"goal_type": "single", "training_goal": "Sub-1:25 HM", "timeline": "2027-09-12"},
        temp_data={"firstname": "Cyrille", "lastname": "Visser", "run_time_of_day": "Afternoon",
                   "strength_time_of_day": "pm"},
    )
    assert (again["run_time_of_day"], again["strength_time_of_day"]) == ("afternoon", "evening")
    prefill = profile_creation.onboarding_prefill(merged)
    assert prefill["run_time_of_day"] == "morning" and "cross_training_strength" not in prefill
