from running_coach.utils.profile_helpers import (
    RUNNER_ID_STATE_KEY,
    get_user_id,
    merge_profile_data,
    normalize_timeline,
    onboarding_prefill,
    sync_profile_to_state,
)


class FakeContext:
    """Minimal stand-in for the ADK Context, which only needs a mutable state dict."""

    def __init__(self):
        self.state: dict = {}


def test_get_user_id_builds_canonical_key():
    for first, last, expected in [
        ("Casper", "Visser", "casper_visser"), ("  Casper ", " Visser ", "casper_visser"),
        ("Casper", None, "casper_"), (None, None, "_"),
    ]:
        assert get_user_id(first, last) == expected, (first, last)


class TestMergeProfileData:
    def test_answers_take_precedence_over_harvested_data(self):
        profile = merge_profile_data(
            answers={"age": "41", "weight": "72kg"},
            temp_data={"age": "40", "weight": "70kg", "height": "180cm"},
        )
        assert profile["age"] == "41"
        assert profile["weight"] == "72kg"
        assert profile["height"] == "180cm"

    def test_single_goal(self):
        profile = merge_profile_data(
            answers={"goal_type": "single", "training_goal": "Sub-3:30 Marathon", "timeline": "November 1st, 2026"},
            temp_data={"firstname": "Casper", "lastname": "Visser"},
        )
        assert profile["goal_type"] == "single"
        assert profile["training_goal"] == "Sub-3:30 Marathon"
        assert profile["timeline"] == "2026-11-01"
        assert "north_star" not in profile

    def test_goal_plan_sorted_with_saved_results_kept(self):
        answers = {
            "goal_type": "plan",
            "north_star_goal": "Sub-3:15 Marathon",
            "north_star_race_name": "London Marathon 2028",
            "north_star_race_date": "2028-04-23",
            "sub_goals": [
                {"goal": "Sub-43 10K", "start_date": "2027-02-15", "race_date": "2027-05-02"},
                {"goal": "Sub-21 5K", "race_name": "5K race", "start_date": "2026-11-30", "race_date": "2027-02-07"},
            ],
        }
        saved = {"time": "20:45", "time_s": 1245, "workout_id": "1"}
        temp = {"firstname": "Casper", "lastname": "Visser",
                "sub_goals": [{"goal": "sub-21 5k", "race_date": "2027-02-07", "result": saved}]}
        profile = merge_profile_data(answers=answers, temp_data=temp)
        assert profile["goal_type"] == "plan"
        assert profile["training_goal"] is None and profile["timeline"] is None
        assert profile["north_star"]["race_date"] == "2028-04-23"
        assert [s["goal"] for s in profile["sub_goals"]] == ["Sub-21 5K", "Sub-43 10K"]
        assert profile["sub_goals"][0]["result"] == saved
        assert profile["sub_goals"][1]["result"] is None


class TestSyncProfileToState:
    def test_stores_only_profile_and_runner_id(self):
        ctx = FakeContext()
        sync_profile_to_state(ctx, {"firstname": "Casper", "lastname": "Visser", "age": "41"})
        assert ctx.state[RUNNER_ID_STATE_KEY] == "casper_visser"
        assert "user_id" not in ctx.state
        assert ctx.state["user_profile"]["age"] == "41"
        assert set(ctx.state) == {"user_profile", RUNNER_ID_STATE_KEY}


def test_onboarding_prefill_carries_goal_plan():
    plan = {"goal_type": "plan", "north_star": {"goal": "Sub-3:15 Marathon"}, "sub_goals": [{"goal": "Sub-21 5K"}]}
    seed = onboarding_prefill({"firstname": "Casper", "lastname": "Visser", **plan})
    assert seed["north_star"] == plan["north_star"]
    assert seed["sub_goals"] == plan["sub_goals"]
    assert "training_goal" not in seed


def test_normalize_timeline():
    for raw, expected in [("November 1st, 2026", "2026-11-01"), ("2026-11-01", "2026-11-01"),
                          ("next spring", "next spring"), (None, None), ("", "")]:
        assert normalize_timeline(raw) == expected, raw
