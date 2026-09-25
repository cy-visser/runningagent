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
            {"type": "completed"},
            {"distance_actual_km": 10.5},
            {"tss_actual": 62},
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


# Regression: TrainingPeaks sends '--' as a "no value" placeholder (e.g. VAM/Grade
# on a session without GPS), which used to crash analyze_workout.
from running_coach.utils.workouts import format_workout_analysis  # noqa: E402

NO_GPS_ANALYSIS = {
    "workoutId": 3937515897,
    "totals": {
        "Elapsed time": {"value": 1801, "unit": "h:m:s"},
        "Duration": {"value": 1800, "unit": "h:m:s"},
        "Moving time": {"value": 0, "unit": "h:m:s"},
        "Distance": {"value": 0, "unit": "km"},
        "hrTSS": {"value": 18, "unit": None},
        "El. Gain": {"value": 0, "unit": "m"},
        "El. Loss": {"value": 0, "unit": "m"},
        "VAM": {"value": "--", "unit": "m/h"},
        "Grade": {"value": "--", "unit": "%"},
    },
    "dataChannels": [
        {"identifier": "HeartRate", "name": "Heart Rate", "unit": "bpm", "min": 53.0, "max": 101.0, "average": 80.0},
    ],
    "lapData": [
        {"Name": "Lap 1", "TotalElapsedTime": 1801, "TotalTimerTime": 1801, "AverageHeartRate": 80,
         "MaximumHeartRate": 101, "AverageCadence": 0},
    ],
}


class TestFormatWorkoutAnalysisPlaceholders:
    def test_no_gps_session_formats_without_error(self):
        out = format_workout_analysis(NO_GPS_ANALYSIS, title="Strength", sport="Strength")
        assert "hrTSS: 18.0" in out
        assert "Duration: 30m" in out
        assert "VAM" not in out
        assert "Grade" not in out
        assert "--" not in out
        assert "- Lap 1:" in out

    @pytest.mark.parametrize(
        "key", ["rTSS", "TSS", "hrTSS", "rIF", "IF", "NP", "Energy", "Pa:Hr", "EF", "Duration", "El. Gain"]
    )
    def test_placeholder_totals_are_omitted(self, key):
        out = format_workout_analysis({"totals": {key: {"value": "--", "unit": None}}})
        assert "--" not in out

    @pytest.mark.parametrize(
        "field",
        ["TotalTimerTime", "TotalAscent", "AverageGrade", "AverageVam", "AveragePower",
         "AverageCadence", "AverageHeartRate", "PacePulseDecoupling", "AverageStanceTime"],
    )
    def test_placeholder_lap_fields_are_omitted(self, field):
        out = format_workout_analysis({"lapData": [{"Name": "Lap 1", field: "--"}]}, sport="Run")
        assert "- Lap 1:" in out
        assert "--" not in out

    def test_numeric_strings_still_render(self):
        out = format_workout_analysis({"totals": {"VAM": {"value": "412.4", "unit": "m/h"}, "TSS": "55"}})
        assert "VAM: 412m/h" in out
        assert "TSS: 55.0" in out


# Primary-session selection: the 2026-09-24 run + S&C day, where the old
# `completed[-1]` pick analysed the 30-min strength session instead of the run.
from running_coach.utils.workouts import format_other_sessions, select_primary_workout  # noqa: E402

CANOVA = {"id": "3681731889", "date": "2026-09-24", "start_time": "2026-09-24T07:26:05",
          "title": "Canova 8x1km Alternating (4:55 / 5:20)", "type": "completed", "sport": "Run",
          "duration_actual": 1.17, "distance_actual_km": 12.9, "tss_actual": 101.83}
SNC = {"id": "3937515897", "date": "2026-09-24", "start_time": "2026-09-24T17:36:12",
       "title": "General S&C Work", "type": "completed", "sport": "Strength",
       "duration_actual": 0.5, "tss_actual": 17.9}


class TestSelectPrimaryWorkout:
    @pytest.mark.parametrize("order", [[CANOVA, SNC], [SNC, CANOVA]])
    def test_run_beats_later_strength_session(self, order):
        primary, others = select_primary_workout(order)
        assert primary["id"] == "3681731889"
        assert [w["id"] for w in others] == ["3937515897"]

    def test_two_runs_highest_tss_wins(self):
        easy = {"id": "am", "sport": "Run", "tss_actual": 40, "start_time": "2026-09-24T07:00:00"}
        workout = {"id": "pm", "sport": "Run", "tss_actual": 85, "start_time": "2026-09-24T18:00:00"}
        assert select_primary_workout([workout, easy])[0]["id"] == "pm"

    def test_equal_load_prefers_latest_start(self):
        a = {"id": "a", "sport": "Run", "tss_actual": 50, "start_time": "2026-09-24T07:00:00"}
        b = {"id": "b", "sport": "Run", "tss_actual": 50, "start_time": "2026-09-24T18:00:00"}
        assert select_primary_workout([a, b])[0]["id"] == "b"

    def test_bike_hint_picks_ride_over_run(self):
        ride = {"id": "ride", "sport": "Bike", "tss_actual": 60}
        assert select_primary_workout([CANOVA, ride], sport="bike")[0]["id"] == "ride"

    def test_bike_hint_falls_back_when_no_ride(self):
        assert select_primary_workout([CANOVA, SNC], sport="bike")[0]["id"] == "3681731889"

    def test_strength_beats_non_training(self):
        other = {"id": "o", "sport": "Other", "tss_actual": 30}
        assert select_primary_workout([other, SNC])[0]["id"] == "3937515897"

    def test_other_endurance_beats_strength(self):
        swim = {"id": "swim", "sport": "Swim", "tss_actual": 10}
        assert select_primary_workout([SNC, swim])[0]["id"] == "swim"

    def test_placeholder_tss_does_not_crash(self):
        a = {"id": "a", "sport": "Run", "tss_actual": "--"}
        b = {"id": "b", "sport": "Run", "tss_actual": 20}
        assert select_primary_workout([a, b])[0]["id"] == "b"

    def test_single_and_empty(self):
        assert select_primary_workout([CANOVA]) == (CANOVA, [])
        assert select_primary_workout([]) == (None, [])


class TestFormatOtherSessions:
    def test_renders_title_sport_minutes_tss_and_id(self):
        out = format_other_sessions([SNC], "2026-09-24")
        assert out.startswith("Other completed sessions on 2026-09-24")
        assert "'General S&C Work' (Strength, 30 min, TSS 17.9, id 3937515897)" in out
        assert "analyze_workout(workout_id=...)" in out

    def test_empty_returns_blank(self):
        assert format_other_sessions([], "2026-09-24") == ""
