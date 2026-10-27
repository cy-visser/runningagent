"""Tests for goal plans: north star + dated sub-goal blocks (utils/goals.py)."""

from datetime import date

import pytest

from running_coach.utils.goals import (
    KIND_NORTH_STAR,
    KIND_SINGLE,
    KIND_SUB_GOAL,
    current_goal,
    final_race_passed,
    format_gap,
    format_goal_plan,
    format_projection_vs_north_star,
    format_workout_goal_context,
    next_block,
    north_star_equivalent,
    race_duration_s,
    race_result_update,
    sub_goal_for_date,
    sub_goals_missing_result,
)

SINGLE = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-11-01", "goal_set_date": "2026-06-01"}


def plan(results=None, ns_start=None):
    results = results or {}
    return {
        "goal_type": "plan",
        "north_star": {"goal": "Sub-3:15 Marathon", "race_name": "London Marathon 2028",
                       "start_date": ns_start, "race_date": "2028-04-23"},
        # Deliberately unsorted: blocks are ordered by race date.
        "sub_goals": [
            {"goal": "Sub-43 10K", "start_date": "2027-03-01", "race_date": "2027-05-16",
             "result": results.get(1)},
            {"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07",
             "result": results.get(0)},
            {"goal": "Sub-1:34 Half Marathon", "start_date": "2027-07-01", "race_date": "2027-10-10",
             "result": results.get(2)},
        ],
    }


class TestCurrentGoal:
    def test_single_goal_uses_profile_fields(self):
        goal = current_goal(SINGLE, date(2026, 10, 23))
        assert goal["kind"] == KIND_SINGLE
        assert (goal["training_goal"], goal["timeline"], goal["goal_set_date"]) == (
            "Sub-3:30 Marathon", "2026-11-01", "2026-06-01")

    def test_missing_goal_type_is_single(self):
        assert current_goal({"training_goal": "x", "timeline": "2026-11-01"})["kind"] == KIND_SINGLE

    def test_inside_first_block(self):
        goal = current_goal(plan(), date(2027, 1, 10))
        assert goal["kind"] == KIND_SUB_GOAL
        assert goal["training_goal"] == "Sub-21 5K"
        assert goal["timeline"] == "2027-02-07"
        assert goal["goal_set_date"] == "2026-11-30"
        assert goal["before_start"] is False

    def test_race_day_still_counts_as_current_block(self):
        assert current_goal(plan(), date(2027, 2, 7))["training_goal"] == "Sub-21 5K"

    def test_between_blocks_is_next_block_before_start(self):
        goal = current_goal(plan(), date(2027, 2, 8))
        assert goal["training_goal"] == "Sub-43 10K"
        assert goal["before_start"] is True

    def test_north_star_block_default_start(self):
        goal = current_goal(plan(), date(2027, 12, 1))
        assert goal["kind"] == KIND_NORTH_STAR
        assert goal["goal_set_date"] == "2027-10-11"  # day after the last sub-goal race
        assert goal["before_start"] is False

    def test_north_star_block_explicit_start(self):
        goal = current_goal(plan(ns_start="2027-12-01"), date(2027, 11, 1))
        assert goal["kind"] == KIND_NORTH_STAR
        assert goal["before_start"] is True

    def test_after_final_race_stays_on_north_star(self):
        assert current_goal(plan(), date(2028, 5, 1))["kind"] == KIND_NORTH_STAR


class TestDueStates:
    def test_final_race_passed_single(self):
        assert final_race_passed(SINGLE, date(2026, 11, 1)) is None
        assert final_race_passed(SINGLE, date(2026, 11, 2))["timeline"] == "2026-11-01"

    def test_sub_goal_race_never_ends_plan(self):
        assert final_race_passed(plan(), date(2027, 2, 8)) is None

    def test_final_race_passed_plan(self):
        assert final_race_passed(plan(), date(2028, 4, 24))["kind"] == KIND_NORTH_STAR

    def test_sub_goals_missing_result(self):
        assert sub_goals_missing_result(plan(), date(2027, 2, 7)) == []
        missing = sub_goals_missing_result(plan(), date(2027, 2, 8))
        assert [b["training_goal"] for b in missing] == ["Sub-21 5K"]
        saved = plan(results={0: {"time": "20:45", "time_s": 1245}})
        assert sub_goals_missing_result(saved, date(2027, 2, 8)) == []

    def test_sub_goal_for_date_and_next_block(self):
        block = sub_goal_for_date(plan(), "2027-02-07T09:30:00")
        assert block["training_goal"] == "Sub-21 5K"
        assert next_block(plan(), block)["training_goal"] == "Sub-43 10K"
        assert sub_goal_for_date(plan(), "2027-02-06") is None
        assert sub_goal_for_date(SINGLE, "2026-11-01") is None


class TestRaceResult:
    def test_race_day_run_saves_result(self):
        profile = plan()
        update = race_result_update(profile, "2027-02-07", 1245.0, 99, sport="Run")
        saved = update["sub_goals"][1]
        assert saved["goal"] == "Sub-21 5K"
        assert saved["result"] == {"time": "20:45", "time_s": 1245, "workout_id": "99"}
        assert profile["sub_goals"][1]["result"] is None  # input is not mutated
        assert all(s.get("result") is None for i, s in enumerate(update["sub_goals"]) if i != 1)

    def test_no_update_outside_race_day_single_goal_or_bike(self):
        assert race_result_update(plan(), "2027-02-06", 1245.0, 1) is None
        assert race_result_update(SINGLE, "2026-11-01", 1245.0, 1) is None
        assert race_result_update(plan(), "2027-02-07", 1245.0, 1, sport="Bike") is None
        assert race_result_update(plan(), "2027-02-07", None, 1) is None

    def test_race_duration_prefers_duration_actual(self):
        assert race_duration_s({"duration_actual": 0.25}, {"totals": {"Duration": 1}}) == 900.0
        assert race_duration_s({}, {"totals": {"Duration": {"value": 1245, "unit": "s"}}}) == 1245.0
        assert race_duration_s({}, {}) is None


class TestNorthStarEquivalents:
    @pytest.mark.parametrize("time_s, goal, expected_s", [
        (21 * 60, "Sub-21 5K", 12086),          # ~3:21:26
        (43 * 60, "Sub-43 10K", 11868),         # ~3:17:48
        (94 * 60, "Sub-1:34 Half Marathon", 11760),  # ~3:16:00
    ])
    def test_riegel_to_marathon(self, time_s, goal, expected_s):
        assert north_star_equivalent(time_s, goal, "Sub-3:15 Marathon") == pytest.approx(expected_s, abs=5)

    def test_unknown_distance(self):
        assert north_star_equivalent(1200, "Sub-20 parkrun", "Sub-3:15 Marathon") is None

    def test_format_gap(self):
        assert format_gap(390) == "+6:30 slower"
        assert format_gap(-65) == "-1:05 faster"
        assert format_gap(0.4) == "on target"
        assert format_gap(None) == "-"


class TestFormatting:
    def test_single_goal_has_no_plan_block(self):
        assert format_goal_plan(SINGLE, date(2026, 10, 23)) == ""
        assert format_workout_goal_context(SINGLE, "2026-11-01", 12000, False) == ""

    def test_goal_plan_block_with_results_and_missing(self):
        profile = plan(results={0: {"time": "20:45", "time_s": 1245}})
        text = format_goal_plan(profile, date(2027, 5, 20))
        assert "North star: Sub-3:15 Marathon (London Marathon 2028), race 2028-04-23" in text
        assert "| Sub-21 5K | 2026-11-30 -> 2027-02-07 | done | 21:00 -> 3:21:25 | 20:45 -> 3:19:01 | +4:01 slower |" in text
        assert "| Sub-43 10K | 2027-03-01 -> 2027-05-16 | done |" in text and "missing: ask the runner" in text
        assert "| Sub-1:34 Half Marathon | 2027-07-01 -> 2027-10-10 | upcoming (next block) |" in text
        assert "Between blocks" in text
        assert "North-star peak CTL reference range" in text

    def test_projection_vs_north_star(self):
        projection = {"projection": {"race_day_s": 1245}}
        line = format_projection_vs_north_star(plan(), projection, date(2027, 1, 10))
        assert "Sub-21 5K race-day 20:45 -> north-star equivalent 3:19:01" in line
        assert format_projection_vs_north_star(SINGLE, projection, date(2026, 10, 1)) == ""

    def test_workout_context_race_day_and_normal_day(self):
        race = format_workout_goal_context(plan(), "2027-02-07", 1245, True)
        assert "finish time 20:45" in race and "3:19:01" in race and "Result saved" in race
        normal = format_workout_goal_context(plan(), "2027-01-10", 3000, False)
        assert normal.startswith("**Goal plan:** current block Sub-21 5K")
