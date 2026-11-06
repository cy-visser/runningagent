"""Behavioural test for workout creator (`create_workout`, `create_note`)."""

import asyncio
import json

from running_coach.features.workout_creator.create_note_tool import create_note
from running_coach.features.workout_creator.create_workout_tool import create_workout


def test_workout_creator_upserts_by_sport_flags_ambiguity_and_creates_notes(runner):
    runner.workouts.append({
        "id": "plan-run-1",
        "date": "2026-12-15",
        "sport": "Run",
        "title": "Planned Easy",
        "type": "planned",
    })
    ctx = runner.ctx()

    # Different sport on same day -> creates a new workout without touching the planned run.
    created = json.loads(asyncio.run(create_workout(ctx, "2026-12-15", sport="Strength", title="Core & Mobility")))
    assert created["success"] is True and created["action"] == "created"

    # Single planned workout of same sport -> updates it in place.
    updated = json.loads(asyncio.run(create_workout(ctx, "2026-12-15", sport="Run", title="Threshold 4x2km")))
    assert updated["success"] is True and updated["action"] == "updated" and updated["workout_id"] == "plan-run-1"

    # Two planned workouts of same sport -> returns needs_workout_id with candidates.
    runner.workouts.append({
        "id": "plan-run-2",
        "date": "2026-12-15",
        "sport": "Run",
        "title": "PM Shakeout",
        "type": "planned",
    })
    ambig = json.loads(asyncio.run(create_workout(ctx, "2026-12-15", sport="Run", title="Tempo")))
    assert ambig["success"] is False and ambig["action"] == "needs_workout_id"
    assert [c["workout_id"] for c in ambig["candidates"]] == ["plan-run-1", "plan-run-2"]

    note = json.loads(asyncio.run(create_note(ctx, date="2026-12-16", title="Rest day", description="Travel")))
    assert note["id"] == "note-999" and note["title"] == "Rest day"
