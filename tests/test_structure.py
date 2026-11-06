"""Structured workout flattening, lap alignment, execution table and series decoupling."""

import json
import pathlib

from running_coach.utils.structure import (
    align_laps,
    decoupling,
    flatten_structure,
    format_structured_execution,
    sport_thresholds,
)

FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "structured_workouts.json").read_text())
CANOVA, SETTINGS = FX["canova"], FX["settings"]


def test_canova_alignment_and_formatted_execution():
    steps = flatten_structure(CANOVA["structured_workout"])
    alignment = align_laps(steps, CANOVA["laps"])
    assert len(steps) == 18 and [l["Name"] for l in alignment.extra_laps] == ["Lap 19"]
    out = format_structured_execution(
        CANOVA["structured_workout"], CANOVA["laps"], sport_thresholds(SETTINGS, "Run"),
        CANOVA["series"], "Run", alignment,
    )
    assert "| B3 Hard 1/4 | 1.00 km | 5:05–5:15/km | 4:55/km |" in out
    assert "Extra lap (not in plan): Lap 19" in out


def test_series_decoupling():
    pts = [{"time": t, "HeartRate": 140.0 if t < 1800 else 140.0 / 0.95, "Speed": 11.0} for t in range(0, 3600, 5)]
    assert decoupling(pts, 0, 3600, "Run") == 5.0
