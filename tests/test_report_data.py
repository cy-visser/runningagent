"""JSON round-trip tests for structured web report payload builders."""

from datetime import date
import json

from running_coach.utils.report_data import checkin_report_data, trend_report_data


def test_checkin_report_data_json_roundtrip():
    payload = checkin_report_data(
        q_start=date(2026, 10, 22),
        q_end=date(2026, 11, 12),
        fitness_data={
            "ctl_end": 62.4,
            "atl_end": 68.1,
            "tsb_end": -5.7,
            "history": [{"date": "2026-11-05", "ctl": 62.4, "atl": 68.1, "tsb": -5.7}],
            "trajectory_info": {
                "target_peak_ctl": 80.0,
                "reference_range": [75.0, 90.0],
                "weeks_remaining": 12.0,
                "required_ramp_rate": 1.96,
                "phase": "build",
            },
        },
        race_projection={
            "goal_label": "Marathon",
            "projection": {
                "goal_label": "Marathon",
                "today_s": 12900,
                "race_day_s": 12480,
                "goal_s": 12600,
                "gap_s": -120,
                "range_s": (12360, 12960),
                "confidence": "High",
                "stale": False,
                "readiness": "🟢",
            },
        },
        weekly_totals=[
            {
                "start_date": date(2026, 10, 26),
                "date_range": "Oct 26 - Nov 01, 2026",
                "total_distance_km": 64.2,
                "total_tss": 342.0,
                "easy_count": 4,
                "quality_count": 2,
                "growth_pct": 6.5,
                "partial": True,
                "in_progress": True,
            }
        ],
        dated_metrics={"hrv": [(date(2026, 11, 5), 58.0)], "rhr": [(date(2026, 11, 5), 47.0)], "sleep": []},
    )
    decoded = json.loads(json.dumps(payload))
    assert decoded["version"] == 1
    assert decoded["ctl"]["ramp_tier"] == "safe"
    assert decoded["projection"]["gap_s"] == -120
    assert decoded["weeks"][0]["km"] == 64.2
    assert decoded["weeks"][0]["partial"] is True and decoded["weeks"][0]["in_progress"] is True


def test_trend_report_data_json_roundtrip():
    payload = trend_report_data(
        start=date(2026, 5, 4),
        today=date(2026, 11, 5),
        rows=[
            {
                "week": date(2026, 10, 26),
                "complete": True,
                "km": 64.2,
                "tss": 342.0,
                "runs": 6,
                "quality": 2,
                "long_km": 24.0,
                "ctl": 62.4,
                "tsb": -5.7,
                "hrv": 58.0,
                "hrv_delta_pct": 3.2,
                "rhr": 47.0,
                "rhr_delta": -1.0,
                "sleep_h": 7.6,
                "lt1_pace_s": 291.4,
                "lt2_pace_s": 238.6,
                "lt2_extrapolated": True,
                "key_decoupling": 2.84,
            }
        ],
        progress=[
            {
                "label": "CTL (fitness)",
                "first": "48.0",
                "latest": "62.4",
                "best": "62.4 (wk 2026-10-26)",
                "change": "+14.4",
                "arrow": "↑",
                "verdict": "🟢 improving",
            }
        ],
        levels=[
            {
                "level": 60,
                "weeks": 5,
                "streak": 4,
                "tolerated_share": 0.8,
                "hrv_delta_pct": 1.0,
                "rhr_delta": 0.0,
                "rpe": 5.5,
                "proven": True,
            }
        ],
        outlook={"proven_km": 60, "max_km": 66.0, "current_km": 62.1, "targets": [{"target": 60, "status": "proven", "build_weeks": 0}]},
        key_run_label="tempo/threshold",
    )
    decoded = json.loads(json.dumps(payload))
    assert decoded["version"] == 1
    assert decoded["outlook"]["proven_km"] == 60
    week = decoded["weeks"][0]
    assert week["lt1_pace_s"] == 291 and week["lt2_pace_s"] == 239 and week["lt2_extrapolated"] is True
    assert week["key_decoupling"] == 2.8 and "easy_ef" not in week
    assert decoded["key_run_label"] == "tempo/threshold"


