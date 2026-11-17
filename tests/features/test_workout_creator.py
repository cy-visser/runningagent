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


def test_compact_session_codes_stage_multi_week_audit_changes_in_one_call(runner):
    ctx = runner.ctx()
    audit_deltas = [
        {"date_str": "2026-11-02", "code": "E 8"},                       # updates Mon easy run
        {"date_str": "2026-11-03", "code": "T 4x2k r2'"},                # updates Tue threshold (keeps custom strides)
        {"date_str": "2026-11-03", "code": "S 40' heavy-lower", "create": True},  # infers sport='Strength'
        {"date_str": "2026-11-04", "code": "X 40' swim"},                # infers sport='Swim'
        {"date_str": "2026-11-05", "code": "B 60' Z2"},                  # updates Thu bike
        {"date_str": "2026-11-06", "code": "REST"},                      # deletes Fri easy run
        {"date_str": "2026-11-07", "code": "L 22 +6@M"},                 # updates Sat long run
        {"date_str": "2026-11-10", "code": "I 5x1k r2'"},                # creates next-week Tue VO2max
    ]
    result = _stage_with(_fresh(ctx), audit_deltas, "Trimmed Friday to protect Sunday's marathon-pace long run.")

    assert result["staged"] == 8 and ctx.actions.skip_summarization is True
    staged = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    by_day_sport = {(c["date"][:10], c["sport"]): c for c in staged}

    tue_run = by_day_sport[("2026-11-03", "Run")]
    assert tue_run["action"] == "update" and tue_run["title"] == "Threshold 4x2km"
    assert tue_run["strides_added"] == "kept"  # preserved 4x(15"/45") from existing TP workout
    assert "Plan code:" not in tue_run["description"]

    tue_str = by_day_sport[("2026-11-03", "Strength")]
    assert tue_str["action"] == "create" and tue_str["duration_minutes"] == 40 and tue_str["tss_planned"] > 0

    wed_swim = by_day_sport[("2026-11-04", "Swim")]
    assert wed_swim["action"] == "create" and wed_swim["duration_minutes"] == 40

    fri_del = by_day_sport[("2026-11-06", "Run")]
    assert fri_del["action"] == "delete" and fri_del["replaces"]["title"] == "Easy Run"

    sat_lr = by_day_sport[("2026-11-07", "Run")]
    assert sat_lr["distance_km"] == 22.0 and "@M" in sat_lr["title"]


def test_targetless_non_active_steps_default_cleanly_and_post_stride_totals_pass(runner):
    ctx = runner.ctx()
    # Warm-up, rest, and cool-down omit pace/intensity_min; stated 76 min includes kept/added strides.
    intervals = {
        "steps": [
            {"name": "Warm up", "intensityClass": "warmUp", "duration_seconds": 900},
            {
                "type": "repetition",
                "reps": 4,
                "steps": [
                    {"name": "Threshold", "intensityClass": "active", "distance_m": 2000, "pace": "4:45-4:52"},
                    {"name": "Jog", "intensityClass": "rest", "duration_seconds": 120},
                ],
            },
            {"name": "Cool down", "intensityClass": "coolDown", "duration_seconds": 600},
        ]
    }
    result = _stage(_fresh(ctx), [{"date_str": "2026-11-03", "duration_minutes": 77, "structure": intervals}])
    assert result["staged"] == 1 and "needs_structure" not in result


def test_needs_structure_retry_reuses_tp_cache_and_merges_delta_only_fix(runner):
    ctx = runner.ctx()
    initial = [
        {"date_str": "2026-11-02", "code": "E 8"},
        {"date_str": "2026-11-03", "code": "T 3x2k r2'"},
        {"date_str": "2026-11-04", "title": "Broken Run", "distance_km": 10},  # missing code & structure
    ]
    first = _stage_with(_fresh(ctx), initial, "Adjusted volume after audit.")
    assert first["staged"] == 0 and first["ready"] == 2
    assert [n["date_str"] for n in first["needs_structure"]] == ["2026-11-04"]

    runner.tp_calls.clear()
    ctx.actions.skip_summarization, ctx.ui_widgets = None, []
    # Retry sends ONLY the 1 fixed item (no message repeated): zero TP MCP calls, merges all 3 items.
    second = _stage(ctx, [{"date_str": "2026-11-04", "code": "R 6"}])
    assert runner.tp_calls == []
    assert second["staged"] == 3 and ctx.actions.skip_summarization is True
    assert "Adjusted volume after audit." in (ctx.reply_text() or "")
    assert [c["date"][:10] for c in ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]] == [
        "2026-11-02",
        "2026-11-03",
        "2026-11-04",
    ]


def test_from_date_str_moves_and_swaps_preserve_workouts_in_one_call_with_compact_llm_result(runner):
    # Add an evening Strength workout on Saturday 2026-11-07 alongside Saturday's Long Run.
    runner.workouts.append({
        "id": "w_sat_str", "date": "2026-11-07", "sport": "Strength",
        "title": "Heavy Machine & Unilateral S&C", "type": "planned",
        "duration_planned": 0.75, "tss_planned": 30.0,
        "description": "Basic Fit Heavy Machine & Unilateral S&C Protocol",
    })
    ctx = runner.ctx()

    # 1. Strength-only move via from_date_str skips tp_get_athlete_settings and keeps exact workout_id/totals.
    str_move = _stage(_fresh(ctx), [
        {"from_date_str": "2026-11-07", "sport": "Strength", "date_str": "2026-11-06"},
    ])
    assert str_move["staged"] == 1 and ctx.actions.skip_summarization is True
    assert [name for name, _ in runner.tp_calls] == ["tp_get_workouts"]
    (moved_str,) = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    assert moved_str["action"] == "update" and moved_str["workout_id"] == "w_sat_str"
    assert moved_str["date"] == "2026-11-06" and moved_str["replaces"]["date"] == "2026-11-07"
    assert moved_str["description_summary"] == "Basic Fit Heavy Machine & Unilateral S&C Protocol"
    assert all(isinstance(line, str) and "[w_sat_str]" in line and "2026-11-07->2026-11-06" in line
               for line in str_move["changes"])

    # 2. Cross-sport swap (Thu Bike <-> Fri Run) + same-sport swap (Mon Run <-> Tue Run) in ONE call, without ids!
    runner.tp_calls.clear()
    swap_res = _stage_with(_fresh(ctx), [
        {"from_date_str": "2026-11-05", "sport": "Bike", "date_str": "2026-11-06"},
        {"from_date_str": "2026-11-06", "sport": "Run", "date_str": "2026-11-05"},
        {"from_date_str": "2026-11-02", "sport": "Run", "date_str": "2026-11-03"},
        {"from_date_str": "2026-11-03", "sport": "Run", "date_str": "2026-11-02"},
    ], "Swapped sessions to open > 48 h recovery.")
    assert swap_res["staged"] == 4 and ctx.actions.skip_summarization is True
    staged = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    assert {(c["replaces"]["date"], c["date"], c["sport"], c["title"]) for c in staged} == {
        ("2026-11-05", "2026-11-06", "Bike", "Z2 Spin"),
        ("2026-11-06", "2026-11-05", "Run", "Easy Run"),
        ("2026-11-02", "2026-11-03", "Run", "Easy Aerobic Run"),
        ("2026-11-03", "2026-11-02", "Run", "Threshold 2 x 15'"),
    }
    # Compact LLM response is a flat list of short one-line strings (< 450 chars total), while state holds full dicts.
    assert all(isinstance(s, str) for s in swap_res["changes"])
    assert len(json.dumps(swap_res)) < 650

    # Applying writes 4 clean tp_update_workout moves (zero deletes, zero creates!).
    runner.tp_calls.clear()
    applied = json.loads(asyncio.run(apply_staged_changes(_fresh(ctx))))
    assert applied["success"] is True
    assert [name for name, _ in runner.tp_calls] == ["tp_update_workout"] * 4
    assert ctx.reply_text().count("| Moved |") == 4

    # 3. Missing or ambiguous from_date_str reports clean errors without creating duplicates.
    not_found = _stage(_fresh(ctx), [{"from_date_str": "2026-11-04", "sport": "Run", "date_str": "2026-11-05"}])
    assert not_found["staged"] == 0 and not_found["not_found"][0]["date_str"] == "2026-11-04"

    runner.workouts.append({"id": "pm-run", "date": "2026-11-06", "sport": "Run", "title": "PM Shakeout",
                            "type": "planned"})
    ambig = _stage(_fresh(ctx), [{"from_date_str": "2026-11-06", "sport": "Run", "date_str": "2026-11-04"}])
    assert ambig["staged"] == 0 and ambig["ambiguous"][0]["reason"] == "needs_workout_id"


def test_stage_workout_changes_resolves_goal_pace_for_workout_date_and_long_run_blocks(runner):
    from running_coach.tests.fakes import PLAN_PROFILE

    profile = {
        **PLAN_PROFILE,
        "sub_goals": [
            {"goal": "Sub-1:40 Half Marathon", "race_date": "2027-06-12", "planned": True},
            {"goal": "Sub-1:30 Half Marathon", "race_date": "2027-10-31", "planned": True},
        ],
    }
    ctx = runner.ctx(profile=profile)
    res = _stage(ctx, [
        {"date_str": "2027-05-16", "code": "L 24 +3x3k@HM r1k"},
        {"date_str": "2027-10-03", "code": "L 26 +4x4k@HM r1k +2@E"},
    ])
    assert res["staged"] == 2
    may_lr, oct_lr = ctx.state[STAGED_CHANGES_STATE_KEY]["changes"]
    assert may_lr["distance_km"] == 24.0 and oct_lr["distance_km"] == 26.0
    may_hm_min = may_lr["structured_workout"]["structure"][1]["steps"][0]["targets"][0]["minValue"]
    oct_hm_min = oct_lr["structured_workout"]["structure"][1]["steps"][0]["targets"][0]["minValue"]
    assert oct_hm_min > may_hm_min  # Sub-1:30 October HM block gets faster @HM target than Sub-1:40 June block



