import asyncio
from datetime import date

import pytest

from running_coach import tools
from running_coach.tools import (
    _build_goal_projection,
    _location_args,
    _result_or_none,
    _summarize_fitness,
)
from running_coach.utils.weekly import new_week_bucket as _new_week_bucket
from running_coach.utils.weekly import tally_workout as _tally_workout
from running_coach.utils.metrics import parse_mcp_response  # noqa: F401  (import sanity)
from running_coach.utils.race_readiness import ANALYSIS_SCHEMA_VERSION
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

    def test_window_start_limits_bounds_but_keeps_history(self):
        payload = mcp_envelope({"daily_data": [
            {"date": "2026-07-01", "ctl": 70.0},
            {"date": "2026-09-01", "ctl": 40.0},
            {"date": "2026-09-15", "ctl": 50.0},
        ]})
        result = _summarize_fitness(payload, {}, date(2026, 9, 15), window_start=date(2026, 9, 1))
        assert (result["ctl_start"], result["ctl_end"]) == (40.0, 50.0)
        assert len(result["daily_list"]) == 2
        assert len(result["history"]) == 3


class TestBuildGoalProjection:
    def test_no_goal_distance_yields_empty_projection(self):
        out = asyncio.run(_build_goal_projection(None, None, {}, [], None, None, None, date(2026, 9, 24)))
        assert out == {"goal_label": None, "projection": None}


def _analysis(laps):
    return mcp_envelope({"totals": {"Pa:Hr": {"value": 4.0, "unit": "%"}}, "lapData": laps})


class TestLoadWorkoutSummaries:
    WORKOUTS = [
        {"id": 1, "date": "2026-09-10", "title": "Threshold 2x15", "distance_actual_km": 3.1},
        {"id": 2, "date": "2026-09-20", "title": "28km long", "distance_actual_km": 3.0},
    ]
    LAP = {"TotalTimerTime": 900, "TotalDistance": 3.1, "AveragePace": 290, "AverageHeartRate": 160}
    CACHED_LAPS = [{"distance_km": 3.1, "duration_s": 900, "speed_ms": 3.4, "hr": 160}]

    def _patch(self, monkeypatch, cache, analysed, fail_cache=False):
        async def fake_read(user_id, wid):
            if fail_cache:
                raise RuntimeError("firestore down")
            return cache.get(wid)

        async def fake_write(user_id, wid, summary):
            if fail_cache:
                raise RuntimeError("firestore down")
            cache[wid] = summary

        async def fake_tp(ctx, name, **kw):
            analysed.append(kw["workout_id"])
            return _analysis([self.LAP])

        monkeypatch.setattr(tools, "get_cached_workout_analysis", fake_read)
        monkeypatch.setattr(tools, "save_workout_analysis", fake_write)
        monkeypatch.setattr(tools, "_run_tp_tool", fake_tp)

    def test_analyses_misses_and_populates_cache(self, monkeypatch):
        cache, analysed = {}, []
        self._patch(monkeypatch, cache, analysed)
        out = asyncio.run(tools._load_workout_summaries(None, self.WORKOUTS, "user_x"))
        assert analysed == ["1", "2"]
        assert set(cache) == {"1", "2"}
        assert len(out) == 2 and out[0]["laps"][0]["hr"] == 160

    def test_uses_cache_hits_and_ignores_old_schema(self, monkeypatch):
        cache = {
            "1": {"version": ANALYSIS_SCHEMA_VERSION, "workout_id": "1", "distance_km": 3.1,
                  "laps": self.CACHED_LAPS, "date": "2026-09-10"},
            "2": {"version": ANALYSIS_SCHEMA_VERSION - 1, "workout_id": "2", "laps": self.CACHED_LAPS},
        }
        analysed = []
        self._patch(monkeypatch, cache, analysed)
        out = asyncio.run(tools._load_workout_summaries(None, self.WORKOUTS, "user_x"))
        assert analysed == ["2"]
        assert cache["2"]["version"] == ANALYSIS_SCHEMA_VERSION
        assert len(out) == 2

    def test_partially_synced_workout_is_used_but_not_cached(self, monkeypatch):
        cache, analysed = {}, []
        self._patch(monkeypatch, cache, analysed)
        partial = [{"id": 9, "date": "2026-09-24", "title": "Canova 8x1km", "distance_actual_km": 12.9}]
        out = asyncio.run(tools._load_workout_summaries(None, partial, "user_x"))
        assert len(out) == 1 and cache == {}
        # A stale partial entry already in the cache is treated as a miss.
        cache["9"] = out[0]
        asyncio.run(tools._load_workout_summaries(None, partial, "user_x"))
        assert analysed == ["9", "9"]

    def test_refresh_bypasses_cache(self, monkeypatch):
        cache = {"1": {"version": ANALYSIS_SCHEMA_VERSION, "laps": self.CACHED_LAPS}}
        analysed = []
        self._patch(monkeypatch, cache, analysed)
        asyncio.run(tools._load_workout_summaries(None, self.WORKOUTS[:1], "user_x", refresh=True))
        assert analysed == ["1"]

    def test_firestore_failure_falls_back_to_analysis(self, monkeypatch):
        analysed = []
        self._patch(monkeypatch, {}, analysed, fail_cache=True)
        out = asyncio.run(tools._load_workout_summaries(None, self.WORKOUTS, "user_x"))
        assert analysed == ["1", "2"]
        assert len(out) == 2


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
