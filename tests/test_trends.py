"""Weekly rows, goal-specific key-run Pa:Hr, progress verdicts and training patterns (utils.trends)."""

from datetime import date, timedelta

from running_coach.utils.trends import key_run_decoupling, lt_paces, progress_summary, training_patterns, weekly_rows

MONDAY = date(2026, 9, 7)


def _run(day, km=10.0, kind="easy", ef=1.2, feels=12.0, comment=None, dec=None):
    return {"workout_id": f"{day}-{km}", "date": day.isoformat(), "sport": "Run", "kind": kind,
            "distance_km": km, "tss": 60.0, "ef": ef, "session_decoupling": dec,
            "weather": {"feels_like_c": feels}, "athlete": {"rpe": None, "comment": comment}}


def _step(pct, minutes, dec):
    return {"target": {"metric": "percentOfThresholdPace", "lo": pct - 2, "hi": pct + 2},
            "duration_s": minutes * 60.0, "decoupling": dec}


def test_weekly_rows_completeness_heat_and_lt_paces():
    laps = [{"hr": hr, "speed_ms": 3.0 + 0.02 * (hr - 130), "duration_s": 600.0} for hr in (130, 140, 150, 160, 165)]
    recs = [
        {**_run(MONDAY, 10, ef=1.30), "laps": laps},
        _run(MONDAY + timedelta(days=1), 10, ef=1.10, feels=26, comment="Left calf tight"),
        _run(MONDAY + timedelta(days=6), 25, kind="long", dec=4.0),
    ]
    rows = weekly_rows(recs, [], {}, MONDAY, MONDAY + timedelta(days=13),
                       unrecorded_dates=[(MONDAY + timedelta(days=8)).isoformat()], lthr=170.0, lt1_hr=150.0)
    w0, w1 = rows
    assert w0["complete"] and w0["km"] == 45 and w0["long_km"] == 25 and w0["easy_ef"] == 1.30 and w0["niggle"]
    assert not w1["complete"] and w1["unrecorded"] == 1
    out = lt_paces(recs[:1], MONDAY + timedelta(days=6), 170.0, 150.0)
    assert round(out["lt1_pace_s"], 1) == round(1000 / 3.4, 1) and out["lt2_extrapolated"]


def test_key_run_decoupling_follows_goal_distance():
    thr = {**_run(MONDAY, kind="quality", dec=9.0),
           "work_intervals": [_step(97, 15, 2.0), _step(97, 5, 6.0), _step(110, 3, 12.0)]}
    assert key_run_decoupling(thr, "5K") == 3.0
    assert key_run_decoupling(_run(MONDAY, 22, kind="long", dec=4.0), "5K") is None
    mp = {**_run(MONDAY, 30, kind="long", dec=7.0), "work_intervals": [_step(90, 20, 1.0), _step(90, 20, 3.0)]}
    assert key_run_decoupling(mp, "Marathon") == 2.0
    assert key_run_decoupling(thr, "Marathon") is None


def test_progress_verdict_direction_and_relative_pattern_split():
    rows = [{"week": MONDAY + timedelta(weeks=i), "complete": True, "runs": 5, "quality": 2 if i % 2 else 1,
             "ctl": 40.0 + 2 * i, "km": 60.0, "long_km": 20.0 if i % 2 else 15.0,
             "key_decoupling": 2.0 + 0.5 * i, "lt1_pace_s": 300.0 - 2 * i,
             "hrv": None, "rhr": None, "sleep_h": None, "easy_ef": 1.0 + 0.01 * i,
             "hrv_delta_pct": 0.0, "rpe": None} for i in range(10)]
    out = {p["key"]: p for p in progress_summary(rows, "5K")}
    assert out["ctl"]["verdict"] == "🟢 improving"
    assert out["key_decoupling"]["arrow"] == "↑" and out["key_decoupling"]["verdict"] == "🔴 declining"
    assert out["lt1_pace_s"]["arrow"] == "↓" and out["lt1_pace_s"]["verdict"] == "🟢 improving"

    patterns = training_patterns(rows)
    assert patterns[1]["a"] == "Long run >= 30% of week km"
    assert patterns[1]["a_out"]["n"] == 4 and patterns[1]["b_out"]["n"] == 5
