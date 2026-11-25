"""End-to-end behavioural tests for TrainingPeaks Race Events across Plan Builder, Plan Audit, and Workout Creator."""

from __future__ import annotations

import asyncio
import json

from running_coach.features.plan_audit.fetch_plan_audit_data_tool import fetch_plan_audit_data
from running_coach.features.plan_builder.apply_training_plan_tool import apply_training_plan
from running_coach.features.plan_builder.fetch_plan_context_tool import fetch_plan_context
from running_coach.features.plan_builder.stage_training_plan_tool import stage_training_plan
from running_coach.features.workout_creator.apply_staged_changes_tool import apply_staged_changes
from running_coach.features.workout_creator.stage_workout_changes_tool import stage_workout_changes
from running_coach.shared.race_events import (
    RACE_TYPE_1_TO_2H,
    RACE_TYPE_OVER_2H,
    RACE_TYPE_UNDER_1H,
    derive_race_type_duration,
)
from running_coach.tests.fakes import PLAN_PROFILE


def test_derive_race_type_duration_matches_verified_tp_buckets():
    assert derive_race_type_duration(goal_text="Sub-21 5K") == RACE_TYPE_UNDER_1H
    assert derive_race_type_duration(goal_text="Sub-43 10K") == RACE_TYPE_UNDER_1H
    assert derive_race_type_duration(goal_text="Sub-1:35 Half Marathon") == RACE_TYPE_1_TO_2H
    assert derive_race_type_duration(goal_text="Sub-2:05 Half Marathon") == RACE_TYPE_OVER_2H
    assert derive_race_type_duration(goal_text="Sub-3:15 Marathon") == RACE_TYPE_OVER_2H
    assert derive_race_type_duration(distance_km=5.0) == RACE_TYPE_UNDER_1H
    assert derive_race_type_duration(distance_km=21.1) == RACE_TYPE_1_TO_2H
    assert derive_race_type_duration(distance_km=42.2) == RACE_TYPE_OVER_2H


def test_plan_builder_stages_and_applies_combined_race_workout_and_tp_events(runner):
    profile = {
        **PLAN_PROFILE,
        "goal_type": "single",
        "training_goal": "Sub-1:35 Half Marathon",
        "race_name": "Amsterdam Half Marathon",
        "timeline": "2026-11-15",
        "north_star": None,
        "sub_goals": [],
        "planned": False,
    }
    ctx = runner.ctx(profile=profile)
    context_text = asyncio.run(fetch_plan_context(ctx, start_date="2026-11-02", end_date="2026-11-15", mode="new"))
    assert "EVENTS IN WINDOW: none" in context_text

    # 1. Intermediate race mistakenly set to priority A must be rejected!
    bad_plan = {
        "start_date": "2026-11-02",
        "end_date": "2026-11-15",
        "mode": "new",
        "weeks": [
            "W1 | peak | Tune-up 10K | Tue: E 8 | Sun: RACE 10k @10K Local 10K",
            "W2 | race | Race week | Tue: E 6 | Sun: RACE",
        ],
        "events": [
            {"date": "2026-11-08", "name": "Local 10K", "priority": "A", "distance_km": 10.0},
            {"date": "2026-11-15", "name": "Amsterdam Half Marathon", "priority": "A", "distance_km": 21.1},
        ],
    }
    bad_res = json.loads(asyncio.run(stage_training_plan(ctx, bad_plan, message="Block strategy")))
    assert bad_res["staged"] == 0
    assert any("cannot be priority A" in e["why"] for e in bad_res["errors"])

    # 2. Valid plan: B-priority intermediate 10K + A-priority HM with place & PR from coach conversation
    good_plan = {
        "start_date": "2026-11-02",
        "end_date": "2026-11-15",
        "mode": "new",
        "weeks": [
            "W1 | peak | Tune-up 10K | Tue: E 8 | Sun: RACE 10k @10K Local 10K",
            "W2 | race | Race week | Tue: E 6 | Sun: RACE",
        ],
        "events": [
            {
                "date": "2026-11-08",
                "name": "Local 10K",
                "event_type": "RunningRoad",
                "priority": "B",
                "distance_km": 10.0,
                "goal_time": "43:00",
                "goal_pr": False,
            },
            {
                "date": "2026-11-15",
                "name": "Amsterdam Half Marathon",
                "event_type": "RunningRoad",
                "priority": "A",
                "distance_km": 21.1,
                "goal_time": "1:35:00",
                "goal_place": 25,
                "goal_pr": True,
            },
        ],
    }
    staged_res = json.loads(asyncio.run(stage_training_plan(ctx, good_plan, message="Block strategy")))
    assert staged_res["events"] == 2
    staged_id = staged_res["staged_id"]
    staged_state = ctx.state["staged_training_plan"]
    assert len(staged_state["events"]) == 2
    assert staged_state["events"][0]["race_type_duration"] == RACE_TYPE_UNDER_1H
    assert staged_state["events"][1]["race_type_duration"] == RACE_TYPE_1_TO_2H

    # Apply both weeks -> creates BOTH the race workouts (with tags="race") AND the TP Events!
    runner.tp_calls.clear()
    r1 = json.loads(asyncio.run(apply_training_plan(ctx, staged_id, 1)))
    r2 = json.loads(asyncio.run(apply_training_plan(ctx, staged_id, 2)))
    assert r1["success"] is True and r2["success"] is True

    created_events = [kw for n, kw in runner.tp_calls if n == "tp_create_event"]
    assert len(created_events) == 2
    ev_by_date = {kw["date"]: kw for kw in created_events}
    assert ev_by_date["2026-11-08"]["priority"] == "B"
    assert ev_by_date["2026-11-08"]["race_type_duration"] == RACE_TYPE_UNDER_1H
    assert ev_by_date["2026-11-08"]["goal_pr"] is False

    assert ev_by_date["2026-11-15"]["priority"] == "A"
    assert ev_by_date["2026-11-15"]["race_type_duration"] == RACE_TYPE_1_TO_2H
    assert ev_by_date["2026-11-15"]["goal_time"] == "1:35:00"
    assert ev_by_date["2026-11-15"]["goal_place"] == 25
    assert ev_by_date["2026-11-15"]["goal_pr"] is True

    created_race_workouts = [
        kw for n, kw in runner.tp_calls
        if n in ("tp_create_workout", "tp_update_workout") and kw.get("tags") == "race"
    ]
    assert len(created_race_workouts) == 2


def test_plan_audit_flags_missing_and_misprioritized_events(runner):
    profile = {
        **PLAN_PROFILE,
        "goal_type": "single",
        "training_goal": "Sub-1:35 Half Marathon",
        "race_name": "Amsterdam HM",
        "timeline": "2026-11-15",
        "north_star": None,
        "sub_goals": [],
        "planned": True,
    }
    runner.workouts.extend([
        {
            "id": "w_tuneup",
            "date": "2026-11-08",
            "title": "Race: Local 10K",
            "sport": "Run",
            "tags": "race",
            "type": "planned",
            "distance_planned_km": 10.0,
            "duration_planned": 0.72,
            "tss_planned": 75.0,
        },
        {
            "id": "w_goal_hm",
            "date": "2026-11-15",
            "title": "Race: Amsterdam HM",
            "sport": "Run",
            "tags": "race",
            "type": "planned",
            "distance_planned_km": 21.1,
            "duration_planned": 1.58,
            "tss_planned": 140.0,
        },
    ])
    # No events configured -> Plan Audit must flag BOTH the block goal race and the intermediate race!
    runner.events = []
    ctx = runner.ctx(profile=profile)
    out = asyncio.run(fetch_plan_audit_data(ctx, start_date="2026-11-02", end_date="2026-11-15"))
    assert "Race Events in Window:" in out
    assert "Missing TrainingPeaks A-priority Event for block goal 'Amsterdam HM' on 2026-11-15" in out
    assert "Missing TrainingPeaks B/C-priority Event for intermediate race 'Race: Local 10K' on 2026-11-08" in out

    # Now add the A event on 2026-11-15 and a wrongly prioritized A event on 2026-11-08 -> flags intermediate A!
    runner.events = [
        {"id": "e1", "name": "Amsterdam HM", "eventDate": "2026-11-15", "eventType": "RunningRoad", "atpPriority": "A", "distance": 21100.0, "distanceUnits": "Meters"},
        {"id": "e2", "name": "Local 10K", "eventDate": "2026-11-08", "eventType": "RunningRoad", "atpPriority": "A", "distance": 10000.0, "distanceUnits": "Meters"},
    ]
    out2 = asyncio.run(fetch_plan_audit_data(ctx, start_date="2026-11-02", end_date="2026-11-15"))
    assert "Missing TrainingPeaks A-priority Event" not in out2
    assert "is priority A (must be B or C, not A)" in out2


def test_workout_creator_stages_and_applies_tp_events_create_and_update(runner):
    profile = {
        **PLAN_PROFILE,
        "goal_type": "single",
        "training_goal": "Sub-1:35 Half Marathon",
        "race_name": "Amsterdam HM",
        "timeline": "2026-11-15",
        "north_star": None,
        "sub_goals": [],
        "planned": True,
    }
    runner.events = []
    ctx = runner.ctx(profile=profile)

    # 1. Stage via compact 1-line string (creates A event) + dict (creates B intermediate event)
    res = json.loads(asyncio.run(stage_workout_changes(
        ctx,
        changes=[
            "2026-11-15: event A RunningRoad 21.1k Amsterdam HM | goal=1:35:00 place=20 pr=true",
            {
                "kind": "event",
                "date_str": "2026-11-08",
                "name": "Local 10K",
                "event_type": "RunningRoad",
                "priority": "B",
                "distance_km": 10.0,
                "goal_time": "43:00",
                "goal_pr": False,
            },
        ],
        message="Adding missing TP events from plan audit.",
    )))
    assert res["staged"] == 2
    staged_id = res["staged_id"]

    # Apply staged events
    applied = json.loads(asyncio.run(apply_staged_changes(ctx, staged_id=staged_id)))
    assert applied["success"] is True
    assert len(runner.events) == 2

    # 2. Re-staging an event on 2026-11-15 resolves as UPDATE (no duplicate event!)
    res2 = json.loads(asyncio.run(stage_workout_changes(
        ctx,
        changes=["2026-11-15: event A RunningRoad 21.1k Amsterdam HM | goal=1:34:00 place=15 pr=true"],
        message="Updating goal time.",
    )))
    assert res2["staged"] == 1
    staged_ev = ctx.state["staged_workout_changes"]["changes"][0]
    assert staged_ev["action"] == "update"
    assert staged_ev["event_id"] is not None

    applied2 = json.loads(asyncio.run(apply_staged_changes(ctx, staged_id=res2["staged_id"])))
    assert applied2["success"] is True
    assert len(runner.events) == 2  # updated in-place, still 2 events
