"""Evidence-based race readiness model (utils.race_readiness)."""

import json
from datetime import date, timedelta

import pytest

from running_coach.utils.race_readiness import MAX_RACE_DAY_GAIN, project_race, summarize_analysis

TODAY = date(2026, 9, 24)
THRESHOLDS = {"lthr": 172.0, "threshold_speed": 3.4483}
THRESHOLD_WORKOUT = {"id": 3908039985, "date": "2026-09-10", "title": "Threshold 2 x 15'", "sport": "Run",
                     "distance_actual_km": 12.5, "duration_actual": 1.05}
LONG_WORKOUT = {"id": 3681731887, "date": "2026-09-20", "title": "28km (18k Easy + 8k @ MP 5:22)", "sport": "Run",
                "distance_actual_km": 28.0, "duration_actual": 2.68}
ZONE2_HM_WORKOUT = {"id": 111, "date": "2026-08-30", "title": "Long run Z2", "sport": "Run",
                    "distance_actual_km": 21.1, "duration_actual": 2 + 8 / 60}


def _lap(dur, km, pace, hr, dec=None, ngp=None):
    out = {"TotalTimerTime": dur, "TotalDistance": km, "AveragePace": pace, "AverageHeartRate": hr}
    if dec is not None:
        out["PacePulseDecoupling"] = dec
    if ngp is not None:
        out["NormalizedGradedPace"] = ngp
    return out


def _envelope(laps, pa_hr):
    return {"content": [{"type": "text", "text": json.dumps({"totals": {"Pa:Hr": {"value": pa_hr}}, "lapData": laps})}]}


def test_marathon_projection_uses_quality_and_mp_evidence_with_capped_race_day_gain():
    summaries = [
        summarize_analysis(_envelope([
            _lap(900, 2.5, 360, 135), _lap(870, 3.0, 290, 154), _lap(180, 0.45, 400, 140),
            _lap(870, 3.0, 290, 162), _lap(600, 1.6, 375, 138),
        ], 10.44), THRESHOLD_WORKOUT),
        summarize_analysis(_envelope([
            _lap(6400, 18.0, 356, 136, dec=5.93),
            _lap(2559, 8.0, 320, 155, dec=4.77, ngp=331),
            _lap(684, 2.0, 342, 158),
        ], 5.27), LONG_WORKOUT),
    ]
    health = {k: [(TODAY - timedelta(days=i), v) for i in range(28)] for k, v in (("hrv", 60), ("rhr", 48), ("sleep", 7.5))}
    p = project_race(
        goal_label="Marathon", goal_minutes=225,
        runs=[LONG_WORKOUT, THRESHOLD_WORKOUT, ZONE2_HM_WORKOUT], summaries=summaries,
        thresholds=THRESHOLDS, daily_pmc=[{"date": "2026-09-01", "ctl": 60.0}],
        fitness={"ctl_end": 62.0, "atl_end": 66.0, "tsb_end": -4.0},
        trajectory_info={"weeks_remaining": 5.5, "build_weeks": 3.5, "target_peak_ctl": 75.0},
        dated_metrics=health, today=TODAY,
    )
    naive_z2_s = (2 * 3600 + 8 * 60) * 2 ** 1.06
    assert 3 * 3600 + 35 * 60 < p["today_s"] < naive_z2_s - 20 * 60
    assert p["today_s"] * (1 - MAX_RACE_DAY_GAIN) - 1 <= p["race_day_s"] < p["today_s"]
    assert p["gap_s"] == pytest.approx(p["race_day_s"] - 225 * 60)


def test_no_evidence_returns_none():
    assert project_race("Marathon", 225, [], [], {"lthr": None, "threshold_speed": None},
                        None, {"ctl_end": 50.0, "atl_end": 50.0, "tsb_end": 0.0}, None, None, TODAY) is None
