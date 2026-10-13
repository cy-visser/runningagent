from datetime import date

import pytest

from running_coach.utils.trajectory import (
    TAPER_WEEKS,
    evaluate_goal_trajectory,
    parse_target_time_minutes,
    resolve_taper_weeks,
)


def _check(fn, cases):
    for arg, expected in cases:
        assert fn(arg) == expected, arg


def test_resolve_taper_weeks():
    _check(resolve_taper_weeks, [
        ("100k ultra", 3.0), ("Sub-4:00 Marathon", 3.0), ("Sub-1:45 Half Marathon", 2.0),
        ("Sub-1:15 10 mile", 2.0), ("Sub-45 10K", 1.0), ("Sub-20 5K", 1.0),
        ("General fitness", TAPER_WEEKS), (None, TAPER_WEEKS),
    ])
    # Valid overrides win; invalid ones fall back to the distance default.
    for override, expected in [(2, 2.0), ("2.5", 2.5), (0, 0.0), ("three", 3.0), (-1, 3.0), ("", 3.0)]:
        assert resolve_taper_weeks("Sub-4:00 Marathon", override) == expected, override


def test_parse_target_time_minutes():
    for goal, expected in [
        ("Sub-3:30 Marathon", 210), ("3:00 Marathon", 180), ("Sub-4 hour marathon", 240),
        ("3 hours and 15 mins", 195), ("Sub-1:45 Half", 105), ("Sub-20 5K", 20), ("45 minutes 10K", 45),
        # mm:ss vs h:mm disambiguation
        ("Sub-19:30 5K", 19.5), ("40:00 10K", 40), ("3:15:00 Marathon", 195), ("Sub-1:05 10 mile", 65),
        (None, None), ("Just finish the race", None),
    ]:
        assert parse_target_time_minutes(goal) == pytest.approx(expected), goal


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

        # Already at target: no ramp needed.
        result = evaluate_goal_trajectory(profile, current_ctl=95.0, today_date=date(2026, 9, 15))
        assert result["required_ramp_rate"] == 0.0
