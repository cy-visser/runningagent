"""Tests for the evidence-based race readiness model.

Fixtures mirror the runner's real TrainingPeaks sessions:
- Sep 10 threshold session: 2 x 14.5' @ 4:50/km, HR 154 / 162 (LTHR 172)
- Sep 20 long run '28km (18k Easy + 8k @ MP 5:22)': 18 km @ 5:56 HR 136,
  8 km @ 5:20 (NGP 5:31) HR 155 Pa:Hr 4.77%, 2 km @ 5:42 HR 158
"""

from datetime import date, timedelta

import pytest

from running_coach.utils.metrics import extract_health_metrics_dated
from running_coach.utils.race_readiness import (
    ANALYSIS_SCHEMA_VERSION,
    MAX_RACE_DAY_GAIN,
    classify_run,
    extract_thresholds,
    project_race,
    summarize_analysis,
)
from tests.test_metrics import mcp_envelope

LTHR = 172.0
TP_SPEED = 3.4483  # 4:50/km
THRESHOLDS = {"lthr": LTHR, "threshold_speed": TP_SPEED}
TODAY = date(2026, 9, 24)
MARATHON_GOAL_MIN = 225  # 3:45


def _lap(dur, km, pace, hr, dec=None, ngp=None):
    lap = {"TotalTimerTime": dur, "TotalDistance": km, "AveragePace": pace, "AverageHeartRate": hr}
    if dec is not None:
        lap["PacePulseDecoupling"] = dec
    if ngp is not None:
        lap["NormalizedGradedPace"] = ngp
    return lap


def _analysis(laps, pa_hr=None):
    totals = {"Pa:Hr": {"value": pa_hr, "unit": "%"}} if pa_hr is not None else {}
    return mcp_envelope({"totals": totals, "lapData": laps})


THRESHOLD_WORKOUT = {
    "id": 3908039985, "date": "2026-09-10", "title": "Threshold 2 x 15'", "sport": "Run",
    "distance_actual_km": 12.5, "duration_actual": 1.05,
}
LONG_WORKOUT = {
    "id": 3681731887, "date": "2026-09-20", "title": "28km (18k Easy + 8k @ MP 5:22)", "sport": "Run",
    "distance_actual_km": 28.0, "duration_actual": 2.68,
}
ZONE2_HM_WORKOUT = {
    "id": 111, "date": "2026-08-30", "title": "Long run Z2", "sport": "Run",
    "distance_actual_km": 21.1, "duration_actual": 2 + 8 / 60,  # 2:08
}

THRESHOLD_LAPS = [
    _lap(900, 2.5, 360, 135),
    _lap(870, 3.0, 290, 154),
    _lap(180, 0.45, 400, 140),
    _lap(870, 3.0, 290, 162),
    _lap(600, 1.6, 375, 138),
]
LONG_LAPS = [
    _lap(6400, 18.0, 356, 136, dec=5.93),
    _lap(2559, 8.0, 320, 155, dec=4.77, ngp=331),
    _lap(684, 2.0, 342, 158),
]


@pytest.fixture
def summaries():
    return [
        summarize_analysis(_analysis(THRESHOLD_LAPS, pa_hr=10.44), THRESHOLD_WORKOUT),
        summarize_analysis(_analysis(LONG_LAPS, pa_hr=5.27), LONG_WORKOUT),
    ]


def _trajectory(weeks=5.5, build=3.5, target=75.0):
    return {"weeks_remaining": weeks, "build_weeks": build, "target_peak_ctl": target}


def _fitness(ctl=62.0, atl=66.0, tsb=-4.0):
    return {"ctl_end": ctl, "atl_end": atl, "tsb_end": tsb}


def _health(recent, base, today=TODAY):
    """recent/base: dicts of hrv/rhr/sleep values for days 0-4 and 5-27 before today."""
    out = {"hrv": [], "rhr": [], "sleep": []}
    for i in range(28):
        src = recent if i < 5 else base
        for k, v in src.items():
            out[k].append((today - timedelta(days=i), v))
    return out


GOOD_HEALTH = _health({"hrv": 60, "rhr": 48, "sleep": 7.5}, {"hrv": 60, "rhr": 48, "sleep": 7.5})


class TestExtractThresholds:
    def test_prefers_run_hr_zones_and_falls_back_to_default_speed(self):
        raw = mcp_envelope({"settings": {
            "heartRateZones": [{"workoutTypeId": 0, "threshold": 180}, {"workoutTypeId": 3, "threshold": 172}],
            "speedZones": [{"workoutTypeId": 0, "threshold": 3.4483}],
        }})
        assert extract_thresholds(raw) == {"lthr": 172, "threshold_speed": 3.4483}


class TestClassifyRun:
    @pytest.mark.parametrize("workout, expected", [
        ({"title": "Dam tot Damloop race", "distance_actual_km": 16}, "race"),
        (LONG_WORKOUT, "long"),
        (THRESHOLD_WORKOUT, "quality"),
        ({"title": "Easy recovery", "distance_actual_km": 8}, "easy"),
    ])
    def test_marathon_classification(self, workout, expected):
        assert classify_run(workout, "Marathon") == expected


class TestSummarizeAnalysis:
    def test_compacts_laps_and_uses_ngp_for_speed(self, summaries):
        long_s = summaries[1]
        assert long_s["version"] == ANALYSIS_SCHEMA_VERSION
        assert long_s["workout_id"] == "3681731887"
        assert long_s["date"] == "2026-09-20"
        assert long_s["pa_hr"] == 5.27
        mp = long_s["laps"][1]
        assert mp["start_km"] == 18.0
        assert mp["pace_s"] == 320
        assert mp["speed_ms"] == pytest.approx(1000 / 331, abs=1e-3)  # NGP


class TestProjectRace:
    def _project(self, summaries, **kw):
        args = dict(
            goal_label="Marathon", goal_minutes=MARATHON_GOAL_MIN,
            runs=[LONG_WORKOUT, THRESHOLD_WORKOUT, ZONE2_HM_WORKOUT], summaries=summaries,
            thresholds=THRESHOLDS, daily_pmc=[{"date": "2026-09-01", "ctl": 60.0}],
            fitness=_fitness(), trajectory_info=_trajectory(), dated_metrics=GOOD_HEALTH, today=TODAY,
        )
        args.update(kw)
        return project_race(**args)

    def test_zone2_half_does_not_drive_the_marathon_projection(self, summaries):
        p = self._project(summaries)
        naive_s = (2 * 3600 + 8 * 60) * 2 ** 1.06  # ~4:27 from doubling the Z2 half
        assert p["today_s"] < naive_s - 20 * 60
        assert 3 * 3600 + 35 * 60 < p["today_s"] < 4 * 3600
        assert "race" not in p["signals"]

    def test_race_day_faster_than_today_but_capped(self, summaries):
        p = self._project(summaries)
        assert p["race_day_s"] < p["today_s"]
        assert p["race_day_s"] >= p["today_s"] * (1 - MAX_RACE_DAY_GAIN) - 1
        assert p["gap_s"] == pytest.approx(p["race_day_s"] - MARATHON_GOAL_MIN * 60)

    def test_no_evidence_returns_none(self):
        assert project_race("Marathon", 225, [], [], {"lthr": None, "threshold_speed": None},
                            None, _fitness(), None, None, TODAY) is None


class TestExtractHealthMetricsDated:
    def test_dates_from_timestamp(self):
        raw = mcp_envelope({"metrics": [
            {"timeStamp": "2026-09-20T07:00:00", "details": [{"type": 60, "value": 55}, {"type": 5, "value": 49}]},
            {"timeStamp": "2026-09-21T07:00:00", "details": [{"type": 6, "value": 7.2}, {"type": 99, "value": 1}]},
        ]})
        out = extract_health_metrics_dated(raw)
        assert out["hrv"] == [(date(2026, 9, 20), 55.0)]
        assert out["rhr"] == [(date(2026, 9, 20), 49.0)]
        assert out["sleep"] == [(date(2026, 9, 21), 7.2)]
