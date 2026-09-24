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
    DISTANCE_PROFILES,
    MAX_HEALTH_PENALTY,
    MAX_RACE_DAY_GAIN,
    classify_run,
    completed_runs,
    durability,
    extract_thresholds,
    format_drivers_table,
    format_projection_row,
    goal_pace_candidate,
    goal_pace_segments,
    health_readiness,
    hr_efficiency_candidate,
    load_projection,
    project_race,
    race_effort_candidate,
    select_for_analysis,
    summarize_analysis,
    threshold_anchor,
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
POOR_HEALTH = _health({"hrv": 52, "rhr": 52, "sleep": 6.5}, {"hrv": 60, "rhr": 48, "sleep": 7.5})


# ------------------------------------------------------------------------------
# Inputs
# ------------------------------------------------------------------------------
class TestExtractThresholds:
    def test_prefers_run_hr_zones_and_falls_back_to_default_speed(self):
        raw = mcp_envelope({"settings": {
            "heartRateZones": [{"workoutTypeId": 0, "threshold": 180}, {"workoutTypeId": 3, "threshold": 172}],
            "speedZones": [{"workoutTypeId": 0, "threshold": 3.4483}],
        }})
        assert extract_thresholds(raw) == {"lthr": 172, "threshold_speed": 3.4483}

    def test_missing_settings(self):
        assert extract_thresholds(None) == {"lthr": None, "threshold_speed": None}


class TestClassifyRun:
    @pytest.mark.parametrize("workout, expected", [
        ({"title": "Dam tot Damloop race", "distance_actual_km": 16}, "race"),
        ({"title": "parkrun", "distance_actual_km": 5}, "race"),
        (LONG_WORKOUT, "long"),
        (THRESHOLD_WORKOUT, "quality"),
        ({"title": "6 x 800m", "distance_actual_km": 10}, "quality"),
        ({"title": "Easy recovery", "distance_actual_km": 8}, "easy"),
        (ZONE2_HM_WORKOUT, "long"),
    ])
    def test_marathon_classification(self, workout, expected):
        assert classify_run(workout, "Marathon") == expected

    def test_long_threshold_depends_on_goal(self):
        run = {"title": "Steady 14k", "distance_actual_km": 14}
        assert classify_run(run, "5K") == "long"
        assert classify_run(run, "Marathon") == "easy"


class TestRunSelection:
    def test_completed_runs_filters_sport_window_and_planned(self):
        workouts = [
            THRESHOLD_WORKOUT, LONG_WORKOUT,
            {"id": 5, "date": "2026-09-22", "sport": "Bike", "distance_actual_km": 40},
            {"id": 6, "date": "2026-09-26", "sport": "Run", "distance_planned_km": 10},
            {"id": 7, "date": "2026-07-01", "sport": "Run", "distance_actual_km": 10},
        ]
        runs = completed_runs(workouts, TODAY - timedelta(days=56), TODAY)
        assert [w["id"] for w in runs] == [LONG_WORKOUT["id"], THRESHOLD_WORKOUT["id"]]

    def test_select_skips_easy_runs_and_caps(self):
        easy = [{"id": i, "date": f"2026-09-{i:02d}", "title": "Easy", "distance_actual_km": 8} for i in range(1, 9)]
        picked = select_for_analysis(easy + [THRESHOLD_WORKOUT, LONG_WORKOUT], "Marathon", max_n=8)
        assert {w["id"] for w in picked} == {THRESHOLD_WORKOUT["id"], LONG_WORKOUT["id"]}


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

    def test_meters_are_converted_to_km(self):
        s = summarize_analysis(_analysis([_lap(600, 2000, 300, 150)]), {"id": 1, "date": "2026-09-01"})
        assert s["laps"][0]["distance_km"] == 2.0

    def test_error_or_empty_payload(self):
        assert summarize_analysis(mcp_envelope({"isError": True}), {}) is None
        assert summarize_analysis(None, {}) is None


# ------------------------------------------------------------------------------
# Signals
# ------------------------------------------------------------------------------
class TestThresholdAnchor:
    def test_observed_laps_agree_with_tp_setting(self, summaries):
        anchor = threshold_anchor(summaries, "Marathon", LTHR, TP_SPEED)
        assert anchor["source"] == "observed+tp"
        assert anchor["speed"] == pytest.approx(TP_SPEED, rel=0.005)
        assert anchor["date"] == date(2026, 9, 10)
        assert "29' of threshold laps @ 4:50/km" in anchor["evidence"]

    def test_mp_laps_inside_long_run_are_not_threshold_evidence(self, summaries):
        anchor = threshold_anchor(summaries[1:], "Marathon", LTHR, TP_SPEED)
        assert anchor["source"] == "tp"
        assert "no recent threshold laps" in anchor["evidence"]

    def test_observed_wins_when_tp_setting_is_stale(self, summaries):
        anchor = threshold_anchor(summaries, "Marathon", LTHR, 3.2)
        assert anchor["source"] == "observed"
        assert anchor["speed"] == pytest.approx(1000 / 290, rel=0.005)

    def test_nothing_available(self):
        assert threshold_anchor([], "Marathon", LTHR, None) is None

    def test_cooldown_with_lagging_hr_is_not_threshold(self):
        # Live Sep 3 data: 544 s cool-down @ 5:59/km with HR still at 92% LTHR.
        s = [{"date": "2026-09-03", "title": "6km Tempo", "distance_km": 12.1, "laps": [
            {"duration_s": 1875, "distance_km": 6.0, "speed_ms": 1000 / 314, "hr": 158},
            {"duration_s": 544, "distance_km": 1.58, "speed_ms": 1000 / 359, "hr": 159},
        ]}]
        anchor = threshold_anchor(s, "Marathon", LTHR, TP_SPEED)
        assert "31' of threshold laps @ 5:14/km" in anchor["evidence"]


class TestIsCompleteSummary:
    def test_coverage(self):
        from running_coach.utils.race_readiness import is_complete_summary
        laps = [{"distance_km": 2.47}]
        assert not is_complete_summary({"distance_km": 12.9, "laps": laps})
        assert is_complete_summary({"distance_km": 2.5, "laps": laps})
        assert is_complete_summary({"distance_km": None, "laps": laps})
        assert not is_complete_summary({"distance_km": 5, "laps": []})
        assert not is_complete_summary(None)


class TestDurability:
    @pytest.mark.parametrize("longest, pa, tier", [
        (32.0, 4.0, "strong"), (28.0, 4.0, "moderate"), (20.0, 4.0, "weak"), (32.0, 9.0, "weak"),
    ])
    def test_marathon_tiers(self, longest, pa, tier):
        runs = [{"distance_actual_km": longest}]
        summ = [{"pa_hr": pa, "duration_s": 9000}]
        out = durability(runs, summ, "Marathon")
        assert out["tier"] == tier
        assert out["ratio"] == DISTANCE_PROFILES["Marathon"]["ratios"][tier]

    def test_short_runs_do_not_count_for_long_run_decoupling(self):
        out = durability([{"distance_actual_km": 32}], [{"pa_hr": 10.4, "duration_s": 3780}], "Marathon")
        assert out["tier"] == "strong"


class TestGoalPaceSegments:
    def test_mp_block_is_supporting_late_segment(self, summaries):
        goal_speed = 42195 / (MARATHON_GOAL_MIN * 60)
        segs = goal_pace_segments(summaries, "Marathon", [goal_speed], LTHR)
        assert len(segs) == 1
        seg = segs[0]
        assert seg["late"] and seg["supporting"]
        assert seg["hr_pct"] == pytest.approx(155 / 172)
        # Slightly above race HR -> implied race speed a bit slower than the lap.
        assert seg["implied_speed"] < seg["speed"]
        cand = goal_pace_candidate(segs)
        assert "8.0 km @ 5:31/km NGP (actual 5:20/km)" in cand["evidence"]
        assert "Pa:Hr 4.8%" in cand["evidence"] and "✅" in cand["evidence"]

    def test_high_decoupling_segment_is_not_supporting(self):
        s = [{"date": "2026-09-20", "laps": [{"duration_s": 2400, "distance_km": 7.5, "speed_ms": 3.12,
                                               "hr": 160, "decoupling": 9.0, "start_km": 20}]}]
        seg = goal_pace_segments(s, "Marathon", [3.12], LTHR)[0]
        assert not seg["supporting"]
        assert seg["implied_speed"] < 3.12 * 0.97

    def test_no_segments(self):
        assert goal_pace_candidate([]) is None


class TestHrEfficiency:
    def test_needs_enough_points(self, summaries):
        assert hr_efficiency_candidate(summaries[:1], "Marathon", LTHR) is None

    def test_fit_evaluated_near_race_hr(self, summaries):
        cand = hr_efficiency_candidate(summaries, "Marathon", LTHR)
        assert cand is not None
        assert 2.8 < cand["speed"] < 3.4
        assert "@ 153 bpm" in cand["evidence"]


class TestRaceEfforts:
    def test_zone2_long_run_is_not_a_race_effort(self):
        assert race_effort_candidate([ZONE2_HM_WORKOUT], "Marathon", None, None) is None

    def test_titled_race_uses_riegel(self):
        race = {"title": "Half Marathon race", "date": "2026-09-06", "distance_actual_km": 21.0975,
                "duration_actual": 1 + 45 / 60}
        cand = race_effort_candidate([race], "Marathon", None, None)
        assert 42195 / cand["speed"] == pytest.approx(6300 * 2 ** 1.06, rel=1e-3)


class TestLoadProjection:
    def test_safe_ramp_limited_by_target(self):
        out = load_projection(62.0, _trajectory(build=3.5, target=75.0))
        assert out["ctl_race"] == pytest.approx(62 + 3.5 * 3.5)
        assert out["time_factor"] == pytest.approx((62 / 74.25) ** 0.15)

    def test_race_day_gain_is_capped(self):
        out = load_projection(40.0, _trajectory(build=12, target=80.0))
        assert out["time_factor"] == pytest.approx(1 - MAX_RACE_DAY_GAIN)

    def test_no_trajectory_is_neutral(self):
        assert load_projection(50.0, None)["time_factor"] == 1.0


class TestHealthReadiness:
    def test_good_trend(self):
        out = health_readiness(GOOD_HEALTH, TODAY, 38, -4, 66, 62)
        assert out["flag"] == "🟢" and out["penalty"] == 0

    def test_poor_trend_under_heavy_load_is_expected(self):
        out = health_readiness(POOR_HEALTH, TODAY, 38, -18, 80, 62)
        assert out["flag"] == "🟡"
        assert not out["confidence_drop"] and out["penalty"] == 0
        assert "expected to clear in taper" in out["detail"]

    def test_poor_trend_without_load_lowers_confidence(self):
        out = health_readiness(POOR_HEALTH, TODAY, 38, 2, 55, 62)
        assert out["flag"] == "🔴" and out["confidence_drop"] and out["penalty"] == 0

    def test_poor_trend_in_race_week_costs_time(self):
        out = health_readiness(POOR_HEALTH, TODAY, 6, 12, 40, 62)
        assert out["flag"] == "🔴" and out["confidence_drop"]
        assert 0 < out["penalty"] <= MAX_HEALTH_PENALTY

    def test_no_data(self):
        assert health_readiness(None, TODAY, 38, 0, 0, 0)["flag"] == "⚪"


# ------------------------------------------------------------------------------
# End-to-end projection
# ------------------------------------------------------------------------------
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

    def test_drivers_cover_all_signals(self, summaries):
        p = self._project(summaries)
        names = [d[0] for d in p["drivers"]]
        assert names[:3] == ["Threshold anchor", "Goal-pace work", "HR efficiency"]
        assert names[-3:] == ["Durability", "Load", "Health"]
        table = format_drivers_table(p)
        assert table.startswith("**Projection drivers:**")
        assert "| Durability | Longest 28 km" in table

    def test_confidence_and_row(self):
        # Flat MP block (NGP == actual) -> signals agree within 6%.
        flat_laps = [_lap(6400, 18.0, 356, 136, dec=5.93), _lap(2559, 8.0, 320, 155, dec=4.77),
                     _lap(684, 2.0, 342, 158)]
        agreeing = [summarize_analysis(_analysis(THRESHOLD_LAPS, pa_hr=10.44), THRESHOLD_WORKOUT),
                    summarize_analysis(_analysis(flat_laps, pa_hr=5.27), LONG_WORKOUT)]
        p = self._project(agreeing)
        assert p["confidence"] in ("Medium", "High")
        assert not p["stale"]
        row = format_projection_row(p, "Marathon", " (5.5w out)")
        assert row.startswith("| **Projected Marathon** | Today `")
        assert "→ Race day `" in row and "Goal: `3:45:00` (5.5w out)" in row

    def test_disagreeing_signals_lower_confidence(self, summaries):
        # Real data: NGP 5:31 on the MP block vs a 4:50 threshold -> >6% spread.
        p = self._project(summaries)
        lo, hi = p["range_s"]
        assert (hi - lo) / lo > 0.06
        assert p["confidence"] == "Low"

    def test_poor_health_race_week_slows_race_day(self, summaries):
        base = self._project(summaries, trajectory_info=_trajectory(weeks=0.5, build=0))
        sick = self._project(summaries, trajectory_info=_trajectory(weeks=0.5, build=0),
                             dated_metrics=POOR_HEALTH, fitness=_fitness(tsb=12))
        assert sick["race_day_s"] > base["race_day_s"]
        assert sick["readiness"] == "🔴"
        assert _rank(sick["confidence"]) < _rank(base["confidence"]) or base["confidence"] == "Low"

    def test_no_evidence_returns_none(self):
        assert project_race("Marathon", 225, [], [], {"lthr": None, "threshold_speed": None},
                            None, _fitness(), None, None, TODAY) is None

    def test_5k_block_after_marathon_is_stale_and_fitness_adjusted(self, summaries):
        # Nov 1 marathon -> 4 weeks recovery -> 5K block starts Dec 1; check-in Dec 8.
        today = date(2026, 12, 8)
        pmc = [{"date": "2026-09-10", "ctl": 70.0}, {"date": "2026-09-20", "ctl": 72.0}]
        p = project_race(
            goal_label="5K", goal_minutes=20, runs=[], summaries=summaries, thresholds=THRESHOLDS,
            daily_pmc=pmc, fitness=_fitness(ctl=45.0, atl=40.0, tsb=5.0),
            trajectory_info=_trajectory(weeks=10, build=8, target=55), dated_metrics=None,
            today=today, block_start="2026-12-01",
        )
        assert p["stale"] and p["confidence"] == "Low"
        assert "fitness-adj." in p["drivers"][0][1]
        # 5K from a ~4:50 threshold: ~4:30/km before detraining; must be slower after it.
        assert p["today_s"] > 5000 / (TP_SPEED * 1.07)


def _rank(conf):
    return ("Low", "Medium", "High").index(conf)


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

    def test_empty(self):
        assert extract_health_metrics_dated(None) == {"sleep": [], "hrv": [], "rhr": []}
