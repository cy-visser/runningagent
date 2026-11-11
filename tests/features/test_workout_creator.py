"""Behavioural test for the workout creator: stage changes, apply them by code, coded confirmations."""

import asyncio
import json

from google.adk.events.event import Event
from google.genai import types


from running_coach.features.workout_creator.apply_staged_changes_tool import (
    NOTHING_STAGED_TEXT,
    REPLACED_TEXT,
    apply_staged_changes,
)
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

    # The date-resolved threshold update also reads its current builder (to keep its strides).
    assert sorted(name for name, _ in runner.tp_calls) == ["tp_get_athlete_settings", "tp_get_workout", "tp_get_workouts"]
    assert _writes(runner) == []
    staged = ctx.state[STAGED_CHANGES_STATE_KEY]
    assert result["staged"] == 4 and result["staged_id"] == staged["staged_id"]
    by_title = {c["title"]: c for c in staged["changes"]}
    threshold = by_title["Threshold 4x2km"]
    assert threshold["action"] == "update" and threshold["replaces_title"] == "Threshold 2 x 15'"
    assert threshold["workout_id"] and threshold["description"]
    # Totals follow the builder (whole minutes / TSS), incl. the strides kept from the current builder;
    # the coach's 12 km / 65 min are reported back against its own builder (13.09 km / 72 min).
    assert threshold["distance_km"] == 13.78 and threshold["strides_added"] == "kept"
    assert all(type(threshold[f]) is int for f in ("duration_minutes", "tss_planned"))
    assert (threshold["duration_minutes"], threshold["tss_planned"]) == (76, 104)
    # Builder targets are whole % of threshold pace (no 88.9 %).
    targets = [t for block in threshold["structured_workout"]["structure"] for s in block["steps"]
               for t in s["targets"]]
    assert targets and all(type(t[k]) is int for t in targets for k in ("minValue", "maxValue"))
    # Whole-% targets read back within ±1 s/km of the coach's 4:45-4:52.
    assert threshold["structure_summary"] == (
        "15' WU · 4× (15\" @ 4:08–4:31/km / 45\" rec) · 4× (2 km @ 4:45–4:51/km / 2' rec) · 10' CD")
    assert {(n["field"], n["builder"]) for n in result["totals_from_builder"]} == {("distance_km", 13.09), ("duration_minutes", 72)}
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
    assert update_kw["title"] == "Threshold 4x2km" and update_kw["duration_minutes"] == 76
    assert update_kw["distance_km"] == 13.78 and update_kw["tss_planned"] == 104
    assert "structure" not in update_kw and update_kw["structured_workout"]["primaryLengthMetric"] == "distance"
    assert all("structured_workout" not in r for r in applied["results"])  # bulky builder kept out of the result
    assert ctx.state[STAGED_CHANGES_STATE_KEY] is None
    assert ctx.state["applied_workout_changes"] == {"staged_id": staged_id, "applied": 4, "failed": 0}

    assert json.loads(asyncio.run(apply_staged_changes(ctx))) == {"success": False, "reason": "nothing_staged"}


# ------------------------------------------------------------------------------
# Coded replies (no LLM call after staging / applying)
# ------------------------------------------------------------------------------

def _fresh(ctx, coach_text: str = ""):
    """A new tool call: fresh actions, and the coach's text so far in this invocation."""
    ctx.actions.skip_summarization, ctx.ui_widgets = None, []
    ctx.session.events = [Event(invocation_id=ctx.invocation_id, author="coaching_agent",
                                content=types.Content(role="model", parts=[types.Part(text=coach_text)]))]
    return ctx


def _stage_with(ctx, changes, message: str) -> dict:
    return json.loads(asyncio.run(stage_workout_changes(ctx, changes, message=message)))


def test_staging_ends_the_turn_in_one_call_with_the_coaching_message(runner):
    ctx = runner.ctx()
    tue_id = next(w["id"] for w in runner.workouts if w["date"] == "2026-11-03" and w["sport"] == "Run")
    move = _stage(_fresh(ctx), [{"workout_id": tue_id, "date_str": "2026-11-04"}])  # plain move: no text needed
    assert "explain" not in move and ctx.actions.skip_summarization is True
    assert ctx.reply_text().startswith("📋 1 change staged.")

    new = [{"date_str": "2026-11-04", "title": "Recovery Run", "distance_km": 6, "structure": RECOVERY_6KM}]
    # The message argument is the coach's reply: shown above the coded line, and the turn ends (no 2nd call).
    why = "Swap in an easy 6 km: your TSB is -18."
    with_message = _stage_with(_fresh(ctx), new, why)
    assert "explain" not in with_message and ctx.actions.skip_summarization is True
    assert ctx.reply_text() == f"{why}\n\n📋 1 change staged. Review them below and press **Update TrainingPeaks** to apply."

    # No message: still one call, only the coded line (monitored via a trace attribute).
    without = _stage(_fresh(ctx), new)
    assert "explain" not in without and ctx.actions.skip_summarization is True
    assert ctx.reply_text().startswith("📋 1 change staged.")

    # Already written as text this turn: never shown twice.
    _stage_with(_fresh(ctx, why), new, why)
    assert ctx.reply_text().startswith("📋 1 change staged.") and why not in ctx.reply_text()

    ambiguous = _stage_with(_fresh(ctx), new + [{"date_str": "2026-11-09", "workout_id": "nope"}], why)
    assert ambiguous["not_found"] and ctx.actions.skip_summarization is None  # the coach fixes it first


def test_apply_replies_with_the_coded_confirmation_and_ends_the_turn(runner):
    ctx = runner.ctx()
    staged_id = _stage(_fresh(ctx), CHANGES)["staged_id"]
    asyncio.run(apply_staged_changes(_fresh(ctx), staged_id="00000000-0000-0000-0000-000000000000"))
    assert ctx.reply_text() == REPLACED_TEXT and ctx.actions.skip_summarization is True
    asyncio.run(apply_staged_changes(_fresh(ctx), staged_id=staged_id))
    assert ctx.reply_text().startswith("✅ **TrainingPeaks updated:**") and ctx.actions.skip_summarization is True
    asyncio.run(apply_staged_changes(_fresh(ctx)))
    assert ctx.reply_text() == NOTHING_STAGED_TEXT


def test_a_builder_far_from_the_stated_distance_goes_back_to_the_coach(runner):
    ctx = runner.ctx()
    long_run = {"date_str": "2026-11-04", "title": "Long Run 18 km", "distance_km": 18, "structure": RECOVERY_6KM}
    result = _stage(_fresh(ctx, "text"), [long_run])
    (need,) = result["needs_structure"]
    assert result["staged"] == 0 and "add up to 6 km but you stated 18 km" in need["why"]
    assert ctx.actions.skip_summarization is None  # the coach fixes the steps and stages again
    near = _stage(_fresh(ctx, "text"), [{**long_run, "title": "Recovery 6.5 km", "distance_km": 6.5}])
    assert near["staged"] == 1 and near["totals_from_builder"][0]["builder"] == 6.0  # 8%: note only


# ------------------------------------------------------------------------------
# Workout builder: exact numbers, never scaled
# ------------------------------------------------------------------------------

# A TrainingPeaks builder as stored (whole %): 15' WU, 5 x (10' @ 104-108 % / 2' jog), 10' CD.


# ------------------------------------------------------------------------------
# Deletes (staged for review, applied with the button)
# ------------------------------------------------------------------------------

def test_deletes_are_staged_resolved_and_applied(runner):
    ctx = runner.ctx()
    bike_id = next(w["id"] for w in runner.workouts if w["date"] == "2026-11-05" and w["sport"] == "Bike")
    result = _stage(_fresh(ctx, "Rest day Friday."), [
        {"date_str": "2026-11-06", "sport": "Run", "delete": True},           # by date + sport
        {"workout_id": bike_id, "delete": True},                               # by id
        {"kind": "note", "date_str": "2026-11-01", "title": "Berlin", "delete": True},
    ])
    assert result["staged"] == 3 and _writes(runner) == []
    by_title = {c["title"]: c for c in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]}
    assert {c["action"] for c in by_title.values()} == {"delete"} and set(by_title) == {"Easy Run", "Z2 Spin", "Work trip to Berlin"}
    assert by_title["Easy Run"]["replaces"]["distance_km"] == 8.0 and by_title["Work trip to Berlin"]["note_id"] == "n2"

    applied = json.loads(asyncio.run(apply_staged_changes(_fresh(ctx))))
    assert applied["success"] is True
    assert sorted(n for n, _ in runner.tp_calls if n.startswith("tp_delete")) == [
        "tp_delete_note", "tp_delete_workout", "tp_delete_workout"]
    text = ctx.reply_text()
    assert text.startswith("✅ **TrainingPeaks updated:** 2 workouts (2 deleted) and 1 note.")
    assert "| Deleted | Fri 06 Nov | **Easy Run** · 8 km" in text and "🗑️ Note removed: Sun 01 Nov" in text


def test_completed_workouts_are_never_deleted_and_several_matches_ask(runner):
    ctx = runner.ctx()
    refused = _stage(_fresh(ctx, "text"), [{"date_str": "2026-10-26", "sport": "Run", "delete": True}])
    assert refused["staged"] == 0 and refused["refused"][0]["reason"] == "cannot_delete_completed"
    assert ctx.actions.skip_summarization is None  # the coach tells the runner it stays

    runner.workouts.append({"id": "pm-run", "date": "2026-11-06", "sport": "Run", "title": "PM Shakeout",
                            "type": "planned"})
    (ambiguous,) = _stage(_fresh(ctx, "text"), [{"date_str": "2026-11-06", "delete": True}])["ambiguous"]
    assert {c["title"] for c in ambiguous["candidates"]} == {"Easy Run", "PM Shakeout"}


def test_the_confirmation_is_only_the_table_without_a_builder_block(runner):
    ctx = runner.ctx()
    staged_id = _stage(_fresh(ctx), CHANGES)["staged_id"]
    asyncio.run(apply_staged_changes(_fresh(ctx), staged_id=staged_id))
    assert "| Change | Date | Before | After |" in ctx.reply_text()
    assert "Workout builder" not in ctx.reply_text()
