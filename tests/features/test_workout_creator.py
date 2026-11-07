"""Behavioural test for the workout creator: stage changes, apply them by code, coded confirmations."""

import asyncio
import copy
import json

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.features.workout_creator.apply_staged_changes_tool import apply_staged_changes
from running_coach.features.workout_creator.stage_workout_changes_tool import (
    STAGED_CHANGES_STATE_KEY,
    stage_workout_changes,
)
from running_coach.features.workout_creator.helpers.staged_changes import change_label
from running_coach.features.workout_creator.helpers.workout_builder import with_geometry
from running_coach.features.workout_creator.write_confirmation_callback import (
    EXPLAIN_STAGED_INSTRUCTION,
    NOTHING_STAGED_TEXT,
    REPLACED_TEXT,
    write_confirmation_reply,
)
from running_coach.integrations.trainingpeaks import tp_calls
from running_coach.shared.workout_structure import flatten_structure
from running_coach.tests.fakes import CANOVA, FakeContext, envelope

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
    # Totals follow the builder; the coach's 12 km / 65 min are reported back.
    assert (threshold["distance_km"], threshold["duration_minutes"], threshold["tss_planned"]) == (13.09, 71.9, 98.5)
    assert threshold["structure_summary"] == "15' WU · 4× (2 km @ 4:45–4:52/km / 2' rec) · 10' CD"
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


def test_staged_updates_carry_the_current_workout_for_the_web_card(runner):
    ctx = runner.ctx()
    result = _stage(ctx, CHANGES)
    by_title = {c["title"]: c for c in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]}
    # Current column: the planned values of the workout the update replaces (no extra TP read).
    assert by_title["Threshold 4x2km"]["replaces"] == {
        "title": "Threshold 2 x 15'", "date": "2026-11-03", "sport": "Run",
        "distance_km": 12.5, "duration_minutes": 63.0, "tss_planned": 82.0,
    }
    assert by_title["Recovery Run"].get("replaces") is None  # creates have no current workout
    assert next(c for c in result["changes"] if c["title"] == "Threshold 4x2km")["replaces"]["title"] == (
        "Threshold 2 x 15'")

    # Moving a workout within the staged range: the current date differs -> Moved.
    tuesday = _planned_id(runner, "2026-11-03")
    _stage(ctx, [{"date_str": "2026-11-03", "sport": "Strength", "title": "Core", "create": True},
                 {"date_str": "2026-11-05", "title": "Threshold (moved)", "workout_id": tuesday}])
    moved = next(c for c in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"] if c["title"] == "Threshold (moved)")
    assert moved["replaces"]["date"] == "2026-11-03" and change_label(moved) == "Moved"
    assert change_label({"action": "create"}) == "Created"
    assert change_label({"action": "update", "date": "2026-11-03", "replaces": {"date": "2026-11-03"}}) == "Updated"


def test_apply_writes_every_staged_change_clears_staging_and_handles_stale_buttons(runner):
    ctx = runner.ctx()
    staged_id = _stage(ctx, CHANGES)["staged_id"]

    stale = json.loads(asyncio.run(apply_staged_changes(ctx, staged_id="00000000-0000-0000-0000-000000000000")))
    assert stale == {"success": False, "reason": "replaced"} and _writes(runner) == []

    applied = json.loads(asyncio.run(apply_staged_changes(ctx, staged_id=staged_id)))
    assert applied["success"] is True and all(r["ok"] for r in applied["results"])
    assert sorted(_writes(runner)) == ["tp_create_note", "tp_create_workout", "tp_create_workout", "tp_update_workout"]
    update_kw = next(kw for name, kw in runner.tp_calls if name == "tp_update_workout")
    assert update_kw["title"] == "Threshold 4x2km" and update_kw["duration_minutes"] == 71.9
    assert update_kw["distance_km"] == 13.09 and update_kw["tss_planned"] == 98.5
    assert "structure" not in update_kw and update_kw["structured_workout"]["primaryLengthMetric"] == "distance"
    assert all("structured_workout" not in r for r in applied["results"])  # bulky builder kept out of the result
    assert ctx.state[STAGED_CHANGES_STATE_KEY] is None
    assert ctx.state["applied_workout_changes"] == {"staged_id": staged_id, "applied": 4, "failed": 0}

    assert json.loads(asyncio.run(apply_staged_changes(ctx))) == {"success": False, "reason": "nothing_staged"}


def test_apply_reports_partial_failures(runner, monkeypatch):
    async def flaky(tool_context, name, **kw):
        if name == "tp_create_note":
            return envelope({"isError": True, "message": "Note service unavailable"})
        return await runner.run_tp_tool(tool_context, name, **kw)

    monkeypatch.setattr(tp_calls, "run_tp_tool", flaky)
    ctx = runner.ctx()
    _stage(ctx, CHANGES)
    applied = json.loads(asyncio.run(apply_staged_changes(ctx)))
    failed = [r for r in applied["results"] if not r["ok"]]
    assert applied["success"] is True and [r["title"] for r in failed] == ["Travel: Milan"]
    assert failed[0]["error"] == "Note service unavailable"


def test_bare_move_to_another_date_shows_the_session_and_writes_only_the_date(runner):
    # The traced request: "move the 5k of Nov 25th to Nov 26th" staged as {date_str, workout_id, sport}
    # only. The workout sits on another date than the staged one, outside the fetched range.
    tuesday = _planned_id(runner, "2026-11-03")
    ctx = runner.ctx()
    result = _stage(ctx, [{"date_str": "2026-11-05", "workout_id": tuesday, "sport": "Run"}])

    # One parallel TrainingPeaks round: the moved workout is read with the calendar.
    assert sorted(name for name, _ in runner.tp_calls) == ["tp_get_athlete_settings", "tp_get_workout", "tp_get_workouts"]
    (change,) = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    current = change["replaces"]
    assert (current["title"], current["date"], current["distance_km"], current["duration_minutes"],
            current["tss_planned"]) == ("Threshold 2 x 15'", "2026-11-03", 12.5, 63.0, 82.0)
    assert current["structure_summary"] and current["description_summary"].startswith("Warm up 15 min easy")
    # The proposed side is the same session (never "Planned Run" with no details).
    assert change["title"] == "Threshold 2 x 15'" and change["structure_summary"] == current["structure_summary"]
    assert (change["distance_km"], change["duration_minutes"], change["tss_planned"]) == (12.5, 63.0, 82.0)
    assert set(change["inherited"]) == {"title", "distance_km", "duration_minutes", "tss_planned"}
    assert change_label(change) == "Moved" and "structured_workout" not in change
    assert result["edit_only"] is True and result["changes"][0]["replaces"]["date"] == "2026-11-03"

    # Applying writes only the move: TrainingPeaks keeps the title, totals and builder.
    asyncio.run(apply_staged_changes(ctx))
    update_kw = next(kw for name, kw in runner.tp_calls if name == "tp_update_workout")
    assert update_kw == {"date": "2026-11-05", "sport": "Run", "workout_id": tuesday}


def test_unknown_workout_id_is_not_staged(runner):
    ctx = runner.ctx()
    result = _stage(ctx, [{"date_str": "2026-11-05", "workout_id": "nope", "sport": "Run"}])
    assert result["staged"] == 0 and STAGED_CHANGES_STATE_KEY not in ctx.state
    (missing,) = result["not_found"]
    assert missing["reason"] == "workout_not_found" and missing["workout_id"] == "nope"
    assert "not_found" in result["message"] and "ambiguous" not in result
    # The LLM gets the turn to fix it (no coded reply).
    call = types.Part(function_call=types.FunctionCall(name="stage_workout_changes"))
    partial = _response("stage_workout_changes", {"staged": 1, "not_found": result["not_found"]})
    assert _reply_text(_request(RUNNER_MSG, types.Content(role="model", parts=[call]),
                                types.Content(role="user", parts=[partial]))) is None


def test_new_content_with_coach_totals_is_not_an_edit_only_set(runner):
    ctx = runner.ctx()
    tuesday = _planned_id(runner, "2026-11-03")
    result = _stage(ctx, [{"date_str": "2026-11-05", "workout_id": tuesday, "title": "Threshold 5x12'",
                           "structure": THRESHOLD_4X2KM}])
    (change,) = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    assert "edit_only" not in result and "inherited" not in change  # builder totals are written
    assert change["structure_summary"] == "15' WU · 4× (2 km @ 4:45–4:52/km / 2' rec) · 10' CD"
    assert change["replaces"]["structure_summary"] != change["structure_summary"]
    assert "totals_from_builder" not in result  # inherited totals are not the coach's numbers


# ------------------------------------------------------------------------------
# Coded replies (no LLM call after staging / applying)
# ------------------------------------------------------------------------------

def _response(name: str, payload: dict) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(name=name, response={"result": json.dumps(payload)}))


def _request(*contents: types.Content) -> LlmRequest:
    return LlmRequest(contents=list(contents))


RUNNER_MSG = types.Content(role="user", parts=[types.Part(text="What should I fix?")])


def _reply_text(req: LlmRequest):
    resp = write_confirmation_reply(FakeContext(), req)
    return None if resp is None else "".join(p.text or "" for p in resp.content.parts)


def test_apply_response_gets_a_coded_confirmation_table(runner):
    ctx = runner.ctx()
    _stage(ctx, CHANGES)
    payload = json.loads(asyncio.run(apply_staged_changes(ctx)))
    text = _reply_text(_request(
        types.Content(role="user", parts=[types.Part(text="Update TrainingPeaks")]),
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="apply_staged_changes"))]),
        types.Content(role="user", parts=[_response("apply_staged_changes", payload)]),
    ))
    assert text.startswith("✅ **TrainingPeaks updated:** 3 workouts and 1 note.")
    assert "| Change | Date | Before | After |" in text
    assert ("| Updated | Tue 03 Nov | **Threshold 2 x 15'** · 12.5 km · 63 min · TSS 82 | "
            "**Threshold 4x2km** · 13.1 km · 71.9 min · TSS 98.5 |") in text
    assert "| Created | Wed 04 Nov | – | **Recovery Run** · 6 km · 39 min · TSS 37.7 |" in text
    assert "| Created | Tue 03 Nov | – | **Core & Hips** · Strength |" in text
    assert "**Workout builder:**" in text
    assert "- Tue 03 Nov · Threshold 4x2km: 15' WU · 4× (2 km @ 4:45–4:52/km / 2' rec) · 10' CD" in text
    assert "- Wed 04 Nov · Recovery Run: 6 km @ 6:00–6:30/km" in text
    assert "📝 Note added: Wed 04 Nov · Travel: Milan" in text
    # Rows follow the calendar.
    assert text.index("Tue 03 Nov") < text.index("| Wed 04 Nov")

    replaced = _request(RUNNER_MSG, types.Content(role="user", parts=[
        _response("apply_staged_changes", {"success": False, "reason": "replaced"})]))
    assert _reply_text(replaced) == REPLACED_TEXT
    nothing = _request(RUNNER_MSG, types.Content(role="user", parts=[
        _response("apply_staged_changes", {"success": False, "reason": "nothing_staged"})]))
    assert _reply_text(nothing) == NOTHING_STAGED_TEXT


def test_stage_response_is_coded_only_after_the_recommendations_were_written():
    staged = _response("stage_workout_changes", {"staged": 3, "staged_id": "x"})
    call = types.Part(function_call=types.FunctionCall(name="stage_workout_changes"))

    with_text = _request(RUNNER_MSG, types.Content(role="model", parts=[types.Part(text="### Recommendations ..."), call]),
                         types.Content(role="user", parts=[staged]))
    assert _reply_text(with_text) == (
        "📋 3 changes staged. Review them below and press **Update TrainingPeaks** to apply."
    )
    # Staged before writing anything: the LLM call goes ahead, tools off, told to write the reasoning.
    no_text = _request(RUNNER_MSG, types.Content(role="model", parts=[call]), types.Content(role="user", parts=[staged]))
    assert _reply_text(no_text) is None
    assert no_text.config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.NONE
    assert EXPLAIN_STAGED_INSTRUCTION in str(no_text.config.system_instruction)
    assert with_text.config.tool_config is None  # the coded line case never touches the request
    # A plain move / rename the runner asked for: coded line, no explanation call.
    edit = _response("stage_workout_changes", {"staged": 1, "staged_id": "x", "edit_only": True})
    edit_req = _request(RUNNER_MSG, types.Content(role="model", parts=[call]), types.Content(role="user", parts=[edit]))
    assert _reply_text(edit_req) == "📋 1 change staged. Review them below and press **Update TrainingPeaks** to apply."
    assert edit_req.config.tool_config is None
    # Ambiguous changes: the LLM asks the runner which workout.
    ambiguous = _response("stage_workout_changes", {"staged": 1, "ambiguous": [{"reason": "needs_workout_id"}]})
    assert _reply_text(_request(RUNNER_MSG, types.Content(role="model", parts=[types.Part(text="Plan"), call]),
                                types.Content(role="user", parts=[ambiguous]))) is None
    # Another tool in the same step, or a plain runner message: the LLM runs.
    mixed = types.Content(role="user", parts=[staged, _response("get_weather", {"ok": True})])
    assert _reply_text(_request(RUNNER_MSG, types.Content(role="model", parts=[types.Part(text="Plan"), call]), mixed)) is None
    assert _reply_text(_request(RUNNER_MSG)) is None


# ------------------------------------------------------------------------------
# Workout builder: exact numbers, never scaled
# ------------------------------------------------------------------------------

# A TrainingPeaks builder as stored (whole %): 15' WU, 5 x (10' @ 104-108 % / 2' jog), 10' CD.
FIVE_BY_TEN = {
    "structure": [
        {"type": "step", "length": {"value": 1, "unit": "repetition"}, "begin": 0, "end": 2400, "steps": [
            {"name": "Warm up", "length": {"value": 900, "unit": "second"}, "targets": [{"minValue": 75, "maxValue": 81}],
             "intensityClass": "warmUp", "openDuration": False}]},
        {"type": "repetition", "length": {"value": 5, "unit": "repetition"}, "begin": 2400, "end": 12000, "steps": [
            {"type": "step", "name": "Threshold", "length": {"value": 600, "unit": "second"},
             "targets": [{"minValue": 104, "maxValue": 108}], "intensityClass": "active", "openDuration": False},
            {"type": "step", "name": "Jog", "length": {"value": 120, "unit": "second"},
             "targets": [{"minValue": 68, "maxValue": 76}], "intensityClass": "rest", "openDuration": False}]},
        {"type": "step", "length": {"value": 1, "unit": "repetition"}, "begin": 12000, "end": 13600, "steps": [
            {"name": "Cool down", "length": {"value": 600, "unit": "second"}, "targets": [{"minValue": 75, "maxValue": 81}],
             "intensityClass": "coolDown", "openDuration": False}]},
    ],
    "polyline": [], "primaryLengthMetric": "distance", "primaryIntensityMetric": "percentOfThresholdPace",
    "primaryIntensityTargetOrRange": "range", "visualizationDistanceUnit": "kilometer",
}


def _planned_id(runner, day: str, sport: str = "Run") -> str:
    return next(w["id"] for w in runner.workouts if w["date"] == day and w["sport"] == sport)


def test_coach_builder_is_written_exactly_with_totals_from_it(runner):
    ctx = runner.ctx()
    structure = {"steps": [
        {"name": "Warm up", "intensityClass": "warmUp", "duration_seconds": 900, "pace": "5:50-6:20"},
        {"type": "repetition", "reps": 5, "steps": [
            {"name": "Threshold", "intensityClass": "active", "duration_seconds": 720, "pace": "4:25-4:35"},
            {"name": "Jog", "intensityClass": "rest", "duration_seconds": 120, "pace": "6:15-7:00"}]},
        {"name": "Cool down", "intensityClass": "coolDown", "duration_seconds": 600, "pace": "4:30"},
    ]}
    result = _stage(ctx, [{"date_str": "2026-11-03", "title": "Threshold 5x12'", "structure": structure}])
    (change,) = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    native = change["structured_workout"]

    # Exact lengths; paces as % of threshold pace (4:45/km) with one decimal; the 5 keys the MCP requires.
    assert {"structure", "polyline", "primaryLengthMetric", "primaryIntensityMetric",
            "primaryIntensityTargetOrRange"} <= set(native)
    reps = native["structure"][1]
    assert reps["length"] == {"value": 5, "unit": "repetition"}
    assert reps["steps"][0]["length"] == {"value": 720, "unit": "second"}
    assert reps["steps"][0]["targets"] == [{"minValue": 103.6, "maxValue": 107.5}]
    assert native["structure"][2]["steps"][0]["targets"] == [{"minValue": 105.5, "maxValue": 105.5}]  # single 4:30
    assert native["polyline"][0] == [0, 0] and native["polyline"][-1] == [1, 0]
    # The analysis side reads it back step by step.
    steps = flatten_structure(native)
    assert len(steps) == 12 and [s.length_s for s in steps[1:3]] == [720.0, 120.0]
    assert change["structure_summary"] == "15' WU · 5× (12' @ 4:25–4:35/km / 2' rec) · 10' CD"
    assert result["changes"][0]["distance_km"] == change["distance_km"] and change["duration_minutes"] == 95.0

    # Same arithmetic as TrainingPeaks: the Canova builder's stored begin/end are reproduced exactly.
    canova = with_geometry(copy.deepcopy(CANOVA["structured_workout"]), {"threshold_speed": 3.448})
    assert [(b["begin"], b["end"]) for b in canova["structure"]] == [
        (b["begin"], b["end"]) for b in CANOVA["structured_workout"]["structure"]]

    asyncio.run(apply_staged_changes(ctx))
    update_kw = next(kw for name, kw in runner.tp_calls if name == "tp_update_workout")
    assert update_kw["structured_workout"] == native and "structure" not in update_kw


def test_changed_distance_without_builder_returns_the_exact_current_builder(runner):
    tuesday = _planned_id(runner, "2026-11-03")
    runner.builders[tuesday] = FIVE_BY_TEN
    ctx = runner.ctx()

    result = _stage(ctx, [{"date_str": "2026-11-03", "title": "Threshold 5x12'", "duration_minutes": 87}])
    assert result["staged"] == 0 and STAGED_CHANGES_STATE_KEY not in ctx.state  # nothing the runner could apply
    (needs,) = result["needs_structure"]
    assert needs["why"] == "distance/duration changed" and needs["workout_id"] == tuesday
    assert [name for name, kw in runner.tp_calls if name == "tp_get_workout"] == ["tp_get_workout"]
    current = needs["current_structure"]
    work = current["steps"][1]["steps"][0]
    assert current["steps"][1]["reps"] == 5
    assert (work["duration_seconds"], work["intensity_min"], work["intensity_max"]) == (600, 104, 108)
    assert work["pace"] == "4:24–4:34"  # read-only hint

    # The coach edits only the rep length; untouched steps keep their exact stored targets.
    work["duration_seconds"] = 720
    again = _stage(ctx, [{"date_str": "2026-11-03", "title": "Threshold 5x12'", "structure": current}])
    assert again["staged"] == 1
    native = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"][0]["structured_workout"]
    assert native["structure"][1]["steps"][0]["length"] == {"value": 720, "unit": "second"}
    for new_block, old_block in zip(native["structure"], FIVE_BY_TEN["structure"]):
        assert [s["targets"] for s in new_block["steps"]] == [s["targets"] for s in old_block["steps"]]
        assert [s["name"] for s in new_block["steps"]] == [s["name"] for s in old_block["steps"]]

    # A rename or a move with unchanged totals keeps the builder: no builder written, and the workout is
    # read only in the first (parallel) round to show it on the card.
    runner.tp_calls.clear()
    renamed = _stage(ctx, [{"date_str": "2026-11-03", "title": "Threshold (renamed)", "workout_id": tuesday}])
    assert renamed["staged"] == 1 and "structured_workout" not in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"][0]
    moved = _stage(ctx, [{"date_str": "2026-11-12", "title": "Threshold (moved)", "workout_id": tuesday}])
    assert moved["staged"] == 1 and "structured_workout" not in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"][0]
    assert [name for name, _ in runner.tp_calls].count("tp_get_workout") == 2  # one per staging call


def test_run_and_bike_changes_without_a_usable_builder_go_back_to_the_coach(runner):
    ctx = runner.ctx()
    bad = {"steps": [{"name": "Tempo", "distance_m": 5000, "duration_seconds": 1500, "pace": "4:40-4:50"}]}
    result = _stage(ctx, [
        {"date_str": "2026-11-04", "title": "Recovery Run", "distance_km": 6},
        {"date_str": "2026-11-08", "title": "Tempo", "structure": bad},
        {"date_str": "2026-11-03", "sport": "Strength", "title": "Core & Hips", "create": True},
    ])
    assert result["staged"] == 0 and _writes(runner) == []
    whys = {n["title"]: n["why"] for n in result["needs_structure"]}
    assert whys["Recovery Run"] == "missing"
    assert whys["Tempo"] == "invalid: steps[1]: give exactly one of distance_m or duration_seconds"
    assert "Core & Hips" not in whys and result["ready"] == 1  # strength needs no builder
    assert "Do not ask the runner" in result["message"]

    # The LLM gets the turn to re-stage with builders (no coded "staged" reply).
    call = types.Part(function_call=types.FunctionCall(name="stage_workout_changes"))
    pending = _response("stage_workout_changes", {"staged": 2, "needs_structure": result["needs_structure"]})
    assert _reply_text(_request(RUNNER_MSG, types.Content(role="model", parts=[types.Part(text="Plan"), call]),
                                types.Content(role="user", parts=[pending]))) is None

    # A coach that keeps staging without a usable builder is stopped by code after 3 attempts in the turn.
    retry = [{"date_str": "2026-11-04", "title": "Recovery Run", "distance_km": 6}]
    assert "give_up" not in _stage(ctx, retry)  # 2nd attempt in this turn
    stuck = _stage(ctx, retry)                  # 3rd attempt
    assert stuck["give_up"] is True
    text = _reply_text(_request(RUNNER_MSG, types.Content(role="model", parts=[call]),
                                types.Content(role="user", parts=[_response("stage_workout_changes", stuck)])))
    assert text.startswith("⚠️ **Nothing was staged:**") and "- 2026-11-04 · Recovery Run: missing" in text
