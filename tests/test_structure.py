"""Structure-aware analysis, using the real 2026-09-24 Canova (3681731889) and 2026-09-25
10 km easy run (3963243462) as fixtures: TP builder structure, device laps, time series."""
import json
import pathlib

import pytest

from running_coach.utils.structure import (
    MIN_DECOUPLING_WINDOW_S,
    PA_HR_SKIP_S,
    PlannedStep,
    align_laps,
    decoupling,
    flatten_structure,
    format_structured_execution,
    format_target,
    lap_decoupling,
    pa_hr_window,
    series_end,
    session_decoupling,
    sport_thresholds,
    target_range,
)

FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "structured_workouts.json").read_text())
CANOVA, EASY, SETTINGS = FX["canova"], FX["easy_run"], FX["settings"]
PACE = "percentOfThresholdPace"


@pytest.fixture
def thr():
    return sport_thresholds(SETTINGS, "Run")


@pytest.fixture
def steps():
    return flatten_structure(CANOVA["structured_workout"])


@pytest.fixture
def alignment(steps):
    return align_laps(steps, CANOVA["laps"])


def _step(**kw):
    base = dict(block=1, block_reps=1, rep=1, pos=0, name="Step", intensity="active")
    return PlannedStep(**{**base, **kw})


# ---------------------------------------------------------------- structure & thresholds
class TestFlatten:
    def test_canova_expands_to_18_steps_in_4_blocks(self, steps):
        assert len(steps) == 18
        assert sorted({s.block for s in steps}) == [1, 2, 3, 4]
        assert [s.name for s in steps[:3]] == ["Warm up", "Hard", "Easy"]
        assert (steps[9].block, steps[9].rep, steps[9].length_m) == (3, 1, 1000.0)
        assert steps[0].intensity == "warmup" and steps[-1].intensity == "cooldown"

    def test_empty_or_missing_structure(self):
        assert flatten_structure(None) == []
        assert flatten_structure({"structure": []}) == []


class TestThresholds:
    def test_run_prefers_run_group_then_default(self, thr):
        assert thr["lthr"] == 172 and thr["ftp"] == 220
        assert round(1000 / thr["threshold_speed"]) == 290  # 4:50/km

    def test_bike_uses_bike_group(self):
        assert sport_thresholds(SETTINGS, "Bike")["ftp"] == 250


class TestTargets:
    @pytest.mark.parametrize("lo, hi, expected", [(92, 95, "5:05–5:15/km"), (105, 115, "4:12–4:36/km"), (70, 80, "6:02–6:54/km")])
    def test_percent_threshold_pace(self, thr, lo, hi, expected):
        assert format_target(_step(target_lo=lo, target_hi=hi), PACE, thr) == expected

    def test_percent_lthr_and_ftp(self, thr):
        assert target_range(_step(target_lo=80, target_hi=90), "percentOfThresholdHr", thr) == ("hr", 138, 155)
        assert format_target(_step(target_lo=88, target_hi=94), "percentOfFtp", {"ftp": 250}) == "220–235 W"

    def test_missing_threshold_falls_back_to_percent(self):
        assert format_target(_step(target_lo=92, target_hi=95), PACE, {}) == "92–95% thr pace"
        assert format_target(_step(), PACE, {}) == "no target"


# ---------------------------------------------------------------- alignment
class TestAlignLaps:
    def test_canova_laps_map_one_to_one_with_one_extra(self, alignment):
        assert alignment is not None
        assert [len(e.laps) for e in alignment.steps] == [1] * 18
        assert [l["Name"] for l in alignment.extra_laps] == ["Lap 19"]
        main = [e for e in alignment.steps if e.step.block == 3 and e.step.name == "Hard"]
        assert [round(e.hr_avg) for e in main] == [142, 151, 155, 159]

    def test_auto_laps_inside_a_10k_block(self):
        steps = [_step(name="MP", length_m=10000)]
        laps = [{"startOffsetSeconds": i * 320, "TotalTimerTime": 320, "TotalDistance": 1.0,
                 "AverageHeartRate": 150} for i in range(10)]
        al = align_laps(steps, laps)
        assert al is not None and len(al.steps[0].laps) == 10
        assert al.steps[0].pace_s == pytest.approx(320)

    def test_mismatch_returns_none(self, steps):
        assert align_laps(steps, CANOVA["laps"][:5]) is None          # laps run out
        overshoot = [{"TotalTimerTime": 2000, "TotalDistance": 5.0}]   # overshoots the 900 s warm-up
        assert align_laps(steps, overshoot) is None


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

    def test_bike_uses_power(self):
        pts = [{"time": t, "HeartRate": 130 if t < 1800 else 130 / 0.97, "Power": 200} for t in range(0, 3600, 5)]
        assert decoupling(pts, 0, 3600, "Bike") == 3.0

    def test_window_rule_unstructured_skips_first_5_min(self):
        end = series_end(EASY["series"])
        assert pa_hr_window(end) == (PA_HR_SKIP_S, end)

    def test_window_rule_structured_trims_warmup_and_cooldown(self, alignment):
        t0, t1 = pa_hr_window(series_end(CANOVA["series"], CANOVA["laps"]), alignment)
        assert t0 == alignment.steps[0].end          # warm-up end (> 5 min)
        assert t1 == alignment.steps[-1].start       # cool-down start

    def test_short_window_gives_no_value(self):
        assert pa_hr_window(PA_HR_SKIP_S + MIN_DECOUPLING_WINDOW_S - 1) is None
        assert session_decoupling(_synthetic_series(minutes=20), None, "Run") == ""

    def test_easy_run_from_5_min_is_lower_than_tp_whole_session(self):
        line = session_decoupling(EASY["series"], EASY["laps"], "Run")
        assert line.startswith("Pa:Hr (5:00 → 1:07:07, 62 min):")
        value = float(line.rsplit(" ", 1)[1].rstrip("%"))
        assert value == pytest.approx(4.6, abs=0.3)
        assert value < EASY["tp_pa_hr"]

    def test_canova_session_and_lap_fallback(self, alignment):
        line = session_decoupling(CANOVA["series"], CANOVA["laps"], "Run", alignment)
        assert line.startswith("Pa:Hr (15:42 → 1:01:41, 46 min):")
        series_value = float(line.rsplit(" ", 1)[1].rstrip("%"))
        assert series_value == pytest.approx(6.5, abs=0.5)
        lap_value = lap_decoupling(CANOVA["laps"], alignment.steps[0].end, alignment.steps[-1].start, "Run")
        assert lap_value == pytest.approx(series_value, abs=1.5)

    def test_no_data_returns_none(self):
        assert session_decoupling(None, None, "Run") is None


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

    def test_unaligned_shows_plan_only(self, thr):
        out = format_structured_execution(CANOVA["structured_workout"], CANOVA["laps"][:5], thr, None, "Run")
        assert "do not line up" in out
        assert "- B3: 4× Hard 1.00 km @ 5:05–5:15/km" in out

    def test_long_run_marks_race_pace_block_as_key(self):
        sw = {"primaryIntensityMetric": PACE, "structure": [
            {"type": "step", "length": {"value": 1, "unit": "repetition"}, "steps": [
                {"name": "Easy", "length": {"value": 7000, "unit": "meter"}, "targets": [{"minValue": 75, "maxValue": 82}], "intensityClass": "active"}]},
            {"type": "step", "length": {"value": 1, "unit": "repetition"}, "steps": [
                {"name": "MP", "length": {"value": 10000, "unit": "meter"}, "targets": [{"minValue": 89, "maxValue": 92}], "intensityClass": "active"}]},
            {"type": "step", "length": {"value": 1, "unit": "repetition"}, "steps": [
                {"name": "Easy", "length": {"value": 7000, "unit": "meter"}, "targets": [{"minValue": 75, "maxValue": 82}], "intensityClass": "active"}]},
        ]}
        paces = [380] * 7 + [320] * 10 + [380] * 7      # s/km per 1 km auto-lap
        laps, t = [], 0
        for p in paces:
            laps.append({"startOffsetSeconds": t, "stopOffsetSeconds": t + p, "TotalTimerTime": p,
                         "TotalDistance": 1.0, "AverageHeartRate": 150})
            t += p
        series = [{"time": s, "HeartRate": 140 + s / 600, "Speed": 10.5} for s in range(0, t, 5)]
        out = format_structured_execution(sw, laps, {"threshold_speed": 1000 / 290}, series, "Run")
        key = [l for l in out.splitlines() if "[key block]" in l]
        assert len(key) == 1 and key[0].startswith("- B2 MP: Pa:Hr")
