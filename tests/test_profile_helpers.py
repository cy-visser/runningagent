from running_coach.utils.profile_helpers import (
    RUNNER_ID_STATE_KEY,
    get_user_id,
    merge_profile_data,
    normalize_timeline,
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


class TestSyncProfileToState:
    def test_populates_profile_summary_and_runner_id(self):
        ctx = FakeContext()
        sync_profile_to_state(ctx, {"firstname": "Casper", "lastname": "Visser", "age": "41"})
        assert ctx.state[RUNNER_ID_STATE_KEY] == "casper_visser"
        assert "user_id" not in ctx.state
        assert ctx.state["user_profile"]["age"] == "41"
        assert "Casper Visser" in ctx.state["user_profile_summary"]


def test_normalize_timeline():
    for raw, expected in [("November 1st, 2026", "2026-11-01"), ("2026-11-01", "2026-11-01"),
                          ("next spring", "next spring"), (None, None), ("", "")]:
        assert normalize_timeline(raw) == expected, raw
