"""Tool facades: trend gap-fill, workout analysis record parity, sub-goal result save & workout upsert."""

import asyncio
import json
import pathlib
from datetime import date

import pytest

import running_coach.tools as tools

CANOVA = json.loads((pathlib.Path(__file__).parent / "fixtures" / "structured_workouts.json").read_text())["canova"]
TODAY = date(2026, 10, 27)
PROFILE = {
    "firstname": "Cyrille", "lastname": "Visser", "latitude": 52.37, "longitude": 4.89,
    "goal_type": "plan",
    "north_star": {"goal": "Sub-3:15 Marathon", "race_date": "2028-04-23"},
    "sub_goals": [{"goal": "Sub-21 5K", "start_date": "2026-08-01", "race_date": "2026-10-20", "result": None}],
}
SETTINGS = {"settings": {
    "heartRateZones": [{"workoutTypeId": 3, "threshold": 172, "zones": [
        {"label": "Zone 1", "minimum": 111, "maximum": 145}, {"label": "Zone 2", "minimum": 146, "maximum": 153}]}],
    "speedZones": [{"workoutTypeId": 3, "threshold": 3.509}]}}
ANALYSIS = {"lapData": CANOVA["laps"], "totals": {"Avg heart rate": {"value": 140}, "NGP": {"value": 5.0}, "Duration": {"value": 1245}},
            "startTimestamp": "2026-10-20T07:30:00", "data_file": None}


def _envelope(data):
    return {"content": [{"type": "text", "text": json.dumps(data)}]}


class Ctx:
    def __init__(self):
        self.state = {"user_profile": json.loads(json.dumps(PROFILE))}


@pytest.fixture
def env(monkeypatch):
    saved, profile_updates = {}, []
    workouts = [
        {"id": "w1", "date": "2026-10-13", "start_time": "2026-10-13T07:30:00", "title": "Run w1", "sport": "Run",
         "type": "completed", "distance_actual_km": 10.0},
        {"id": "w2", "date": "2026-10-20", "start_time": "2026-10-20T07:30:00", "title": "5K race", "sport": "Run",
         "type": "completed", "distance_actual_km": 5.0},
        {"id": "w3", "date": "2026-10-21", "start_time": "2026-10-21T07:30:00", "title": "Bike", "sport": "Bike",
         "type": "completed", "distance_actual_km": 20.0},
    ]

    async def fake_tp(tool_context, name, **kw):
        if name == "tp_get_workouts":
            return _envelope({"workouts": [w for w in workouts if kw["start_date"] <= w["date"] <= kw["end_date"]]})
        if name == "tp_get_workout":
            w = next(w for w in workouts if w["id"] == kw["workout_id"])
            km = sum(lap["TotalDistance"] for lap in CANOVA["laps"]) if w["sport"] == "Run" else 20.0
            return _envelope({"id": w["id"], "date": w["date"], "title": w["title"], "sport": w["sport"],
                              "structured_workout": CANOVA["structured_workout"] if w["sport"] == "Run" else None,
                              "metrics": {"duration_actual": 1245 / 3600, "distance_actual_km": km, "tss_actual": 80.0}})
        if name == "tp_analyze_workout":
            return _envelope(ANALYSIS)
        if name == "tp_get_fitness":
            return _envelope({"daily_data": [{"date": "2026-10-20", "ctl": 60.0, "atl": 65.0, "tsb": -5.0}]})
        if name == "tp_get_metrics":
            return _envelope({"metrics": [{"timeStamp": "2026-10-20T00:00:00", "details": [{"type": 60, "value": 41}]}]})
        if name == "tp_get_athlete_settings":
            return _envelope(SETTINGS)
        return {"id": "new-1"}

    async def fake_list(user_id, start, end):
        return [{"workout_id": "w1", "date": "2026-10-13", "sport": "Run", "kind": "easy",
                 "distance_km": 10.0, "tss": 60.0, "athlete": {}}]

    async def fake_save(user_id, wid, record):
        saved[wid] = record

    async def fake_update_profile(user_id, update):
        profile_updates.append((user_id, update))

    async def no_weather_text(profile, dates, **_kw):
        return ""

    monkeypatch.setattr(tools, "_run_tp_tool", fake_tp)
    monkeypatch.setattr(tools, "list_training_records", fake_list)
    monkeypatch.setattr(tools, "save_training_record", fake_save)
    monkeypatch.setattr(tools, "update_user_profile", fake_update_profile)
    monkeypatch.setattr(tools, "get_conditions_at", lambda lat, lon, ts, **_kw: {"feels_like_c": 11.0})
    monkeypatch.setattr(tools, "_fetch_weather_text", no_weather_text)
    monkeypatch.setattr(tools, "get_today_date", lambda: TODAY)
    return {"saved": saved, "profile_updates": profile_updates}


def test_trend_gap_fill_and_rate_limit_flagging(env, monkeypatch):
    out = asyncio.run(tools.fetch_trend_data(Ctx(), weeks=6))
    assert sorted(env["saved"]) == ["w2", "w3"]
    assert "2 added by gap-fill now, 0 could not be recorded" in out

    env["saved"].clear()
    original = tools._run_tp_tool

    async def rate_limited(tool_context, name, **kw):
        if name == "tp_analyze_workout":
            return _envelope({"isError": True, "error_code": "API_ERROR", "message": "429 Too Many Requests"})
        return await original(tool_context, name, **kw)

    monkeypatch.setattr(tools, "_run_tp_tool", rate_limited)
    flagged = asyncio.run(tools.fetch_trend_data(Ctx(), weeks=6))
    assert "w2" not in env["saved"] and "| 2026-10-19 (1 unrecorded) |" in flagged


def test_analyze_workout_matches_gap_fill_and_saves_sub_goal_race_result(env):
    out = asyncio.run(tools.analyze_workout(Ctx(), workout_id="w2"))
    assert "Result saved" in out and len(env["profile_updates"]) == 1
    via_analysis = {k: v for k, v in env["saved"]["w2"].items() if k != "recorded_at"}

    env["saved"].clear()
    asyncio.run(tools.fetch_trend_data(Ctx(), weeks=6))
    via_gap_fill = {k: v for k, v in env["saved"]["w2"].items() if k != "recorded_at"}
    assert via_analysis == via_gap_fill


def test_create_workout_updates_same_sport_and_creates_different_sport(monkeypatch):
    calls = []

    async def fake_fetch(tool_context, start, end):
        return [{"id": "r1", "sport": "Run", "title": "Easy", "type": "planned"}]

    async def fake_run(tool_context, tool_name, **node_input):
        calls.append((tool_name, node_input))
        return {"id": "new-1"}

    monkeypatch.setattr(tools, "_fetch_workouts", fake_fetch)
    monkeypatch.setattr(tools, "_run_tp_tool", fake_run)

    assert json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", sport="Strength", title="Core")))["action"] == "created"
    assert json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", title="Tempo")))["action"] == "updated"
    assert [c[0] for c in calls] == ["tp_create_workout", "tp_update_workout"]
