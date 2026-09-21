import pytest

from running_coach.utils.profile_helpers import (
    format_profile_summary,
    get_user_id,
    merge_profile_data,
    parse_runner_name,
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

    def test_defaults_sleep_average_and_coordinates(self):
        profile = merge_profile_data(answers={}, temp_data={})
        assert profile["sleep_hours_2w_avg"] == 7.0
        assert profile["latitude"] is None
        assert profile["longitude"] is None

    def test_carries_goal_and_timeline_from_answers(self):
        profile = merge_profile_data(
            answers={"training_goal": "Sub-3:30 Marathon", "timeline": "2026-11-01"},
            temp_data={},
        )
        assert profile["training_goal"] == "Sub-3:30 Marathon"
        assert profile["timeline"] == "2026-11-01"


class TestSyncProfileToState:
    def test_populates_profile_summary_and_user_id(self):
        ctx = FakeContext()
        sync_profile_to_state(ctx, {"firstname": "Casper", "lastname": "Visser", "age": "41"})
        assert ctx.state["user_id"] == "casper_visser"
        assert ctx.state["user_profile"]["age"] == "41"
        assert "Casper Visser" in ctx.state["user_profile_summary"]

    def test_omits_user_id_when_name_is_absent(self):
        ctx = FakeContext()
        sync_profile_to_state(ctx, {"age": "41"})
        assert "user_id" not in ctx.state


def test_format_profile_summary_is_empty_for_empty_profile():
    assert format_profile_summary({}) == ""
