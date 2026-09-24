from datetime import date

import pytest

from running_coach.utils.trajectory import (
    DEFAULT_PEAK_CTL,
    evaluate_goal_trajectory,
    parse_target_time_minutes,
    resolve_goal_distance,
    resolve_target_peak_ctl,
)


class TestParseTargetTimeMinutes:
    @pytest.mark.parametrize(
        "goal, expected",
        [
            ("Sub-3:30 Marathon", 210),
            ("3:00 Marathon", 180),
            ("Sub-4 hour marathon", 240),
            ("3 hours and 15 mins", 195),
            ("Sub-1:45 Half", 105),
            ("Sub-20 5K", 20),
            ("Sub-45 10K", 45),
            ("45 minutes 10K", 45),
        ],
    )
    def test_extracts_target_minutes(self, goal, expected):
        assert parse_target_time_minutes(goal) == expected

    @pytest.mark.parametrize("goal", [None, "", "Just finish the race", "Get fitter"])
    def test_returns_none_without_a_time(self, goal):
        assert parse_target_time_minutes(goal) is None


class TestResolveTargetPeakCtl:
    def test_half_marathon_is_matched_before_marathon(self):
        """'half marathon' contains 'marathon', so ordering matters."""
        half, _ = resolve_target_peak_ctl("Sub-1:45 Half Marathon")
        full, _ = resolve_target_peak_ctl("Sub-3:30 Marathon")
        assert half == 68.0
        assert full == 80.0

    @pytest.mark.parametrize(
        "goal, expected_peak",
        [
            ("100k ultra", 90.0),
            ("Sub-3:00 Marathon", 95.0),
            ("Sub-4:30 Marathon", 55.0),
            ("Sub-20 5K", 60.0),
            ("Sub-40 10K", 65.0),
        ],
    )
    def test_resolves_expected_benchmarks(self, goal, expected_peak):
        peak, _ = resolve_target_peak_ctl(goal)
        assert peak == expected_peak

    def test_unknown_goal_uses_the_default(self):
        peak, ref_range = resolve_target_peak_ctl("General fitness")
        assert peak == DEFAULT_PEAK_CTL
        assert len(ref_range) == 2

    def test_range_brackets_the_target(self):
        peak, (low, high) = resolve_target_peak_ctl("Sub-3:30 Marathon")
        assert low <= peak <= high

    @pytest.mark.parametrize(
        "goal, expected_peak",
        [("Sub-1:05 10 mile", 70.0), ("Sub-1:15 10 Mile", 60.0), ("Run a 10 mile race", 60.0)],
    )
    def test_ten_mile_bands(self, goal, expected_peak):
        peak, _ = resolve_target_peak_ctl(goal)
        assert peak == expected_peak


class TestResolveGoalDistance:
    @pytest.mark.parametrize(
        "goal, label, pr_type",
        [
            ("Sub-20 5K", "5K", "speed5K"),
            ("Run a 10k", "10K", "speed10K"),
            ("Sub-1:15 10 mile", "10 Mile", "speed10Mi"),
            ("Dam tot Damloop 10 miles", "10 Mile", "speed10Mi"),
            ("Sub-1:45 Half Marathon", "Half Marathon", "speedHalfMarathon"),
            ("Sub-3:30 Marathon", "Marathon", "speedMarathon"),
        ],
    )
    def test_resolves_supported_distances(self, goal, label, pr_type):
        resolved = resolve_goal_distance(goal)
        assert resolved[0] == label
        assert resolved[2] == pr_type

    @pytest.mark.parametrize("goal", [None, "", "General fitness", "100k ultra"])
    def test_unsupported_goals_return_none(self, goal):
        assert resolve_goal_distance(goal) is None


class TestEvaluateGoalTrajectory:
    def test_computes_ramp_rate_excluding_the_taper(self):
        # 12 weeks out, so 10 build weeks after the 2-week taper; 40 CTL to gain.
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-12-08"}
        result = evaluate_goal_trajectory(profile, current_ctl=40.0, today_date=date(2026, 9, 15))
        assert result["weeks_remaining"] == 12.0
        assert result["build_weeks"] == 10.0
        assert result["target_peak_ctl"] == 80.0
        assert result["required_ramp_rate"] == 4.0

    def test_no_ramp_needed_when_already_at_target(self):
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-12-08"}
        result = evaluate_goal_trajectory(profile, current_ctl=95.0, today_date=date(2026, 9, 15))
        assert result["required_ramp_rate"] == 0.0

    def test_past_timeline_clamps_weeks_to_zero(self):
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-01-01"}
        result = evaluate_goal_trajectory(profile, current_ctl=40.0, today_date=date(2026, 9, 15))
        assert result["weeks_remaining"] == 0.0
        assert result["build_weeks"] == 0.0

    def test_missing_timeline_leaves_projections_unset(self):
        result = evaluate_goal_trajectory({"training_goal": "Marathon"}, current_ctl=50.0)
        assert result["weeks_remaining"] is None
        assert result["required_ramp_rate"] is None

    def test_unparseable_timeline_does_not_raise(self):
        profile = {"training_goal": "Marathon", "timeline": "next spring"}
        result = evaluate_goal_trajectory(profile, current_ctl=50.0, today_date=date(2026, 9, 15))
        assert result["weeks_remaining"] is None

    def test_defaults_goal_name_when_absent(self):
        assert evaluate_goal_trajectory({}, current_ctl=50.0)["goal_name"] == "General Fitness"
