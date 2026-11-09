"""Behavioural test for the workout creator: stage changes, apply them by code, coded confirmations."""

import asyncio
import json


from running_coach.features.workout_creator.apply_staged_changes_tool import apply_staged_changes
from running_coach.features.workout_creator.stage_workout_changes_tool import (
    STAGED_CHANGES_STATE_KEY,
    stage_workout_changes,
)
from running_coach.integrations.trainingpeaks import tp_calls

WRITE_TOOLS = ("tp_create_workout", "tp_update_workout", "tp_create_note")

THRESHOLD_4X2KM = {"steps": [
    {"name": "Warm up", "intensityClass": "warmUp", "duration_seconds": 900, "pace": "5:50-6:20"},
    {"type": "repetition", "reps": 4, "steps": [
        {"name": "Threshold", "intensityClass": "active", "distance_m": 2000, "pace": "4:45-4:52"},
        {"name": "Jog", "intensityClass": "rest", "duration_seconds": 120, "pace": "6:15-7:00"}]},
    {"name": "Cool down", "intensityClass": "coolDown", "duration_seconds": 600, "pace": "5:50-6:20"},
]}
RECOVERY_6KM = {"steps": [{"name": "Recovery", "intensityClass": "active", "distance_m": 6000, "pace": "6:00-6:30"}]}

# Planned week of 2026-11-02 in the fake calendar: Mon easy run, Tue 'Threshold 2 x 15'', Thu bike,
# Fri easy run, Sat long run.
CHANGES = [
    {"date_str": "2026-11-03", "title": "Threshold 4x2km", "distance_km": 12, "duration_minutes": 65,
     "tss_planned": 78, "description": "15' WU, 4x2km @ LT2, 2' jog, 10' CD",
     "structure": THRESHOLD_4X2KM},                                                   # updates Tue threshold
    {"date_str": "2026-11-04", "title": "Recovery Run", "distance_km": 6,
     "structure": RECOVERY_6KM},                                                      # no run that day: create
    {"date_str": "2026-11-03", "sport": "Strength", "title": "Core & Hips", "create": True},
    {"kind": "note", "date_str": "2026-11-04", "title": "Travel: Milan"},
]


def _writes(runner) -> list[str]:
    return [name for name, _ in runner.tp_calls if name in WRITE_TOOLS]


def _stage(ctx, changes) -> dict:
    return json.loads(asyncio.run(stage_workout_changes(ctx, changes)))


def test_staging_resolves_create_update_and_ambiguity_with_one_lookup_and_no_writes(runner):
    runner.workouts.append({"id": "pm-run", "date": "2026-11-06", "sport": "Run", "title": "PM Shakeout",
                            "type": "planned"})
    ctx = runner.ctx()
    result = _stage(ctx, CHANGES + [{"date_str": "2026-11-06", "title": "Fartlek 8x1'"}])

    assert sorted(name for name, _ in runner.tp_calls) == ["tp_get_athlete_settings", "tp_get_workouts"]
    assert _writes(runner) == []
    staged = ctx.state[STAGED_CHANGES_STATE_KEY]
    assert result["staged"] == 4 and result["staged_id"] == staged["staged_id"]
    by_title = {c["title"]: c for c in staged["changes"]}
    threshold = by_title["Threshold 4x2km"]
    assert threshold["action"] == "update" and threshold["replaces_title"] == "Threshold 2 x 15'"
    assert threshold["workout_id"] and threshold["description"]
    # Totals follow the builder (whole minutes / TSS); the coach's 12 km / 65 min are reported back.
    assert threshold["distance_km"] == 13.09
    assert all(type(threshold[f]) is int for f in ("duration_minutes", "tss_planned"))
    assert (threshold["duration_minutes"], threshold["tss_planned"]) == (72, 98)
    # Builder targets are whole % of threshold pace (no 88.9 %).
    targets = [t for block in threshold["structured_workout"]["structure"] for s in block["steps"]
               for t in s["targets"]]
    assert targets and all(type(t[k]) is int for t in targets for k in ("minValue", "maxValue"))
    # Whole-% targets read back within ±1 s/km of the coach's 4:45-4:52.
    assert threshold["structure_summary"] == "15' WU · 4× (2 km @ 4:45–4:51/km / 2' rec) · 10' CD"
    assert {n["field"] for n in result["totals_from_builder"]} == {"distance_km", "duration_minutes"}
    assert by_title["Recovery Run"]["action"] == "create" and by_title["Recovery Run"]["workout_id"] is None
    assert by_title["Recovery Run"]["structured_workout"]["structure"][0]["steps"][0]["length"] == {
        "value": 6000, "unit": "meter"}
    assert by_title["Core & Hips"]["action"] == "create" and by_title["Core & Hips"]["sport"] == "Strength"
    assert "structured_workout" not in by_title["Core & Hips"]
    assert by_title["Travel: Milan"]["kind"] == "note"
    # Two planned runs on Fri: not staged, the coach asks which one.
    (ambiguous,) = result["ambiguous"]
    assert ambiguous["reason"] == "needs_workout_id" and ambiguous["date_str"] == "2026-11-06"
    assert {c["title"] for c in ambiguous["candidates"]} == {"Easy Run", "PM Shakeout"}

    # A new staging replaces the previous set.
    again = _stage(ctx, [{"date_str": "2026-11-06", "title": "Fartlek 8x1'", "workout_id": "pm-run"}])
    assert again["staged_id"] != result["staged_id"]
    assert [c["workout_id"] for c in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]] == ["pm-run"]


def test_apply_writes_every_staged_change_clears_staging_and_handles_stale_buttons(runner):
    ctx = runner.ctx()
    staged_id = _stage(ctx, CHANGES)["staged_id"]

    stale = json.loads(asyncio.run(apply_staged_changes(ctx, staged_id="00000000-0000-0000-0000-000000000000")))
    assert stale == {"success": False, "reason": "replaced"} and _writes(runner) == []

    applied = json.loads(asyncio.run(apply_staged_changes(ctx, staged_id=staged_id)))
    assert applied["success"] is True and all(r["ok"] for r in applied["results"])
    assert sorted(_writes(runner)) == ["tp_create_note", "tp_create_workout", "tp_create_workout", "tp_update_workout"]
    update_kw = next(kw for name, kw in runner.tp_calls if name == "tp_update_workout")
    assert update_kw["title"] == "Threshold 4x2km" and update_kw["duration_minutes"] == 72
    assert update_kw["distance_km"] == 13.09 and update_kw["tss_planned"] == 98
    assert "structure" not in update_kw and update_kw["structured_workout"]["primaryLengthMetric"] == "distance"
    assert all("structured_workout" not in r for r in applied["results"])  # bulky builder kept out of the result
    assert ctx.state[STAGED_CHANGES_STATE_KEY] is None
    assert ctx.state["applied_workout_changes"] == {"staged_id": staged_id, "applied": 4, "failed": 0}

    assert json.loads(asyncio.run(apply_staged_changes(ctx))) == {"success": False, "reason": "nothing_staged"}


# ------------------------------------------------------------------------------
# Coded replies (no LLM call after staging / applying)
# ------------------------------------------------------------------------------


# ------------------------------------------------------------------------------
# Workout builder: exact numbers, never scaled
# ------------------------------------------------------------------------------

# A TrainingPeaks builder as stored (whole %): 15' WU, 5 x (10' @ 104-108 % / 2' jog), 10' CD.
