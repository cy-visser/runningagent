from datetime import date

import pytest

from running_coach.utils.trajectory import (
    DEFAULT_PEAK_CTL,
    TAPER_WEEKS,
    evaluate_goal_trajectory,
    parse_target_time_minutes,
    resolve_goal_distance,
    resolve_target_peak_ctl,
    resolve_taper_weeks,
)


class TestResolveTaperWeeks:
    @pytest.mark.parametrize(
        "goal, expected",
        [
            ("100k ultra", 3.0),
            ("Sub-4:00 Marathon", 3.0),
            ("Sub-1:45 Half Marathon", 2.0),
            ("Sub-1:15 10 mile", 2.0),
            ("Sub-45 10K", 1.0),
            ("Sub-20 5K", 1.0),
            ("General fitness", TAPER_WEEKS),
            (None, TAPER_WEEKS),
        ],
    )
    def test_distance_defaults(self, goal, expected):
        assert resolve_taper_weeks(goal) == expected

    @pytest.mark.parametrize("override, expected", [(2, 2.0), ("2.5", 2.5), (0, 0.0)])
    def test_valid_override_wins(self, override, expected):
        assert resolve_taper_weeks("Sub-4:00 Marathon", override) == expected

    @pytest.mark.parametrize("override", ["three", -1, ""])
    def test_invalid_override_falls_back_to_default(self, override):
        assert resolve_taper_weeks("Sub-4:00 Marathon", override) == 3.0


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
        "goal, label",
        [
            ("Sub-20 5K", "5K"),
            ("Run a 10k", "10K"),
            ("Sub-50min 10K", "10K"),
            ("Sub-1:15 10 mile", "10 Mile"),
            ("Dam tot Damloop 10 miles", "10 Mile"),
            ("Sub-1:45 Half Marathon", "Half Marathon"),
            ("Sub-3:30 Marathon", "Marathon"),
        ],
    )
    def test_resolves_supported_distances(self, goal, label):
        assert resolve_goal_distance(goal) == label

    @pytest.mark.parametrize("goal", [None, "", "General fitness", "100k ultra", "15k race"])
    def test_unsupported_goals_return_none(self, goal):
        assert resolve_goal_distance(goal) is None


class TestHardenedGoalParsing:
    def test_minutes_suffix_is_not_an_ultra(self):
        peak, _ = resolve_target_peak_ctl("Sub-50min 10K")
        assert peak == 55.0

    @pytest.mark.parametrize(
        "goal, expected",
        [("Sub-19:30 5K", 19.5), ("40:00 10K", 40), ("3:15:00 Marathon", 195), ("Sub-1:05 10 mile", 65)],
    )
    def test_mm_ss_vs_h_mm(self, goal, expected):
        assert parse_target_time_minutes(goal) == pytest.approx(expected)


class TestEvaluateGoalTrajectory:
    def test_computes_ramp_rate_excluding_the_taper(self):
        # 12 weeks out, so 9 build weeks after the 3-week marathon taper; 40 CTL to gain.
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-12-08"}
        result = evaluate_goal_trajectory(profile, current_ctl=40.0, today_date=date(2026, 9, 15))
        assert result["weeks_remaining"] == 12.0
        assert result["taper_weeks"] == 3.0
        assert result["build_weeks"] == 9.0
        assert result["phase"] == "build"
        assert result["target_peak_ctl"] == 80.0
        assert result["required_ramp_rate"] == 4.44

    def test_no_ramp_needed_when_already_at_target(self):
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-12-08"}
        result = evaluate_goal_trajectory(profile, current_ctl=95.0, today_date=date(2026, 9, 15))
        assert result["required_ramp_rate"] == 0.0

    def test_past_timeline_clamps_weeks_to_zero(self):
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-01-01"}
        result = evaluate_goal_trajectory(profile, current_ctl=40.0, today_date=date(2026, 9, 15))
        assert result["weeks_remaining"] == 0.0
        assert result["build_weeks"] == 0.0
        assert result["phase"] == "taper"
        assert result["required_ramp_rate"] is None

    # Race Sun 1 Nov -> nominal 3-week taper starts Sun 11 Oct; peak long run on that Sunday.
    TAPER_PMC = [
        {"date": "2026-10-09", "ctl": 67.8},
        {"date": "2026-10-10", "ctl": 68.1},
        {"date": "2026-10-11", "ctl": 69.0},  # peak long run (nominal first taper day)
        {"date": "2026-10-12", "ctl": 68.3},
        {"date": "2026-10-16", "ctl": 66.0},
        {"date": "2026-10-20", "ctl": 64.2},
    ]

    def test_marathon_inside_three_week_taper_needs_no_ramp(self):
        # The reported case: Sub-4 marathon, 2.9w out (20 days).
        profile = {"training_goal": "Sub-4:00 Marathon", "timeline": "2026-11-01"}
        result = evaluate_goal_trajectory(
            profile, current_ctl=68.3, today_date=date(2026, 10, 12), daily_pmc=self.TAPER_PMC
        )
        assert result["weeks_remaining"] == 2.9
        assert result["phase"] == "taper"
        assert result["required_ramp_rate"] is None
        assert result["pre_taper_ctl"] == 69.0  # includes the Sunday long run

    def test_peak_ctl_stays_static_through_the_taper(self):
        profile = {"training_goal": "Sub-4:00 Marathon", "timeline": "2026-11-01"}
        result = evaluate_goal_trajectory(
            profile, current_ctl=64.2, today_date=date(2026, 10, 20), daily_pmc=self.TAPER_PMC
        )
        assert result["phase"] == "taper"
        assert result["pre_taper_ctl"] == 69.0

    def test_pre_taper_ctl_ignores_peaks_long_before_the_taper(self):
        profile = {"training_goal": "Sub-4:00 Marathon", "timeline": "2026-11-01"}
        pmc = [{"date": "2026-09-01", "ctl": 80.0}, *self.TAPER_PMC]
        result = evaluate_goal_trajectory(
            profile, current_ctl=68.3, today_date=date(2026, 10, 12), daily_pmc=pmc
        )
        assert result["pre_taper_ctl"] == 69.0

    def test_pre_taper_ctl_falls_back_to_current_without_history(self):
        profile = {"training_goal": "Sub-4:00 Marathon", "timeline": "2026-11-01"}
        result = evaluate_goal_trajectory(profile, current_ctl=66.6, today_date=date(2026, 10, 12))
        assert result["pre_taper_ctl"] == 66.6

    def test_short_build_window_is_floored_to_one_week(self):
        # Half marathon 2.9w out -> 0.9 build weeks; 3.4 CTL gap reads +3.4/wk, not +3.78.
        profile = {"training_goal": "Sub-1:35 Half Marathon", "timeline": "2026-11-01"}
        result = evaluate_goal_trajectory(profile, current_ctl=64.6, today_date=date(2026, 10, 12))
        assert result["phase"] == "build"
        assert result["build_weeks"] == 0.9
        assert result["required_ramp_rate"] == 3.4

    def test_profile_taper_override_is_used(self):
        profile = {"training_goal": "Sub-4:00 Marathon", "timeline": "2026-11-01", "taper_weeks": 2}
        result = evaluate_goal_trajectory(profile, current_ctl=66.6, today_date=date(2026, 10, 12))
        assert result["taper_weeks"] == 2.0
        assert result["phase"] == "build"

    def test_missing_timeline_leaves_projections_unset(self):
        result = evaluate_goal_trajectory({"training_goal": "Marathon"}, current_ctl=50.0)
        assert result["weeks_remaining"] is None
        assert result["required_ramp_rate"] is None

    def test_unparseable_timeline_does_not_raise(self):
        profile = {"training_goal": "Marathon", "timeline": "next spring"}
        result = evaluate_goal_trajectory(profile, current_ctl=50.0, today_date=date(2026, 9, 15))
        assert result["weeks_remaining"] is None

    def test_no_goal_uses_default_peak(self):
        result = evaluate_goal_trajectory({}, current_ctl=50.0)
        assert result["target_peak_ctl"] == DEFAULT_PEAK_CTL
        assert "goal_name" not in result


class TestFreeTextTimeline:
    def test_month_name_timeline_drives_projections(self):
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "November 1st, 2026"}
        result = evaluate_goal_trajectory(profile, current_ctl=40.0, today_date=date(2026, 9, 25))
        assert result["weeks_remaining"] == 5.3  # 37 days
        assert result["required_ramp_rate"] is not None
