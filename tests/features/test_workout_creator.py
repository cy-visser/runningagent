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


def _writes(runner) -> list[str]:
    return [name for name, _ in runner.tp_calls if name in ("tp_create_workout", "tp_update_workout")]


def test_create_workout_writes_and_reports_load_warnings(runner):
    ctx = runner.ctx()
    # Wed 2026-11-04: Tue is 'Threshold 2 x 15'' and the prior week ran 44.5 km.
    risky = json.loads(asyncio.run(create_workout(
        ctx, "2026-11-04", sport="Run", title="VO2max 5x1km Intervals",
        distance_km=10.0, duration_minutes=55, create=True)))
    assert risky["success"] is True and risky["action"] == "created"   # written on the first call
    assert _writes(runner) == ["tp_create_workout"]
    assert any("consecutive day" in r and "2026-11-03" in r for r in risky["warnings"])
    # Volume growth is a fact for the coach (no coded % limit), never a warning.
    assert not any("km vs" in r or "limit" in r for r in risky["warnings"])
    assert risky["week"]["running_km_after"] == 54.5 and risky["week"]["quality_sessions_after"] == 2
    assert risky["week"]["prior_week_running_km"] == 44.5
    assert risky["week"]["volume_change_pct"] == 22.5 and risky["week"]["volume_increased"] is True

    # A long run three days after the 'Slight calf tightness' note is written and warned about.
    long_run = json.loads(asyncio.run(create_workout(
        ctx, "2026-10-28", sport="Run", title="Long Run", distance_km=16.0, create=True)))
    assert long_run["success"] is True
    assert long_run["warnings"] == ["Calendar note on 2026-10-25: 'Slight calf tightness'."]

    # A short easy run has no warnings but carries the week's volume facts; non-run sports are never checked.
    easy = json.loads(asyncio.run(create_workout(
        ctx, "2026-11-04", sport="Run", title="Easy Shakeout", distance_km=3.0, create=True)))
    assert easy["success"] is True and "warnings" not in easy
    assert easy["week"]["volume_increased"] is True and easy["week"]["volume_change_pct"] is not None
    bike = json.loads(asyncio.run(create_workout(ctx, "2026-11-04", sport="Bike", title="VO2 Intervals", create=True)))
    assert bike["success"] is True and "warnings" not in bike and "week" not in bike


def test_load_warnings_only_flag_what_the_change_makes_worse(runner):
    # Week of 2026-11-02 is already over the volume limit (54.5 km vs 44.5 km) and has 3 quality sessions.
    runner.workouts += [
        {"id": "extra-run", "date": "2026-11-04", "sport": "Run", "title": "Easy Run",
         "type": "planned", "distance_planned_km": 10.0},
        {"id": "q2", "date": "2026-11-05", "sport": "Run", "title": "Tempo 3 x 10'", "type": "planned"},
        {"id": "q3", "date": "2026-11-08", "sport": "Run", "title": "Intervals 6 x 800m", "type": "planned"},
    ]
    ctx = runner.ctx()

    # Shortening a run in an over-volume week reduces volume: updated, no volume warning.
    shorter = json.loads(asyncio.run(create_workout(
        ctx, "2026-11-04", sport="Run", title="Easy Run", distance_km=8.0, workout_id="extra-run")))
    assert shorter["success"] is True and shorter["action"] == "updated" and "warnings" not in shorter

    # Swapping one quality session for another keeps the count: updated, no quality-count warning.
    swapped = json.loads(asyncio.run(create_workout(
        ctx, "2026-11-08", sport="Run", title="Fartlek 8 x 1'", workout_id="q3")))
    assert swapped["success"] is True and swapped["action"] == "updated" and "warnings" not in swapped
    assert _writes(runner) == ["tp_update_workout", "tp_update_workout"]
