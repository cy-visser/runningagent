"""Target-time parsing and CTL goal trajectory."""

from datetime import date
import pytest

from running_coach.utils.trajectory import evaluate_goal_trajectory, parse_target_time_minutes


def test_parse_target_time_and_evaluate_goal_trajectory():
    for goal, expected in [
        ("Sub-3:30 Marathon", 210), ("Sub-19:30 5K", 19.5), ("Sub-20 5K", 20), ("Just finish", None),
    ]:
        assert parse_target_time_minutes(goal) == pytest.approx(expected)

    profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-12-08"}
    res = evaluate_goal_trajectory(profile, current_ctl=40.0, today_date=date(2026, 9, 15))
    assert (res["build_weeks"], res["taper_weeks"], res["required_ramp_rate"]) == (9.0, 3.0, 4.44)
