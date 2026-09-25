import pytest

from running_coach.utils.profile_helpers import (
    RUNNER_ID_STATE_KEY,
    format_profile_summary,
    get_user_id,
    merge_profile_data,
    onboarding_prefill,
    parse_runner_name,
    profile_user_id,
    sync_profile_to_state,
)


class FakeContext:
    """Minimal stand-in for the ADK Context, which only needs a mutable state dict."""

    def __init__(self):
        self.state: dict = {}


class TestGetUserId:
    @pytest.mark.parametrize(
        "firstname, lastname, expected",
        [
            ("Casper", "Visser", "casper_visser"),
            ("  Casper ", " Visser ", "casper_visser"),
            ("Casper", "", "casper_"),
            ("Casper", None, "casper_"),
            (None, None, "_"),
        ],
    )
    def test_builds_canonical_key(self, firstname, lastname, expected):
        assert get_user_id(firstname, lastname) == expected


class TestParseRunnerName:
    def test_splits_first_and_last_name(self):
        assert parse_runner_name("Casper Visser") == ("Casper", "Visser", "casper_visser")

    def test_keeps_multipart_surnames_intact(self):
        assert parse_runner_name("Casper van der Visser") == (
            "Casper", "van der Visser", "casper_van der visser",
        )

    def test_single_name_has_empty_surname(self):
        assert parse_runner_name("Casper") == ("Casper", "", "casper_")

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_name_yields_sentinel_id(self, raw):
        assert parse_runner_name(raw) == ("", "", "_")


class TestMergeProfileData:
    def test_answers_take_precedence_over_harvested_data(self):
        profile = merge_profile_data(
            answers={"age": "41", "weight": "72kg"},
            temp_data={"age": "40", "weight": "70kg", "height": "180cm"},
        )
        assert profile["age"] == "41"
        assert profile["weight"] == "72kg"
        assert profile["height"] == "180cm"

    def test_name_comes_only_from_harvested_data(self):
        """The onboarding schema does not collect the name, so answers must not win."""
        profile = merge_profile_data(
            answers={"firstname": "Ignored", "lastname": "Ignored"},
            temp_data={"firstname": "Casper", "lastname": "Visser"},
        )
        assert profile["firstname"] == "Casper"
        assert profile["lastname"] == "Visser"

    def test_explicit_location_wins_over_both_sources(self):
        profile = merge_profile_data(
            answers={"location": "Answer City"},
            temp_data={"location": "Temp City"},
            location="Explicit City",
        )
        assert profile["location"] == "Explicit City"

    def test_defaults_coordinates_and_has_no_sleep_average(self):
        profile = merge_profile_data(answers={}, temp_data={})
        assert "sleep_hours_2w_avg" not in profile
        assert profile["latitude"] is None
        assert profile["longitude"] is None

    def test_carries_goal_and_timeline_from_answers(self):
        profile = merge_profile_data(
            answers={"training_goal": "Sub-3:30 Marathon", "timeline": "2026-11-01"},
            temp_data={},
        )
        assert profile["training_goal"] == "Sub-3:30 Marathon"
        assert profile["timeline"] == "2026-11-01"

    def test_stamps_goal_set_date_as_block_start(self):
        from running_coach.utils.date_helpers import get_today_str

        profile = merge_profile_data(answers={"training_goal": "Sub-20 5K"}, temp_data={})
        assert profile["goal_set_date"] == get_today_str()


class TestSyncProfileToState:
    def test_populates_profile_summary_and_runner_id(self):
        ctx = FakeContext()
        sync_profile_to_state(ctx, {"firstname": "Casper", "lastname": "Visser", "age": "41"})
        assert ctx.state[RUNNER_ID_STATE_KEY] == "casper_visser"
        assert "user_id" not in ctx.state
        assert ctx.state["user_profile"]["age"] == "41"
        assert "Casper Visser" in ctx.state["user_profile_summary"]

    def test_omits_runner_id_when_name_is_absent(self):
        ctx = FakeContext()
        sync_profile_to_state(ctx, {"age": "41"})
        assert RUNNER_ID_STATE_KEY not in ctx.state


class TestProfileUserId:
    def test_returns_id_for_named_profile(self):
        assert profile_user_id({"firstname": "Casper", "lastname": "Visser"}) == "casper_visser"

    @pytest.mark.parametrize("profile", [None, {}, {"firstname": " ", "lastname": ""}])
    def test_returns_none_without_name(self, profile):
        assert profile_user_id(profile) is None


def test_onboarding_prefill_copies_answered_fields():
    prefill = onboarding_prefill({"firstname": "Casper", "age": "41", "training_goal": "x"})
    assert prefill["firstname"] == "Casper"
    assert prefill["age"] == "41"
    assert "training_goal" not in prefill


def test_format_profile_summary_is_empty_for_empty_profile():
    assert format_profile_summary({}) == ""


def test_format_profile_summary_omits_coordinates_and_sleep():
    summary = format_profile_summary({"firstname": "C", "latitude": 52.1, "sleep_hours_2w_avg": 7})
    assert "Lat" not in summary
    assert "Sleep" not in summary


class TestNormalizeTimeline:
    from running_coach.utils.profile_helpers import normalize_timeline as _norm

    @pytest.mark.parametrize(
        "raw, expected",
        [("November 1st, 2026", "2026-11-01"), ("2026-11-01", "2026-11-01"),
         ("next spring", "next spring"), (None, None), ("", "")],
    )
    def test_normalizes_when_parseable(self, raw, expected):
        assert TestNormalizeTimeline._norm(raw) == expected

    def test_merge_profile_data_stores_iso_timeline(self):
        profile = merge_profile_data(answers={"timeline": "November 1st, 2026"}, temp_data={})
        assert profile["timeline"] == "2026-11-01"
