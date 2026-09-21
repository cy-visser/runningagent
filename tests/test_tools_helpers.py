from datetime import date

import pytest

from running_coach.tools import (
    _location_args,
    _new_week_bucket,
    _result_or_none,
    _summarize_fitness,
    _tally_workout,
)
from running_coach.utils.metrics import parse_mcp_response  # noqa: F401  (import sanity)
from tests.test_metrics import mcp_envelope


class TestLocationArgs:
    def test_uses_cached_coordinates(self):
        args = _location_args({"location": "Amsterdam", "latitude": 52.37, "longitude": 4.89})
        assert args == {"location": "Amsterdam", "lat": 52.37, "lon": 4.89}

    def test_allows_location_without_coordinates(self):
        args = _location_args({"location": "Amsterdam"})
        assert args["location"] == "Amsterdam"
        assert args["lat"] is None

    def test_allows_coordinates_without_location(self):
        args = _location_args({"latitude": 52.37, "longitude": 4.89})
        assert args["location"] == ""
        assert args["lat"] == 52.37

    @pytest.mark.parametrize("profile", [{}, {"location": ""}, {"latitude": 52.37}])
    def test_returns_none_when_ungeolocatable(self, profile):
        assert _location_args(profile) is None


class TestResultOrNone:
    def test_passes_through_successful_results(self):
        assert _result_or_none({"ok": True}, "workouts") == {"ok": True}

    def test_swallows_exceptions(self):
        assert _result_or_none(ValueError("mcp exploded"), "workouts") is None


class TestSummarizeFitness:
    def _fitness_payload(self):
        return mcp_envelope({"daily_data": [
            {"date": "2026-09-01", "ctl": 40.0, "atl": 45.0, "tsb": -5.0},
            {"date": "2026-09-15", "ctl": 50.0, "atl": 60.0, "tsb": -10.0},
        ]})

    def test_takes_first_and_last_values_in_date_order(self):
        result = _summarize_fitness(self._fitness_payload(), {}, date(2026, 9, 15))
        assert result["ctl_start"] == 40.0
        assert result["ctl_end"] == 50.0
        assert result["atl_end"] == 60.0
        assert result["tsb_end"] == -10.0

    def test_sorts_out_of_order_payloads(self):
        payload = mcp_envelope({"daily_data": [
            {"date": "2026-09-15", "ctl": 50.0},
            {"date": "2026-09-01", "ctl": 40.0},
        ]})
        result = _summarize_fitness(payload, {}, date(2026, 9, 15))
        assert (result["ctl_start"], result["ctl_end"]) == (40.0, 50.0)

    def test_attaches_goal_trajectory(self):
        profile = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-12-08"}
        result = _summarize_fitness(self._fitness_payload(), profile, date(2026, 9, 15))
        assert result["trajectory_info"]["target_peak_ctl"] == 80.0

    def test_empty_payload_yields_zeroed_metrics(self):
        result = _summarize_fitness(mcp_envelope({"daily_data": []}), {}, date(2026, 9, 15))
        assert result["ctl_end"] == 0.0
        assert result["daily_list"] == []

    def test_missing_payload_returns_none(self):
        assert _summarize_fitness(None, {}, date(2026, 9, 15)) is None


class TestTallyWorkout:
    def _bucket(self):
        return _new_week_bucket(date(2026, 9, 15))

    def test_new_bucket_spans_monday_to_sunday(self):
        bucket = self._bucket()
        assert bucket["start_date"] == date(2026, 9, 14)
        assert bucket["end_date"] == date(2026, 9, 20)

    def test_easy_run_counts_distance_and_easy_slot(self):
        bucket = self._bucket()
        _tally_workout(bucket, {"sport": "Run", "title": "Easy Aerobic", "distance_planned_km": 10.0, "tss_planned": 55}, date(2026, 9, 15))
        assert bucket["total_distance_km"] == 10.0
        assert bucket["total_tss"] == 55.0
        assert (bucket["easy_count"], bucket["quality_count"]) == (1, 0)

    @pytest.mark.parametrize(
        "title",
        ["Threshold Intervals", "Tempo Run", "Race Pace Block", "Hills Repeats", "Progression Long Run"],
    )
    def test_quality_keywords_classify_as_quality(self, title):
        bucket = self._bucket()
        _tally_workout(bucket, {"sport": "Run", "title": title}, date(2026, 9, 15))
        assert bucket["quality_count"] == 1

    def test_bike_and_strength_do_not_add_running_volume(self):
        bucket = self._bucket()
        _tally_workout(bucket, {"sport": "Bike", "distance_planned_km": 40.0, "tss_planned": 90}, date(2026, 9, 15))
        _tally_workout(bucket, {"sport": "Strength", "tss_planned": 20}, date(2026, 9, 16))
        assert bucket["total_distance_km"] == 0.0
        assert bucket["total_tss"] == 110.0
        assert (bucket["bike_count"], bucket["strength_count"]) == (1, 1)

    def test_unknown_sport_falls_into_other(self):
        bucket = self._bucket()
        _tally_workout(bucket, {"sport": "Swim"}, date(2026, 9, 15))
        assert bucket["other_sport_count"] == 1

    def test_records_a_session_line(self):
        bucket = self._bucket()
        _tally_workout(bucket, {"sport": "Run", "title": "Easy", "distance_planned_km": 8.0}, date(2026, 9, 15))
        assert "8.0km" in bucket["sessions"][0]
        assert "[Run] 'Easy'" in bucket["sessions"][0]
