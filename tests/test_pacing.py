"""Pacing (utils.pacing): Zone-2 easy range, threshold reconciliation, headroom & LTHR qualification."""

import copy
from datetime import date

from running_coach.utils.pacing import analyse_pacing, easy_pace_range, hr_pace_model, threshold_estimate

TODAY = date(2026, 10, 27)
LTHR, TP_SPEED = 172.0, 3.509
ZONES = [{"label": "Zone 1", "min": 111, "max": 145}, {"label": "Zone 2", "min": 146, "max": 153}]
THR = {"lthr": LTHR, "threshold_speed": TP_SPEED}


def _lap(hr, speed, d=600):
    return {"hr": hr, "speed_ms": speed, "duration_s": d}


def _easy(day="2026-10-20", feels=10.0, laps=None):
    laps = laps or [_lap(hr, 2.5 + 0.02 * (hr - 130)) for hr in (120, 126, 132, 138, 144, 150)]
    return {"workout_id": f"e{day}", "date": day, "kind": "easy", "laps": laps, "pct_lthr": 0.76,
            "weather": {"feels_like_c": feels}, "thresholds": THR, "work_intervals": []}


def _session(wid, pace=296, pct=0.90, dec=2.0, hr=155):
    iv = {"target": {"metric": "percentOfThresholdPace", "lo": 95, "hi": 100},
          "pace_s": pace, "pct_lthr": pct, "decoupling": dec, "hr": hr, "duration_s": 600}
    return {"workout_id": wid, "date": "2026-10-15", "kind": "quality", "laps": [_lap(hr, 1000 / pace)] * 3,
            "weather": {}, "thresholds": THR, "work_intervals": [copy.deepcopy(iv) for _ in range(3)]}


def test_hr_pace_model_excludes_hot_runs_and_computes_zone2_range():
    hot = _easy(day="2026-10-21", feels=28.0, laps=[_lap(hr, 2.0) for hr in (120, 126, 132, 138, 144, 150)])
    model = hr_pace_model([_easy(), hot], LTHR)
    assert round(model["slope"], 4) == 0.02
    e = easy_pace_range(model, ZONES, LTHR)
    assert round(e["fast_s"]) == round(1000 / (2.5 + 0.02 * 23)) and not e["extrapolated"]


def test_threshold_reconciles_observation_against_tp():
    r = _session("t1", pace=1000 / 3.4)
    r["laps"] = [_lap(155, 3.4, 1200)]
    assert threshold_estimate([r], LTHR, TP_SPEED)["speed"] == 3.4
    r["laps"] = [_lap(155, 3.48, 1200)]
    assert threshold_estimate([r], LTHR, TP_SPEED)["speed"] == (3.48 + TP_SPEED) / 2


def test_headroom_qualified_until_sustained_lthr_effort_confirms_it():
    runs = [_session(f"s{i}") for i in range(3)] + [_easy()]
    unconfirmed = analyse_pacing(runs, THR, ZONES, TODAY)
    assert unconfirmed["lthr_check"]["status"] == "unconfirmed"
    assert unconfirmed["calibration"]["threshold"]["verdict"] == "room to go faster (LTHR unconfirmed)"

    tt = {"workout_id": "tt", "date": "2026-10-20", "title": "30-min TT", "kind": "quality",
          "laps": [_lap(130, 3.3)], "work_intervals": [{"hr": 168, "duration_s": 1800}],
          "weather": {}, "thresholds": THR}
    confirmed = analyse_pacing(runs + [tt], THR, ZONES, TODAY)
    assert confirmed["lthr_check"]["status"] == "confirmed"
    assert confirmed["calibration"]["threshold"]["verdict"] == "room to go faster"
