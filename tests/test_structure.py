"""Structure-aware analysis, using the real 2026-09-24 Canova (3681731889) and 2026-09-25
10 km easy run (3963243462) as fixtures: TP builder structure, device laps, time series."""
import json
import pathlib

import pytest

from running_coach.utils.structure import (
    align_laps,
    decoupling,
    flatten_structure,
    format_structured_execution,
    sport_thresholds,
)

FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "structured_workouts.json").read_text())
CANOVA, EASY, SETTINGS = FX["canova"], FX["easy_run"], FX["settings"]


@pytest.fixture
def thr():
    return sport_thresholds(SETTINGS, "Run")


@pytest.fixture
def steps():
    return flatten_structure(CANOVA["structured_workout"])


@pytest.fixture
def alignment(steps):
    return align_laps(steps, CANOVA["laps"])


# ---------------------------------------------------------------- structure & thresholds
class TestFlatten:
    def test_canova_expands_to_18_steps_in_4_blocks(self, steps):
        assert len(steps) == 18
        assert sorted({s.block for s in steps}) == [1, 2, 3, 4]
        assert [s.name for s in steps[:3]] == ["Warm up", "Hard", "Easy"]
        assert (steps[9].block, steps[9].rep, steps[9].length_m) == (3, 1, 1000.0)
        assert steps[0].intensity == "warmup" and steps[-1].intensity == "cooldown"
        assert flatten_structure(None) == []
        assert flatten_structure({"structure": []}) == []


# ---------------------------------------------------------------- alignment
class TestAlignLaps:
    def test_canova_laps_map_one_to_one_with_one_extra(self, alignment):
        assert alignment is not None
        assert [len(e.laps) for e in alignment.steps] == [1] * 18
        assert [l["Name"] for l in alignment.extra_laps] == ["Lap 19"]
        main = [e for e in alignment.steps if e.step.block == 3 and e.step.name == "Hard"]
        assert [round(e.hr_avg) for e in main] == [142, 151, 155, 159]


# ---------------------------------------------------------------- decoupling
def _synthetic_series(minutes=60, ef_drop=0.05):
    """Constant speed; HR rises in the second half so EF drops by exactly ef_drop."""
    pts = []
    for t in range(0, minutes * 60, 5):
        hr = 140.0 if t < minutes * 30 else 140.0 / (1 - ef_drop)
        pts.append({"time": t, "HeartRate": hr, "Speed": 11.0})
    return pts


class TestDecoupling:
    def test_known_ef_drop(self):
        assert decoupling(_synthetic_series(), 0, 3600, "Run") == 5.0


# ---------------------------------------------------------------- formatting
class TestFormatStructuredExecution:
    def test_canova_section(self, thr, alignment):
        out = format_structured_execution(CANOVA["structured_workout"], CANOVA["laps"], thr,
                                          CANOVA["series"], "Run", alignment)
        assert out.startswith("### Planned structure & execution (threshold pace 4:50/km, LTHR 172 bpm)")
        assert "| B3 Hard 1/4 | 1.00 km | 5:05–5:15/km | 4:55/km | 142/149 | 182 | fast (-10s/km) |" in out
        assert "| B1 Warm up | 15:00 | 6:02–6:54/km | 6:05/km | 120/127 | 176 | ✓ |" in out
        assert "Extra lap (not in plan): Lap 19" in out
        assert "Hard: pace 4:55, 4:55, 4:54, 4:53 (spread 2s) | HR 142 → 151 → 155 → 159 (+17 bpm first→last)" in out
        block = next(l for l in out.splitlines() if l.startswith("- B3 4× Hard/Easy: Pa:Hr"))
        assert float(block.rsplit(" ", 1)[1].rstrip("%")) == pytest.approx(5.9, abs=0.3)
        assert "whole session" not in out
