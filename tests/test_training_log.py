"""Training-log record builder (utils.training_log), using the real Canova fixture."""

import json
import pathlib
from datetime import datetime

from running_coach.utils.training_log import WorkoutBundle, build_training_record

CANOVA = json.loads((pathlib.Path(__file__).parent / "fixtures" / "structured_workouts.json").read_text())["canova"]
NOW = datetime(2026, 9, 25, 8, 0, 0)
THRESHOLDS = {"lthr": 172.0, "threshold_speed": 3.509}
CONTEXT = {"ctl": 60.0, "atl": 70.0, "tsb": -10.0, "hrv": 42.0, "rhr": 51.0, "sleep_h": 8.1}


def _meta(sport="Run", structured=True):
    laps = CANOVA["laps"]
    return {
        "id": "3681731889", "date": "2026-09-24", "title": "Tuesday session", "sport": sport,
        "rpe": 6, "feeling": 7, "new_comment": "calf a bit tight",
        "metrics": {"duration_actual": sum(lap["TotalTimerTime"] for lap in laps) / 3600,
                    "distance_actual_km": sum(lap["TotalDistance"] for lap in laps),
                    "tss_actual": 110.0, "if_actual": 0.86,
                    "duration_planned": 3.3, "distance_planned_km": 20.0, "tss_planned": 115.0},
        "structured_workout": CANOVA["structured_workout"] if structured else None,
    }


def _analysis(laps=None):
    return {"lapData": CANOVA["laps"] if laps is None else laps,
            "totals": {"Avg heart rate": {"value": 140}, "NGP": {"value": 5.0, "unit": "min/km"},
                       "Pa:Hr": {"value": CANOVA["tp_pa_hr"]}}}


def test_structured_run_builds_complete_record_with_intervals():
    b = WorkoutBundle(meta=_meta(), analysis=_analysis(), series=CANOVA["series"],
                      thresholds=THRESHOLDS, weather={"feels_like_c": 14.0}, context=CONTEXT)
    r = build_training_record(b, NOW)
    assert r["kind"] == "quality" and r["tss"] == 110.0 and r["pa_hr"] == CANOVA["tp_pa_hr"]
    assert isinstance(r["session_decoupling"], float) and len(r["laps"]) == len(CANOVA["laps"])
    reps = [iv for iv in r["work_intervals"] if iv["target"]["lo"] == 92]
    assert len(reps) == 4 and all(iv["step"].startswith("B3 Hard") for iv in reps)


def test_incomplete_runs_rejected_and_non_runs_get_light_records():
    assert build_training_record(WorkoutBundle(_meta(), _analysis(CANOVA["laps"][:3]), None, THRESHOLDS, None, CONTEXT), NOW) is None
    assert build_training_record(WorkoutBundle(_meta(), None, None, THRESHOLDS, None, CONTEXT), NOW) is None
    ride = build_training_record(WorkoutBundle(_meta(sport="Bike", structured=False), None, None, THRESHOLDS, None, CONTEXT), NOW)
    assert ride["sport"] == "Bike" and ride["kind"] is None and "laps" not in ride
