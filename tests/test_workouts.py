from datetime import date

from running_coach.utils.workouts import (
    format_workout_analysis,
    is_workout_completed,
    partition_workouts_by_date,
    select_primary_workout,
)

REFERENCE = date(2026, 9, 15)


class TestIsWorkoutCompleted:
    def test_detects_completed_sessions(self):
        for workout in ({"type": "completed"}, {"distance_actual_km": 10.5}, {"tss_actual": 62},
                        {"duration_actual": 1.2}, {"distance_actual_km": "12.4"}):
            assert is_workout_completed(workout) is True, workout


class TestPartitionWorkoutsByDate:
    def test_splits_on_the_reference_date(self):
        workouts = [
            {"date": "2026-09-10", "tss_actual": 50},
            {"date": "2026-09-20"},
        ]
        past, future = partition_workouts_by_date(workouts, REFERENCE)
        assert [w["date"] for w in past] == ["2026-09-10"]
        assert [w["date"] for w in future] == ["2026-09-20"]

# Session without GPS: TrainingPeaks sends '--' for VAM/Grade.
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


class TestFormatWorkoutAnalysis:
    def test_no_gps_session_formats_without_error(self):
        out = format_workout_analysis(NO_GPS_ANALYSIS, title="Strength", sport="Strength")
        assert "hrTSS: 18.0" in out
        assert "Duration: 30m" in out
        assert "VAM" not in out
        assert "Grade" not in out
        assert "--" not in out
        assert "- Lap 1:" in out

# Primary-session selection: a run and a later strength session on the same day.
CANOVA = {"id": "3681731889", "date": "2026-09-24", "start_time": "2026-09-24T07:26:05",
          "title": "Canova 8x1km Alternating (4:55 / 5:20)", "type": "completed", "sport": "Run",
          "duration_actual": 1.17, "distance_actual_km": 12.9, "tss_actual": 101.83}
SNC = {"id": "3937515897", "date": "2026-09-24", "start_time": "2026-09-24T17:36:12",
       "title": "General S&C Work", "type": "completed", "sport": "Strength",
       "duration_actual": 0.5, "tss_actual": 17.9}


class TestSelectPrimaryWorkout:
    def test_run_beats_later_strength_session(self):
        primary, others = select_primary_workout([CANOVA, SNC])
        assert primary["id"] == "3681731889"
        assert [w["id"] for w in others] == ["3937515897"]
