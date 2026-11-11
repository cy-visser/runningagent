"""Behavioural test for the coach's hidden key-events memory: storage rules, the record_key_event tool,
goal-race results from analyze_workout, the profile block and re-onboarding."""

import asyncio
from datetime import date

from running_coach.coach.coaching.instruction import build_profile_context
from running_coach.coach.coaching.record_key_event_tool import record_key_event
from running_coach.features.workout_analysis.analyze_workout_tool import analyze_workout
from running_coach.features.workout_analysis.helpers.sub_goal_race_result import goal_race_event
from running_coach.shared.key_events import (
    CONTEXT_MAX,
    MAX_STORED,
    SOURCE_COACH,
    add_key_event,
    format_key_events,
    make_event,
)
from running_coach.tests.fakes import PLAN_PROFILE, SINGLE_PROFILE


def _ev(day: str, kind: str = "injury", summary: str = "Calf strain", workout_id: str | None = None) -> dict:
    return make_event(kind, day, summary, SOURCE_COACH, workout_id=workout_id, recorded_at="2026-10-27T09:00:00Z")


def test_add_key_event_validates_dedupes_sorts_and_caps():
    for bad in (("nope", "2026-10-01", "x"), ("injury", "someday", "x"), ("injury", "2026-10-01", "  ")):
        try:
            make_event(*bad, SOURCE_COACH)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass

    events = add_key_event(None, _ev("2026-10-10"))
    events = add_key_event(events, _ev("2026-09-01", "break", "Holiday, no running 2 weeks"))
    assert [e["date"] for e in events] == ["2026-09-01", "2026-10-10"]  # sorted by date
    assert add_key_event(events, _ev("2026-10-10")) == events           # identical event: not added twice

    race = _ev("2026-10-20", "race", "Amsterdam 5K: 21:05", workout_id="w1")
    events = add_key_event(add_key_event(events, race), _ev("2026-10-20", "race", "Amsterdam 5K: 20:45", workout_id="w1"))
    assert [e["summary"] for e in events if e["type"] == "race"] == ["Amsterdam 5K: 20:45"]  # re-analysis replaces

    many: list = []
    for i in range(MAX_STORED + 5):
        many = add_key_event(many, _ev(f"2026-01-01", summary=f"event {i:03d}"))
    assert len(many) == MAX_STORED


def test_format_key_events_window_and_limit():
    today = date(2026, 10, 27)
    assert format_key_events({}, today) == ""
    old = _ev("2024-01-01", summary="Ancient history")
    recent = [_ev(f"2026-{m:02d}-01", summary=f"Event {m}") for m in range(1, 11)] + [
        _ev(f"2025-{m:02d}-15", summary=f"Older {m}") for m in range(6, 13)]
    text = format_key_events({"key_events": [old, *recent]}, today)
    assert text.startswith("KEY EVENTS") and "cannot see this list" in text
    assert "Ancient history" not in text                     # outside the ~18-month window
    assert len(text.splitlines()) == 1 + CONTEXT_MAX          # header + the most recent CONTEXT_MAX events
    assert text.splitlines()[-1] == "- 2026-10-01 injury: Event 10"


def test_record_key_event_tool_saves_silently_and_refreshes_state(runner):
    ctx = runner.ctx()
    out = asyncio.run(record_key_event(ctx, "break", "2026-12-20", "Holiday in Lapland, no running for 3 weeks"))
    assert out.startswith("Recorded")
    saved = runner.profiles["cyrille_visser"]["key_events"]
    assert saved == ctx.state["user_profile"]["key_events"]
    assert (saved[0]["date"], saved[0]["type"], saved[0]["source"]) == ("2026-12-20", "break", "coach")

    asyncio.run(record_key_event(ctx, "injury", "today", "Left calf strain"))
    assert [e["date"] for e in runner.profiles["cyrille_visser"]["key_events"]] == ["2026-10-27", "2026-12-20"]

    assert asyncio.run(record_key_event(ctx, "party", "2026-12-20", "x")).startswith("Error")
    assert len(runner.profiles["cyrille_visser"]["key_events"]) == 2


def test_goal_race_event_for_single_goal_sub_goal_and_north_star():
    single = goal_race_event(SINGLE_PROFILE, "2026-12-06", 3 * 3600 + 25 * 60 + 10, "w9", sport="Run")
    assert single["type"] == "race" and single["workout_id"] == "w9"
    assert single["summary"] == "Sub-3:30 Marathon: finished in 3:25:10 (goal Sub-3:30 Marathon, goal race)"
    sub = goal_race_event(PLAN_PROFILE, "2026-10-20", 1245, "w1", sport="run")
    assert sub["summary"] == "Amsterdam 5K: finished in 20:45 (goal Sub-21 5K, sub goal)"
    ns = goal_race_event(PLAN_PROFILE, "2028-04-23", 3 * 3600 + 14 * 60, "w2")
    assert ns["summary"].startswith("London Marathon 2028:") and ns["summary"].endswith("(goal Sub-3:15 Marathon, north star)")
    assert goal_race_event(PLAN_PROFILE, "2026-10-21", 1245, "w1") is None          # not a goal race date
    assert goal_race_event(PLAN_PROFILE, "2026-10-20", 1245, "w1", sport="Bike") is None
    assert goal_race_event(PLAN_PROFILE, "2026-10-20", None, "w1") is None


def test_analyze_workout_on_a_goal_race_date_saves_the_race_to_key_events(runner):
    ctx = runner.ctx()
    asyncio.run(analyze_workout(ctx, date_str="2026-10-20"))
    stored = runner.profiles["cyrille_visser"]
    events = stored["key_events"]
    assert len(events) == 1 and events[0]["type"] == "race" and events[0]["source"] == "workout_analysis"
    assert events[0]["summary"] == "Amsterdam 5K: finished in 20:45 (goal Sub-21 5K, sub goal)"
    assert stored["sub_goals"][0]["result"]["time"] == "20:45"          # the sub-goal result is still saved
    assert ctx.state["user_profile"]["sub_goals"][0]["result"]          # and neither write lost the other
    assert ctx.state["user_profile"]["key_events"] == events

    asyncio.run(analyze_workout(ctx, date_str="2026-10-20"))            # re-analysis: replaced, not duplicated
    assert len(runner.profiles["cyrille_visser"]["key_events"]) == 1

    other = runner.ctx()
    asyncio.run(analyze_workout(other, date_str="2026-10-22", sport="bike"))  # not a goal race
    assert "key_events" not in other.state["user_profile"]


def test_analyze_workout_survives_a_key_event_save_failure(runner, monkeypatch):
    from running_coach.integrations import firestore

    async def boom(user_id, updates):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(firestore, "update_user_profile", boom)
    out = asyncio.run(analyze_workout(runner.ctx(), date_str="2026-10-20"))
    assert not out.startswith("Error")


def test_profile_block_shows_key_events():
    profile = {**PLAN_PROFILE, "key_events": [_ev("2026-10-02", summary="Left calf strain, 2 weeks off")]}
    block = build_profile_context(profile, date(2026, 10, 27))
    assert "KEY EVENTS" in block and "- 2026-10-02 injury: Left calf strain, 2 weeks off" in block
    assert "KEY EVENTS" not in build_profile_context(PLAN_PROFILE, date(2026, 10, 27))
