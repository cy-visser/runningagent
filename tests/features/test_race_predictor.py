"""Behavioural tests for the 12-week Race Predictor engine, quality-km cache trigger, and quick action."""

import asyncio
import copy
from datetime import date, timedelta
import json

from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import app
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.coach.coaching.instruction import build_profile_context
from running_coach.coach.coaching.quick_actions import QUICK_ACTION_PART_PREFIX
from running_coach.coach.profile_lookup import needs_onboarding
from running_coach.features.workout_analysis.analyze_workout_tool import analyze_workout
from running_coach.shared.athlete_settings import extract_thresholds
from running_coach.shared.goal_plan import active_race_goal, goal_key
from running_coach.shared.goal_projection.projection_evidence import (
    ANALYSIS_SCHEMA_VERSION,
    PROJECTION_WINDOW_DAYS,
    has_quality_kms,
    load_workout_summaries,
    quality_distance_km,
)
from running_coach.shared.goal_projection.race_projection import build_goal_projection, project_race
from running_coach.shared.hr_pace_fit import recency_weight
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.coach.test_quick_actions import RecordingLlm
from running_coach.tests.fakes import EMAIL, PLAN_PROFILE, SETTINGS, SINGLE_PROFILE, TODAY


def _threshold_summary(wid: str, run_date: date, pace_min_km: float, hr: float = 171.0) -> dict:
    """Synthetic steady threshold session summary with 2 x 3 km @ `pace_min_km`."""
    dur_s = round(3.0 * pace_min_km * 60)
    speed_ms = round(1000.0 / (pace_min_km * 60.0), 4)
    easy_ms = round(1000.0 / (5.5 * 60.0), 4)
    return {
        "version": ANALYSIS_SCHEMA_VERSION,
        "workout_id": wid,
        "date": run_date.isoformat(),
        "title": "Threshold 2 x 3km",
        "sport": "Run",
        "distance_km": 10.0,
        "duration_s": 1320 + 2 * dur_s,
        "pa_hr": 1.8,
        "weather": {"temp_c": 12.0, "feels_like_c": 11.0, "humidity_pct": 65},
        "laps": [
            {"lap": 1, "name": "Warm up", "duration_s": 660, "distance_km": 2.0, "speed_ms": easy_ms, "hr": 138.0},
            {"lap": 2, "name": "Interval 1", "duration_s": dur_s, "distance_km": 3.0, "speed_ms": speed_ms, "hr": hr},
            {"lap": 3, "name": "Interval 2", "duration_s": dur_s, "distance_km": 3.0, "speed_ms": speed_ms, "hr": hr},
            {"lap": 4, "name": "Cool down", "duration_s": 660, "distance_km": 2.0, "speed_ms": easy_ms, "hr": 140.0},
        ],
    }


def test_recency_weighting_favors_recent_key_sessions_over_10_week_old_sessions():
    assert PROJECTION_WINDOW_DAYS == 84
    w_recent = recency_weight(TODAY - timedelta(days=3), TODAY)
    w_old = recency_weight(TODAY - timedelta(days=70), TODAY)
    assert w_recent > 0.94
    assert 0.25 <= w_old < 0.35

    thresholds = extract_thresholds(SETTINGS)
    # SETTINGS threshold speed is 3.509 m/s (~4:45/km), so 10% band covers ~4:19/km to ~5:16/km.
    # Older threshold @ 5:00/km (70 days ago) vs recent threshold @ 4:24/km (3 days ago):
    old_s = _threshold_summary("old", TODAY - timedelta(days=70), pace_min_km=5.00)
    recent_s = _threshold_summary("recent", TODAY - timedelta(days=3), pace_min_km=4.40)
    runs_fast = [
        {"id": "old", "date": old_s["date"], "title": old_s["title"], "sport": "Run", "distance_actual_km": 10.0, "duration_actual": 0.9},
        {"id": "recent", "date": recent_s["date"], "title": recent_s["title"], "sport": "Run", "distance_actual_km": 10.0, "duration_actual": 0.9},
    ]
    proj_recent_fast = project_race(
        goal_label="10K",
        goal_minutes=43.0,
        runs=runs_fast,
        summaries=[old_s, recent_s],
        thresholds=thresholds,
        daily_pmc=None,
        fitness={"ctl": 58.0},
        trajectory_info={"build_weeks": 12, "target_peak_ctl": 65.0},
        dated_metrics=None,
        today=TODAY,
    )
    # Flip dates so the slower 5:00/km session is recent and 4:24/km is 70 days old:
    old_fast = _threshold_summary("old_f", TODAY - timedelta(days=70), pace_min_km=4.40)
    recent_slow = _threshold_summary("rec_s", TODAY - timedelta(days=3), pace_min_km=5.00)
    runs_slow = [
        {"id": "old_f", "date": old_fast["date"], "title": old_fast["title"], "sport": "Run", "distance_actual_km": 10.0, "duration_actual": 0.9},
        {"id": "rec_s", "date": recent_slow["date"], "title": recent_slow["title"], "sport": "Run", "distance_actual_km": 10.0, "duration_actual": 0.9},
    ]
    proj_recent_slow = project_race(
        goal_label="10K",
        goal_minutes=43.0,
        runs=runs_slow,
        summaries=[old_fast, recent_slow],
        thresholds=thresholds,
        daily_pmc=None,
        fitness={"ctl": 58.0},
        trajectory_info={"build_weeks": 12, "target_peak_ctl": 65.0},
        dated_metrics=None,
        today=TODAY,
    )
    assert proj_recent_fast is not None and proj_recent_slow is not None
    assert proj_recent_fast["window_weeks"] == 12
    assert proj_recent_fast["key_sessions_count"] == 2
    assert proj_recent_fast["today_s"] < proj_recent_slow["today_s"]
    assert proj_recent_fast["race_day_s"] < proj_recent_slow["race_day_s"]


def test_training_log_summaries_and_untitled_key_runs_feed_12_week_projection(runner):
    # Untitled "Morning Run" 60 days ago with quality laps recorded in training_log:
    # reused in the 12-week window and counted as a key session with zero extra tp_analyze_workout calls.
    sixty_days_ago = TODAY - timedelta(days=60)
    summary_60d = _threshold_summary("w_untitled_lt2", sixty_days_ago, pace_min_km=4.45, hr=170.0)
    untitled_run = {
        "id": "w_untitled_lt2",
        "date": sixty_days_ago.isoformat(),
        "title": "Morning Run",
        "sport": "Run",
        "type": "completed",
        "distance_actual_km": 10.0,
        "duration_actual": 0.85,
        "tss_actual": 78.0,
    }
    runner.workouts.append(untitled_run)
    runner.training_records["w_untitled_lt2"] = {
        **summary_60d,
        "title": "Morning Run",
        "sport": "Run",
        "thresholds": {"lthr": 172.0, "threshold_speed": 3.509},
    }
    runner.tp_calls.clear()
    ctx = runner.ctx(user_id="cyrille_visser")
    summaries = asyncio.run(
        load_workout_summaries(
            ctx,
            [untitled_run],
            "cyrille_visser",
            training_records=list(runner.training_records.values()),
        )
    )
    assert len(summaries) == 1
    assert summaries[0]["workout_id"] == "w_untitled_lt2"
    assert not [n for n, _ in runner.tp_calls if n == "tp_analyze_workout"]  # reused training_log at zero TP calls

    wrapped = asyncio.run(
        build_goal_projection(
            ctx,
            "10K",
            PLAN_PROFILE,
            [untitled_run],
            {"ctl": 56.0},
            SETTINGS,
            None,
            TODAY,
            training_records=list(runner.training_records.values()),
        )
    )
    assert wrapped["goal_label"] == "10K"
    assert wrapped["key_sessions_count"] == 1
    assert wrapped["projection"] is not None
    assert wrapped["projection"]["window_weeks"] == 12


def test_quality_kms_detection_distinguishes_quality_sessions_from_easy_runs_with_strides():
    easy_ms = round(1000.0 / (5.30 * 60.0), 4)
    stride_ms = round(1000.0 / (3.33 * 60.0), 4)
    easy_laps_with_strides = [
        {"lap": 1, "duration_s": 3180, "distance_km": 10.0, "speed_ms": easy_ms, "hr": 143.0},
        # Four 20s strides (< 60s minimum quality lap duration) must NOT trigger quality km refresh:
        {"lap": 2, "duration_s": 20, "distance_km": 0.1, "speed_ms": stride_ms, "hr": 168.0},
        {"lap": 3, "duration_s": 20, "distance_km": 0.1, "speed_ms": stride_ms, "hr": 169.0},
        {"lap": 4, "duration_s": 20, "distance_km": 0.1, "speed_ms": stride_ms, "hr": 170.0},
        {"lap": 5, "duration_s": 20, "distance_km": 0.1, "speed_ms": stride_ms, "hr": 171.0},
    ]
    assert (
        quality_distance_km(
            easy_laps_with_strides,
            title="Easy Aerobic Run + Strides",
            distance_km=10.4,
            lthr=172.0,
            threshold_speed=3.509,
        )
        == 0.0
    )
    assert (
        has_quality_kms(
            easy_laps_with_strides,
            title="Easy Aerobic Run + Strides",
            distance_km=10.4,
            lthr=172.0,
            threshold_speed=3.509,
        )
        is False
    )

    threshold_run = _threshold_summary("thr_1", TODAY, pace_min_km=4.45, hr=171.0)
    assert (
        quality_distance_km(
            threshold_run["laps"],
            title=threshold_run["title"],
            distance_km=threshold_run["distance_km"],
            lthr=172.0,
            threshold_speed=3.509,
        )
        == 6.0
    )
    assert (
        has_quality_kms(
            threshold_run["laps"],
            title=threshold_run["title"],
            distance_km=threshold_run["distance_km"],
            lthr=172.0,
            threshold_speed=3.509,
        )
        is True
    )


def test_analyze_workout_updates_firestore_projection_cache_only_when_run_has_quality_kms(runner):
    # 1. Easy Zone 2 run with short strides (and no structured quality intervals):
    # should NOT write race_projection_cache.
    easy_workout = next(w for w in runner.workouts if w["title"] == "Easy Aerobic Run" and w["type"] == "completed")
    orig_run_tp = runner.run_tp_tool

    async def patched_tp(tool_context, name, **kw):
        res = await orig_run_tp(tool_context, name, **kw)
        if name == "tp_get_workout" and str(kw.get("workout_id")) == easy_workout["id"]:
            payload = json.loads(res["content"][0]["text"])
            payload["structured_workout"] = None
            return {"content": [{"type": "text", "text": json.dumps(payload)}]}
        return res

    runner.run_tp_tool = patched_tp  # type: ignore[method-assign]
    from running_coach.integrations.trainingpeaks import tp_calls

    tp_calls.run_tp_tool = patched_tp  # type: ignore[assignment]
    runner.analysis_overrides[easy_workout["id"]] = {
        "lapData": [
            {
                "LapNumber": 1,
                "LapName": "Easy",
                "IsActive": True,
                "TotalDistance": 9.8,
                "TotalTimeSeconds": 3120,
                "AverageHeartRate": 144,
                "NormalizedSpeed": 1000.0 / (5.30 * 60.0),
            },
            {
                "LapNumber": 2,
                "LapName": "Stride",
                "IsActive": True,
                "TotalDistance": 0.1,
                "TotalTimeSeconds": 20,
                "AverageHeartRate": 168,
                "NormalizedSpeed": 1000.0 / (3.30 * 60.0),
            },
        ],
        "totals": {
            "Avg heart rate": {"value": 144, "unit": "bpm"},
            "Max heart rate": {"value": 168, "unit": "bpm"},
            "NGP": {"value": 5.28, "unit": "min/km"},
            "Pa:Hr": {"value": 2.1, "unit": "%"},
            "Duration": {"value": 3140, "unit": "s"},
        },
        "startTimestamp": f"{easy_workout['date']}T07:30:00",
        "data_file": None,
    }
    ctx_easy = runner.ctx(user_id="cyrille_visser")
    asyncio.run(analyze_workout(ctx_easy, date_str=easy_workout["date"]))
    assert "cyrille_visser" not in runner.race_projection_cache

    # 2. Quality session (Threshold 2 x 15'): updates race_projection_cache!
    quality_workout = next(
        w for w in runner.workouts
        if w["title"] == "Threshold 2 x 15'" and w["type"] == "completed" and w["date"] != "2026-10-20"
    )
    ctx_quality = runner.ctx(user_id="cyrille_visser")
    asyncio.run(analyze_workout(ctx_quality, date_str=quality_workout["date"]))

    cached = runner.race_projection_cache.get("cyrille_visser")
    assert cached is not None
    assert cached["trigger"] == "workout_analysis"
    assert cached["trigger_workout"]["workout_id"] == quality_workout["id"]
    assert cached["trigger_workout"]["quality_km"] >= 6.0
    assert cached["active_goal"]["kind"] == "sub_goal"
    assert cached["active_goal"]["training_goal"] == "Sub-43 10K"
    assert cached["active_goal"]["sub_goal_step"] == 2
    assert cached["active_goal"]["sub_goal_total"] == 2
    assert cached["projection"]["goal_label"] == "10K"
    assert cached["north_star"]["goal_label"] == "Marathon"
    assert cached["window_weeks"] == 12


def test_check_in_report_project_quick_action_computes_and_caches_in_zero_llm_calls(runner, monkeypatch):
    llm = RecordingLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        parts = [
            types.Part(text="Refresh race projection"),
            types.Part(text=QUICK_ACTION_PART_PREFIX + json.dumps({"skill": "check-in-report:project"})),
        ]
        events = []
        async for ev in r.run_async(
            user_id="web_runner",
            session_id=session.id,
            state_delta={AUTH_EMAIL_STATE_KEY: EMAIL},
            new_message=types.Content(role="user", parts=parts),
        ):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert llm.requests == []  # zero LLM calls
    calls = [
        p.function_call.name
        for e in events if e.content
        for p in e.content.parts or [] if p.function_call
    ]
    assert calls == ["refresh_race_projection"]
    assert events[-1].actions.skip_summarization is True
    cached = runner.race_projection_cache.get("cyrille_visser")
    assert cached is not None
    assert cached["trigger"] == "manual_refresh"
    assert cached["goal_key"] == "sub_goal:sub-43 10k:2027-02-14"


def test_no_goal_profile_states_and_active_race_goal_resolution():
    no_goal_profile = {"firstname": "Cyrille", "lastname": "Visser", "email": EMAIL, "goal_type": "none"}
    assert needs_onboarding(no_goal_profile) is False
    assert needs_onboarding({**no_goal_profile, "onboarding_pending": True}) is True

    _, label_none, status_none = active_race_goal(no_goal_profile, TODAY)
    assert status_none == "no_goal" and label_none is None
    assert "Goal: not set" in build_profile_context(no_goal_profile, TODAY)

    # Active multi-stage plan resolves to the upcoming sub-goal ("Sub-43 10K"):
    block_plan, label_plan, status_plan = active_race_goal(PLAN_PROFILE, TODAY)
    assert status_plan == "ok" and label_plan == "10K"
    assert block_plan["training_goal"] == "Sub-43 10K"
    assert goal_key(block_plan) == "sub_goal:sub-43 10k:2027-02-14"

    # Past final race resolves to "race_passed":
    past_single = {**SINGLE_PROFILE, "timeline": "2026-10-01"}
    _, _, status_past = active_race_goal(past_single, TODAY)
    assert status_past == "race_passed"

    # Non-distance goal text resolves to "non_race_goal":
    fitness_goal = copy.deepcopy(SINGLE_PROFILE)
    fitness_goal["training_goal"] = "Run consistently 4x per week"
    _, _, status_non_race = active_race_goal(fitness_goal, TODAY)
    assert status_non_race == "non_race_goal"
