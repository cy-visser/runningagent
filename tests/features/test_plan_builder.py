"""Behavioural tests for the plan builder: session codes, plan diff, staging, per-week apply and the guard."""

import asyncio
import json
from datetime import date

import pytest

from running_coach.features.plan_builder import apply_training_plan_tool as apply_module
from running_coach.features.plan_builder.apply_training_plan_tool import apply_training_plan
from running_coach.features.plan_builder.fetch_plan_context_tool import fetch_plan_context
from running_coach.features.plan_builder.helpers.pace_zones import resolve_zones
from running_coach.features.plan_builder.helpers.plan_diff import diff_week
from running_coach.features.plan_builder.helpers.plan_expand import expand_week, normalize_plan
from running_coach.features.plan_builder.helpers.session_codes import CodeError, build_session
from running_coach.features.plan_builder.stage_training_plan_tool import stage_training_plan
from running_coach.features.workout_creator.stage_workout_changes_tool import stage_workout_changes
from running_coach.shared.training_times import default_session_times
from running_coach.tests.fakes import PLAN_PROFILE, SETTINGS, TODAY, envelope

ZONES = resolve_zones(envelope(SETTINGS), PLAN_PROFILE, TODAY)
WRITES = ("tp_create_workout", "tp_update_workout", "tp_delete_workout", "tp_create_note", "tp_delete_note")


def _targets(native: dict) -> list[tuple[int, int]]:
    return [(s["targets"][0]["minValue"], s["targets"][0]["maxValue"])
            for b in native["structure"] for s in b["steps"]]


def _block_names(native: dict) -> list[str]:
    return [b["steps"][0]["name"] for b in native["structure"]]


# ------------------------------------------------------------------------------
# Session codes -> exact sessions
# ------------------------------------------------------------------------------

def test_every_code_type_builds_the_expected_session():
    easy = build_session("E 10", ZONES)
    assert (easy["sport"], easy["title"], easy["distance_km"]) == ("Run", "Easy Run 10 km", 10.0)
    assert _targets(easy["structured_workout"]) == [(75, 82)]
    assert easy["summary"] == "10 km @ 5:48–6:20/km" and "Plan code: E 10" in easy["description"]

    strides = build_session("E 50' +strides", ZONES)
    assert _block_names(strides["structured_workout"]) == ["Easy", "Stride"]

    long_mp = build_session("L 28 +8@M", ZONES)
    steps = [s for b in long_mp["structured_workout"]["structure"] for s in b["steps"]]
    assert [s["length"]["value"] for s in steps] == [20000, 8000] and long_mp["distance_km"] == 28.0
    assert _targets(long_mp["structured_workout"])[1] == tuple(ZONES["goal"]["M"]["pct"])  # Sub-3:15 goal pace
    assert ZONES["goal"]["M"]["source"] == "goal Sub-3:15 Marathon"

    threshold = build_session("T 2x15' r2'", ZONES)
    native = threshold["structured_workout"]
    # Warm-up, strides (shared.strides), main set, cool-down; totals from the builder.
    assert _block_names(native) == ["Warm up", "Stride", "Threshold", "Cool down"]
    assert native["structure"][2]["length"]["value"] == 2 and (97, 101) in _targets(native)
    assert threshold["title"] == "Threshold 2x15'" and threshold["duration_minutes"] == 63
    assert threshold["tss_planned"] and threshold["distance_km"]

    assert build_session("T 20'", ZONES)["title"] == "Tempo 20'"
    assert (106, 111) in _targets(build_session("I 6x1k r2'", ZONES)["structured_workout"])
    speed = build_session("Rp 10x200 r200", ZONES)["structured_workout"]
    assert _block_names(speed) == ["Warm up", "Stride", "Speed", "Cool down"]  # strides even on short reps
    assert speed["structure"][2]["steps"][1]["length"] == {"value": 200, "unit": "meter"}
    hm = build_session("P 4x2k@HM r2'", ZONES)
    assert hm["title"] == "HM Pace 4x2km" and tuple(ZONES["goal"]["HM"]["pct"]) in _targets(hm["structured_workout"])
    assert ZONES["goal"]["HM"]["source"] == "typical for the distance"  # no half-marathon goal: default ratio
    assert build_session("M 3x5k r1k", ZONES)["distance_km"] > 15
    hills = build_session('H 8x60" r90"', ZONES)
    assert hills["title"] == "Hill Reps 8x1'" and (100, 110) in _targets(hills["structured_workout"])

    race = build_session("RACE", ZONES, day=date(2027, 2, 14))
    assert (race["title"], race["distance_km"]) == ("Race: Schoorl 10K", 10.0)

    double = build_session("E 6 pm", ZONES)
    assert double["time"] == "18:00"


def test_bike_strength_and_cross_training_codes():
    ride = build_session("B 4x8' @SS r4'", ZONES)
    native = ride["structured_workout"]
    assert ride["sport"] == "Bike" and native["primaryIntensityMetric"] == "percentOfFtp"
    assert native["primaryLengthMetric"] == "duration" and (88, 94) in _targets(native)
    assert ride["duration_minutes"] == 73 and ride["distance_km"] is None
    steady = build_session("B 60' Z2", ZONES)
    assert steady["title"] == "Endurance Ride 60'" and _targets(steady["structured_workout"]) == [(56, 75)]

    build = build_session("S 45' heavy-lower", ZONES, phase="build 2")
    taper = build_session("S 45' heavy-lower", ZONES, phase="taper")
    base = build_session("S 45' heavy-lower", ZONES, phase="base")
    assert build["sport"] == "Strength" and build["structured_workout"] is None
    assert (build["duration_minutes"], build["tss_planned"]) == (45, 36)
    assert "Back squat 4x5" in build["description"] and "Activation" in taper["description"]
    assert len({build["description"], taper["description"], base["description"]}) == 3
    assert build_session("S 25' mobility", ZONES)["tss_planned"] < build_session("S 25' plyo", ZONES)["tss_planned"]

    swim = build_session("X 40' swim", ZONES)
    assert (swim["sport"], swim["duration_minutes"], swim["structured_workout"]) == ("Swim", 40, None)


@pytest.mark.parametrize("code", ["Q 3", "E", "P 4x1k", "S 40' legs day", "B 10k", "L 20 +25@M", "E 10 @Z9",
                                  "B 3x10' Z2", "X 30' karate", "I 60x400"])
def test_bad_codes_are_rejected_with_a_reason(code):
    with pytest.raises(CodeError) as err:
        build_session(code, ZONES)
    assert str(err.value)


def test_multi_session_days_rest_and_errors_expand_per_week():
    spec, errors = normalize_plan({"start_date": "2026-11-04", "weeks": [{"week": 1, "phase": "build", "days": {
        "monday": ["E 10"],                              # before the start date: skipped
        "Wed": ["B 45' Z2", "S 40' heavy-lower"],
        "Thu": "E 10 am, E 6 pm",
        "Fri": "REST",
        "Sat": ["REST", "E 5"],                          # REST shares a day: error
        "Sun": ["L 22", "Zz 3"],                         # bad code: error
    }}]})
    assert errors == [{"week": 1, "day": "Sat", "code": "REST, E 5", "why": "REST cannot share a day with sessions"}]
    week = expand_week(spec["weeks"][0], date(2026, 11, 2), ZONES, date(2026, 11, 4))
    assert [(s["day"], s["sport"]) for s in week["sessions"]] == [
        ("Wed", "Bike"), ("Wed", "Strength"), ("Thu", "Run"), ("Thu", "Run"), ("Sun", "Run")]
    assert week["sessions"][3]["write_date"] == "2026-11-05T18:00:00"
    assert week["rest"] == ["2026-11-06"] and week["skipped"] == 1 and week["days"][0] == "2026-11-04"
    (bad,) = week["errors"]
    assert (bad["day"], bad["code"]) == ("Sun", "Zz 3") and "unknown session type" in bad["why"]


def test_strength_sessions_list_their_exercises_and_mid_places_an_afternoon_session():
    build = build_session("S 45' heavy-lower mid", ZONES, phase="build")
    assert build["exercises"] == ["Back squat 4x5", "Deadlift 3x5", "Bulgarian split squat 3x6/leg",
                                  "Single-leg calf raise 3x10"]
    assert build["load"].startswith("RPE 8") and build["time"] == "13:00"
    assert build_session("S 20' core-hips", ZONES, phase="taper")["exercises"][0].startswith("Activation")


@pytest.mark.parametrize("profile, times", [
    ({"run_time_of_day": "morning", "strength_time_of_day": "evening"}, {"Run": "07:00", "Strength": "18:00"}),
    ({"run_time_of_day": "Evening", "strength_time_of_day": "morning"}, {"Run": "18:00", "Strength": "07:00"}),
    ({"run_time_of_day": "afternoon", "strength_time_of_day": "afternoon"}, {"Run": "13:00", "Strength": "14:30"}),
    ({"run_time_of_day": "morning"}, {}),                                    # both needed
    ({}, {}),
])
def test_default_session_times_follow_the_runners_training_times(profile, times):
    assert default_session_times(profile) == times


def test_double_days_are_timed_in_the_runners_order_and_explicit_tags_win():
    spec, errors = normalize_plan({"start_date": "2026-11-02", "weeks": [{"week": 1, "phase": "build", "days": {
        "Tue": ["I 6x1k r2'", "S 40' heavy-lower"],    # double day: run morning, strength evening
        "Wed": "S 30' core-hips",                       # strength only: untimed
        "Thu": ["T 2x15' r2'", "S 30' core-hips am"],   # explicit am wins for strength
        "Sat": ["B 45' Z2", "S 30' mobility"],           # no run: untimed
    }}]})
    assert not errors
    times = default_session_times({"run_time_of_day": "morning", "strength_time_of_day": "evening"})
    week = expand_week(spec["weeks"][0], date(2026, 11, 2), ZONES, date(2026, 11, 2), times)
    write = {(s["day"], s["sport"]): s["write_date"] for s in week["sessions"]}
    assert write[("Tue", "Run")] == "2026-11-03T07:00:00" and write[("Tue", "Strength")] == "2026-11-03T18:00:00"
    assert write[("Wed", "Strength")] == "2026-11-04"
    assert write[("Thu", "Run")] == "2026-11-05T07:00:00" and write[("Thu", "Strength")] == "2026-11-05T07:00:00"
    assert write[("Sat", "Bike")] == "2026-11-07" and write[("Sat", "Strength")] == "2026-11-07"
    # Without training times nothing is timed (today's behaviour).
    untimed = expand_week(spec["weeks"][0], date(2026, 11, 2), ZONES, date(2026, 11, 2))
    assert untimed["sessions"][0]["write_date"] == "2026-11-03"


# ------------------------------------------------------------------------------
# Plan diff: per day and per sport
# ------------------------------------------------------------------------------

def _w(wid, day, sport, title, km=None, hours=None, time="00:00:00", **extra):
    return {"id": wid, "date": day, "start_time": f"{day}T{time}", "sport": sport, "title": title,
            "type": "planned", "distance_planned_km": km, "duration_planned": hours, **extra}


def _diff(days: dict, workouts: list[dict], mode: str = "new") -> dict:
    spec, errors = normalize_plan({"start_date": "2026-11-02", "weeks": [{"week": 1, "phase": "build", "days": days}]})
    assert not errors
    week = expand_week(spec["weeks"][0], date(2026, 11, 2), ZONES, date(2026, 11, 2))
    return {(c["date"][5:], c["sport"], c["action"], c["title"], c["workout_id"]) for c in diff_week(week, workouts, mode)}


def test_diff_keeps_updates_creates_and_deletes_per_day_and_sport():
    easy = build_session("E 10", ZONES)
    workouts = [
        _w("same", "2026-11-02", "Run", "Easy Run 10 km", easy["distance_km"], easy["duration_minutes"] / 60),
        _w("old-tue", "2026-11-03", "Run", "Threshold 2 x 15'", 12.5, 1.05),
        _w("str-tue", "2026-11-03", "Strength", "Core"),
        _w("bike-wed", "2026-11-04", "Bike", "Z2 Spin", None, 1.0),
        _w("done-thu", "2026-11-05", "Run", "Easy", 8, 0.8, type="completed", distance_actual_km=8),
        _w("swim-thu", "2026-11-05", "Swim", "Swim"),
        _w("run-fri", "2026-11-06", "running", "Easy Run", 8, 0.7),
        _w("str-fri", "2026-11-06", "Strength", "Gym"),
        _w("swim-fri", "2026-11-06", "Swim", "Pool"),
        _w("swim-sat", "2026-11-07", "Swim", "Pool"),
    ]
    days = {"Mon": "E 10", "Tue": "I 6x1k r2'", "Wed": "E 8", "Thu": "REST", "Fri": "REST", "Sat": "X 40' swim"}
    new = _diff(days, workouts, "new")
    assert ("11-02", "Run", "keep", "Easy Run 10 km", "same") in new
    assert ("11-03", "Run", "update", "Intervals 6x1km", "old-tue") in new
    assert ("11-04", "Run", "create", "Easy Run 8 km", None) in new
    assert ("11-07", "Swim", "update", "Swim 40'", "swim-sat") in new           # an X code manages that sport that day
    deleted = {c[4] for c in new if c[2] == "delete"}
    # New mode: only REST removes, and only Run / Strength / Bike; completed workouts, Swim and the
    # Tuesday strength / Wednesday bike (not in the spec for that day) stay.
    assert deleted == {"run-fri", "str-fri"}

    overhaul = _diff(days, workouts, "overhaul")
    deleted = {c[4] for c in overhaul if c[2] == "delete"}
    assert deleted == {"run-fri", "str-fri", "str-tue", "bike-wed"}             # never completed or Swim workouts
    assert "done-thu" not in deleted and "swim-thu" not in deleted and "swim-fri" not in deleted


def test_two_sessions_of_one_sport_match_by_time_of_day_then_title():
    workouts = [_w("am", "2026-11-03", "Run", "Morning run", 10, 1.0, time="07:00:00"),
                _w("pm", "2026-11-03", "Run", "Shakeout", 5, 0.5, time="18:30:00")]
    by_time = _diff({"Tue": ["E 6 pm", "E 12 am"]}, workouts)
    assert {(c[3], c[4]) for c in by_time} == {("Easy Run 6 km", "pm"), ("Easy Run 12 km", "am")}

    recovery = build_session("R 6", ZONES)
    untimed = [_w("x", "2026-11-03", "Run", "Something", 9, 1.0),
               _w("rec", "2026-11-03", "Run", "Recovery Run 6 km", recovery["distance_km"],
                  recovery["duration_minutes"] / 60)]
    by_title = _diff({"Tue": ["E 10", "R 6"]}, untimed)
    assert {(c[2], c[3], c[4]) for c in by_title} == {("update", "Easy Run 10 km", "x"),
                                                     ("keep", "Recovery Run 6 km", "rec")}


# ------------------------------------------------------------------------------
# stage_training_plan
# ------------------------------------------------------------------------------

def _week(n: int, phase: str) -> dict:
    return {"week": n, "phase": phase, "focus": f"{phase} focus", "days": {
        "Mon": ["B 45' Z2", "S 40' heavy-lower"], "Tue": "I 6x1k r2'", "Wed": "E 10",
        "Thu": ["T 2x15' r2'", "S 30' core-hips"], "Fri": "REST", "Sat": "E 8 +strides", "Sun": "L 24 +6@M"}}


def _plan(weeks: int, mode: str = "new") -> dict:
    phases = ["base"] * (weeks // 3) + ["build"] * (weeks // 3)
    phases += ["peak"] * (weeks - len(phases) - min(2, weeks)) + ["taper"] * min(2, weeks)
    return {"start_date": "2026-11-02", "mode": mode, "weeks": [_week(i + 1, phases[i]) for i in range(weeks)]}


def _stage(ctx, plan, message="", base_staged_id="") -> dict:
    return json.loads(asyncio.run(stage_training_plan(ctx, plan, message=message, base_staged_id=base_staged_id)))


def _writes(runner) -> list[tuple[str, dict]]:
    return [(n, kw) for n, kw in runner.tp_calls if n in WRITES]


def test_a_24_week_plan_is_staged_compactly_with_one_line_per_week(runner):
    ctx = runner.ctx()
    message = "Base first, then MP work; heavy strength after the hard runs, bike as recovery."
    result = _stage(ctx, _plan(24), message)
    staged = ctx.state["staged_training_plan"]

    assert _writes(runner) == []
    assert len(json.dumps(staged)) < 100_000                                   # spec + zones, no native builders
    assert "structured_workout" not in json.dumps(staged)
    assert len(result["weeks"]) == 24 and all(line.startswith(f"W{i + 1} ") for i, line in enumerate(result["weeks"]))
    assert result["weeks"][0].startswith("W1 2026-11-02 base") and "sessions" in result["weeks"][0]
    totals = staged["totals"]
    assert (totals["weeks"], totals["sessions"]) == (24, 24 * 8)            # 8 sessions a week
    assert ctx.actions.skip_summarization is True
    assert ctx.reply_text() == (
        f"{message}\n\n- **24-week plan staged:** {totals['sessions']} sessions ({totals['create']} new · "
        f"{totals['update']} updated · {totals['delete']} removed). Review the weeks below and press "
        "**Apply to TrainingPeaks**.")
    w1 = staged["weeks"][0]
    assert (w1["start"], w1["phase"], w1["strength_sessions"], w1["bike_minutes"]) == ("2026-11-02", "base", 2, 45)
    assert [r["date"] for r in w1["rows"]] == sorted(r["date"] for r in w1["rows"])
    actions = {(r["date"], r["sport"], r["action"]) for r in w1["rows"]}
    # The fake calendar: Tue threshold -> update, Fri easy run on a REST day -> delete, Mon run kept (new mode).
    assert ("2026-11-03", "Run", "update") in actions and ("2026-11-06", "Run", "delete") in actions
    assert not any(r["date"] == "2026-11-02" and r["sport"] == "Run" for r in w1["rows"])
    assert staged["version"] == 1 and staged["title"] == "Sub-3:15 Marathon · 24 weeks"
    # The runner's training times (run morning, strength evening) time the Thu run + strength double; the card
    # lists the strength exercises.
    assert staged["spec"]["times"] == {"Run": "07:00", "Strength": "18:00"}
    thu = {r["sport"]: r for r in w1["rows"] if r["date"] == "2026-11-05"}
    assert (thu["Run"]["time"], thu["Strength"]["time"]) == ("07:00", "18:00")
    assert thu["Strength"]["exercises"][0] == "Dead bug 3x10/side" and thu["Strength"]["load"]


def test_compact_week_string_dsl_parses_identically_and_flags_bad_codes(runner):
    ctx = runner.ctx()
    res = _stage(ctx, {
        "start_date": "2026-11-02",
        "mode": "new",
        "weeks": [
            "W1 | base | Aerobic base; 2x strength | Mon: B 45' Z2; S 40' heavy-lower | Tue: I 6x1k r2' | Thu: T 2x15' r2'; S 30' core-hips | Fri: REST | Sun: L 24 +6@M",
            "W2 | build | 3:1 cutback: adaptation | Tu: T 3x10' r2' | Weds: E 8 | Th: E 10 +strides | Sun: L 26",
            "W3 | taper | Race week: Schoorl 10K | Tue: P 2x1k@10K r2' | Wed: E 6 | Thu: E 5 +strides | Sat: R 4 | Sun: RACE",
        ],
    })
    assert res["total_weeks"] == 3
    w1, w2, w3 = ctx.state["staged_training_plan"]["weeks"]
    assert (w1["phase"], w1["focus"], w1["strength_sessions"], w1["bike_minutes"]) == (
        "base", "Aerobic base; 2x strength", 2, 45
    )
    assert (w2["phase"], w2["focus"], w2["sessions"]) == ("build", "3:1 cutback: adaptation", 4)
    assert (w3["phase"], w3["focus"], w3["sessions"]) == ("taper", "Race week: Schoorl 10K", 5)

    bad_ctx = runner.ctx()
    bad = _stage(bad_ctx, {"start_date": "2026-11-02", "weeks": ["W1 | base | Focus | Funday: E 8"]})
    assert bad["staged"] == 0 and bad["errors"][0]["day"] == "Funday"

    bad_no_focus = _stage(runner.ctx(), {"start_date": "2026-11-02", "weeks": ["W1 | base | Funday: E 8"]})
    assert bad_no_focus["staged"] == 0 and bad_no_focus["errors"][0]["day"] == "Funday"


def test_base_staged_id_replaces_only_the_given_weeks(runner):
    ctx = runner.ctx()
    first = _stage(ctx, _plan(6))
    before = ctx.state["staged_training_plan"]
    easier = "W5 | recovery | Down week | Tue: E 8 | Thu: E 8 | Sun: L 16"
    second = _stage(ctx, {"weeks": [easier]}, "Week 5 becomes a down week.", base_staged_id=first["staged_id"])
    after = ctx.state["staged_training_plan"]
    assert second["staged_id"] != first["staged_id"] and after["staged_id"] == second["staged_id"]
    assert [w["rows"] for w in after["weeks"] if w["week"] != 5] == [w["rows"] for w in before["weeks"] if w["week"] != 5]
    week5 = next(w for w in after["weeks"] if w["week"] == 5)
    assert week5["phase"] == "recovery" and week5["sessions"] == 3
    stale = _stage(ctx, {"weeks": [easier]}, base_staged_id=first["staged_id"])
    assert stale["staged"] == 0 and "not the current staged plan" in stale["message"]
    via_alias = _stage(ctx, {"weeks": ["W4 | recovery | Cutback | Tue: E 7 | Sun: L 14"]}, base_staged_id="current")
    assert via_alias["total_weeks"] == 6 and ctx.state["staged_training_plan"]["weeks"][3]["phase"] == "recovery"


def test_bad_codes_stage_nothing_and_the_second_failure_stops_the_retries(runner):
    ctx = runner.ctx()
    bad = {"start_date": "2026-11-02", "weeks": [{"week": 1, "days": {"Tue": "I 6x1k r2'", "Wed": "Q 9"}}]}
    first = _stage(ctx, bad)
    assert first["staged"] == 0 and first["errors"][0]["code"] == "Q 9" and "give_up" not in first
    assert "staged_training_plan" not in ctx.state and ctx.actions.skip_summarization is None
    second = _stage(ctx, bad)
    assert second["give_up"] is True and ctx.actions.skip_summarization is True
    assert ctx.reply_text().startswith("⚠️ **Nothing was staged:**")


def test_fetch_plan_context_is_compact_and_feeds_the_plan_window(runner):
    ctx = runner.ctx()
    text = asyncio.run(fetch_plan_context(ctx, "2026-11-02", "2027-04-18", "overhaul"))
    assert "PLAN CONTEXT (overhaul): 2026-11-02 → 2027-04-18 · 24 weeks" in text
    assert "T 4:42–4:54/km" in text and "@M 4:34–4:39/km (goal Sub-3:15 Marathon)" in text
    assert "Bike (FTP 260 W)" in text and "strength" in text and "Long runs, last 6 weeks" in text
    assert "Training times: run morning · strength evening" in text and "Cross-training / strength" not in text
    assert "W1 2026-11-02: Mon Run 'Easy Aerobic Run' 10 km [w" in text      # ids in overhaul mode
    assert "W5–W24 (2026-11-30 → 2027-04-12): nothing planned" in text        # consecutive empty full weeks collapsed
    assert len(text) < 8000                                                   # ~1-2k tokens for 24 weeks
    cached = ctx.state["plan_context_cache"]
    assert (cached["start_date"], cached["end_date"], cached["mode"]) == ("2026-11-02", "2027-04-18", "overhaul")
    assert isinstance(cached["zones"], dict)
    # Staging in the same turn reuses both cached zones and temp:plan_workouts (zero extra TP MCP calls),
    # and keeps plan_context_cache active for iterative Turn 3+ revisions until workouts are applied!
    runner.tp_calls.clear()
    result = _stage(ctx, {"weeks": [_week(1, "base")]})
    assert runner.tp_calls == []
    assert result["total_weeks"] == 1 and ctx.state["staged_training_plan"]["mode"] == "overhaul"
    assert ctx.state["staged_training_plan"]["end_date"] == "2026-11-08"
    assert ctx.state["plan_context_cache"]["start_date"] == "2026-11-02"
    by_title = {r["title"]: r["category"] for r in ctx.state["staged_training_plan"]["weeks"][0]["rows"]}
    assert by_title["Intervals 6x1km"] == "quality" and by_title["Easy Run 10 km"] == "easy"
    assert by_title["Endurance Ride 45'"] == "bike" and by_title["Long Run 24 km (last 6 km @M)"] == "quality"
    # Applying the week writes to TrainingPeaks and clears plan_context_cache.
    _apply(ctx, result["staged_id"], 1)
    assert ctx.state["plan_context_cache"] is None
    new_text = asyncio.run(fetch_plan_context(runner.ctx(), "2026-11-02", "2026-11-29"))
    assert "[w" not in new_text.split("CALENDAR IN WINDOW")[1]               # no ids in new mode


def test_sunday_aug_1_new_plan_snaps_to_monday_aug_2_and_midweek_partial_weeks_clip_cleanly(runner):
    # 2027-08-01 is Sunday, 2027-10-31 is Sunday: new plan snaps start to Monday 2027-08-02 (13 full weeks, never 26 Jul).
    ctx = runner.ctx()
    text = asyncio.run(fetch_plan_context(ctx, "2027-08-01", "2027-10-31", "new"))
    assert "PLAN CONTEXT (new): 2027-08-02 → 2027-10-31 · 13 weeks (W1 = week of 2027-08-02)" in text
    assert "W1–W13 (2027-08-02 → 2027-10-25): nothing planned" in text
    assert "2027-07-26" not in text
    staged_res = _stage(ctx, {"start_date": "2027-08-01", "mode": "new", "weeks": [
        {"week": 1, "phase": "base", "days": {"Tue": "E 8", "Thu": "T 2x15' r2'", "Sun": "L 18"}},
    ]})
    assert staged_res["total_weeks"] == 1
    w1 = ctx.state["staged_training_plan"]["weeks"][0]
    assert w1["start"] == "2027-08-02"
    assert [r["date"] for r in w1["rows"]] == ["2027-08-03", "2027-08-05", "2027-08-08"]

    # Mid-week start (Wed 2026-11-04) + mid-week end (Fri 2026-11-13): partial W1 labelled, Sat/Sun of W2 clipped.
    mid_ctx = runner.ctx()
    mid_text = asyncio.run(fetch_plan_context(mid_ctx, "2026-11-04", "2026-11-13", "new"))
    assert "W1 partial: Wed 2026-11-04 → Sun 2026-11-08" in mid_text
    assert "W1 2026-11-04 (partial, Wed–Sun):" in mid_text
    _stage(mid_ctx, {"weeks": [
        {"week": 1, "phase": "base", "days": {"Mon": "E 8", "Wed": "E 8", "Sun": "L 16"}},
        {"week": 2, "phase": "base", "days": {"Tue": "E 8", "Fri": "RACE", "Sun": "E 6"}},
    ]})
    staged_mid = mid_ctx.state["staged_training_plan"]
    assert staged_mid["start_date"] == "2026-11-04" and staged_mid["end_date"] == "2026-11-13"
    assert [r["date"] for r in staged_mid["weeks"][0]["rows"] if r["action"] != "delete"] == ["2026-11-04", "2026-11-08"]
    assert [r["date"] for r in staged_mid["weeks"][1]["rows"] if r["action"] != "delete"] == ["2026-11-10", "2026-11-13"]


# ------------------------------------------------------------------------------
# apply_training_plan: one week per call
# ------------------------------------------------------------------------------

def _apply(ctx, staged_id, week) -> dict:
    ctx.actions.skip_summarization, ctx.ui_widgets = None, []
    return json.loads(asyncio.run(apply_training_plan(ctx, staged_id, week)))


def test_apply_writes_one_week_backs_off_on_429_and_is_idempotent(runner, monkeypatch):
    delays: list[float] = []

    async def no_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(apply_module, "_sleep", no_sleep)
    ctx = runner.ctx()
    staged_id = _stage(ctx, _plan(3, mode="overhaul"))["staged_id"]
    runner.tp_calls.clear()
    runner.write_429s = 2
    week2_ids = {w["id"] for w in runner.workouts if "2026-11-09" <= w["date"] <= "2026-11-15"}

    week2 = _apply(ctx, staged_id, 2)
    writes = _writes(runner)
    # Only week 2 is written: creates / updates dated in that week, deletes of that week's workouts.
    assert writes and all("2026-11-09" <= kw["date"][:10] <= "2026-11-15" for n, kw in writes if "date" in kw)
    assert {kw["workout_id"] for n, kw in writes if n == "tp_delete_workout"} <= week2_ids
    assert not any(n in ("tp_create_note", "tp_delete_note") for n, _ in writes)  # notes never touched
    assert len(delays) == 2 and delays[0] == 2                                    # two 429s, both retried
    assert week2["success"] is True and week2["failed"] == 0
    applied = ctx.state["applied_training_plan"]
    assert applied["weeks_done"] == [2] and applied["done"] is False and applied["failed_weeks"] == []
    assert applied["created"] + applied["updated"] + applied["deleted"] == len(writes) - 2
    assert ctx.reply_text() is None and ctx.actions.skip_summarization is True     # intermediate week: no bubble

    calls = len(runner.tp_calls)
    again = _apply(ctx, staged_id, 2)
    assert again["skipped"] == "already applied" and len(runner.tp_calls) == calls  # no-op
    assert ctx.reply_text() is None and ctx.actions.skip_summarization is True

    _apply(ctx, staged_id, 1)
    assert ctx.reply_text() is None
    _apply(ctx, staged_id, 3)
    applied = ctx.state["applied_training_plan"]
    assert applied["weeks_done"] == [1, 2, 3] and applied["done"] is True
    sessions = sum(w["sessions"] for w in ctx.state["staged_training_plan"]["weeks"])
    assert ctx.reply_text() == (
        f"✅ **TrainingPeaks updated:** 3 weeks · {sessions} sessions ({applied['created']} created, "
        f"{applied['updated']} updated, {applied['deleted']} removed).")

    assert _apply(ctx, "00000000-0000-0000-0000-000000000000", 1) == {"success": False, "reason": "replaced"}


def test_a_rate_limited_write_backs_off_2_4_8_seconds_then_gives_up(runner, monkeypatch):
    delays: list[float] = []

    async def no_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(apply_module, "_sleep", no_sleep)
    change = {"kind": "workout", "action": "create", "date": "2026-11-10", "sport": "Run", "title": "Easy Run 8 km",
              "workout_id": None, "distance_km": 8.0}
    runner.write_429s = 3
    ok = asyncio.run(apply_module._write_with_backoff(runner.ctx(), change, asyncio.Semaphore(3)))
    assert ok["ok"] is True and delays == [2, 4, 8]
    delays.clear()
    runner.write_429s = 4
    failed = asyncio.run(apply_module._write_with_backoff(runner.ctx(), change, asyncio.Semaphore(3)))
    assert failed["ok"] is False and "429" in failed["error"] and delays == [2, 4, 8]


def test_a_week_that_keeps_failing_goes_to_failed_weeks_for_resume(runner, monkeypatch):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(apply_module, "_sleep", no_sleep)
    ctx = runner.ctx()
    staged_id = _stage(ctx, _plan(2))["staged_id"]
    runner.failing_tools = {"tp_create_workout"}
    result = _apply(ctx, staged_id, 1)
    applied = ctx.state["applied_training_plan"]
    assert result["success"] is False and applied["failed_weeks"] == [1] and applied["weeks_done"] == []
    assert "Week 1 was not fully saved" in ctx.reply_text()
    runner.failing_tools = set()
    _apply(ctx, staged_id, 1)                                                     # Resume
    assert ctx.state["applied_training_plan"]["weeks_done"] == [1]
    assert ctx.state["applied_training_plan"]["failed_weeks"] == []


# ------------------------------------------------------------------------------
# Guard: workout-creator hands big sets to plan-builder
# ------------------------------------------------------------------------------

def test_stage_workout_changes_redirects_big_sets_to_plan_builder(runner):
    eleven = [{"date_str": f"2026-11-0{2 + i % 6}", "title": f"Run {i}", "create": True,
               "structure": {"steps": [{"name": "Easy", "distance_m": 5000, "pace": "6:00-6:20"}]}}
              for i in range(11)]
    ctx = runner.ctx()
    result = json.loads(asyncio.run(stage_workout_changes(ctx, eleven)))
    assert result["staged"] == 0 and result["use_plan_builder"] is True
    assert 'load_skill(skill_name="plan-builder"' in result["message"]
    assert 'start_date="2026-11-02"' in result["message"] and "fetch_plan_context" not in result["message"]
    assert runner.tp_calls == [] and "staged_workout_changes" not in ctx.state

    # Workout count (<= 10) governs, so 2 workout changes spanning 3 ISO weeks stage directly.
    spread = [{"date_str": "2026-11-03", "title": "Easy 1", "create": True,
               "structure": {"steps": [{"name": "Easy", "distance_m": 5000, "pace": "6:00-6:20"}]}},
              {"date_str": "2026-11-17", "title": "Easy 2", "create": True,
               "structure": {"steps": [{"name": "Easy", "distance_m": 6000, "pace": "6:00-6:20"}]}}]
    result = json.loads(asyncio.run(stage_workout_changes(ctx, spread, message="Moved both runs two weeks out.")))
    assert result.get("use_plan_builder") is not True and result["staged"] == 2
    assert len(ctx.state["staged_workout_changes"]["changes"]) == 2
