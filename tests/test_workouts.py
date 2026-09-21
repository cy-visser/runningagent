from datetime import date

import pytest

from running_coach.utils.workouts import (
    is_workout_completed,
    partition_workouts_by_date,
)

REFERENCE = date(2026, 9, 15)


class TestIsWorkoutCompleted:
    @pytest.mark.parametrize(
        "workout",
        [
            {"completed": True},
            {"type": "completed"},
            {"distance_actual_km": 10.5},
            {"tss_actual": 62},
            {"duration_actual_min": 45},
            {"duration_actual": 1.2},
        ],
    )
    def test_detects_completed_sessions(self, workout):
        assert is_workout_completed(workout) is True

    @pytest.mark.parametrize(
        "workout",
        [
            {},
            {"completed": False},
            {"distance_planned_km": 10.0},
            {"distance_actual_km": 0},
            {"tss_actual": None},
        ],
    )
    def test_detects_planned_sessions(self, workout):
        assert is_workout_completed(workout) is False

    def test_handles_missing_workout(self):
        assert is_workout_completed(None) is False

    def test_tolerates_string_actuals_without_raising(self):
        """Raw MCP payloads occasionally deliver numbers as strings."""
        assert is_workout_completed({"distance_actual_km": "12.4"}) is True
        assert is_workout_completed({"distance_actual_km": "0"}) is False
        assert is_workout_completed({"distance_actual_km": "n/a"}) is False

    def test_ignores_boolean_actuals(self):
        assert is_workout_completed({"tss_actual": True}) is False


class TestPartitionWorkoutsByDate:
    def test_splits_on_the_reference_date(self):
        workouts = [
            {"date": "2026-09-10", "tss_actual": 50},
            {"date": "2026-09-20"},
        ]
        past, future = partition_workouts_by_date(workouts, REFERENCE)
        assert [w["date"] for w in past] == ["2026-09-10"]
        assert [w["date"] for w in future] == ["2026-09-20"]

    def test_todays_session_is_past_only_once_completed(self):
        completed_today = {"date": "2026-09-15", "tss_actual": 40}
        planned_today = {"date": "2026-09-15"}
        past, future = partition_workouts_by_date([completed_today, planned_today], REFERENCE)
        assert past == [completed_today]
        assert future == [planned_today]

    def test_skips_entries_without_a_usable_date(self):
        past, future = partition_workouts_by_date([{"title": "orphan"}], REFERENCE)
        assert past == []
        assert future is None

    def test_falls_back_to_start_time(self):
        past, _ = partition_workouts_by_date(
            [{"start_time": "2026-09-10T07:00:00", "tss_actual": 30}], REFERENCE
        )
        assert len(past) == 1

    def test_empty_input_returns_empty_past_and_no_future(self):
        assert partition_workouts_by_date([], REFERENCE) == ([], None)
        assert partition_workouts_by_date(None, REFERENCE) == ([], None)

    def test_future_is_none_when_nothing_is_upcoming(self):
        _, future = partition_workouts_by_date(
            [{"date": "2026-09-01", "tss_actual": 10}], REFERENCE
        )
        assert future is None
