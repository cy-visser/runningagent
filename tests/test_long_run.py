"""Shared long-run rule across the schedule audit and trend analysis."""

import asyncio
from datetime import date

import running_coach.tools as tools
from running_coach.utils.long_run import (
    FLAG_ABOVE,
    FLAG_BELOW_FLOOR,
    FLAG_OK,
    PHASE_BUILD,
    PHASE_RACE_WEEK,
    PHASE_SHARPENING,
    format_trend_long_run_target,
    long_run_flag,
    long_run_target,
)

TODAY = date(2026, 11, 5)
PLAN = {
    "goal_type": "plan",
    "north_star": {"goal": "Sub-3:20 Marathon", "race_name": "London Marathon 2028", "race_date": "2028-04-23"},
    "sub_goals": [{"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07"}],
}


def _run(day, km, hours=1.2):
    return {"date": day, "sport": "Run", "title": "Long run" if km >= 14 else "Easy",
            "type": "planned", "distance_planned_km": km, "duration_planned": hours}


def test_long_run_target_phases_floor_and_cap():
    build = long_run_target("5K", "Marathon", 65)
    assert (build["low_km"], build["high_km"], build["phase"]) == (16.5, 19.5, PHASE_BUILD)
    assert (long_run_target("5K", "Marathon", 55)["low_km"], long_run_target("5K", None, 40)["low_km"]) == (16.0, 12.0)
    capped = long_run_target("5K", "Marathon", 70, pace_s_per_km=330)          # 110 min @ 5:30/km = 20 km
    assert (capped["low_km"], capped["high_km"]) == (17.5, 20.0)
    sharpen = long_run_target("5K", "Marathon", 65, weeks_to_race=2)
    assert (sharpen["low_km"], sharpen["high_km"], sharpen["phase"]) == (12.0, 16.0, PHASE_SHARPENING)
    assert long_run_target("5K", "Marathon", 65, weeks_to_race=0)["phase"] == PHASE_RACE_WEEK
    assert (long_run_flag(14.0, build), long_run_flag(18.0, build), long_run_flag(21.0, build)) == (
        FLAG_BELOW_FLOOR, FLAG_OK, FLAG_ABOVE
    )


def test_schedule_audit_facade_surfaces_goal_plan_and_flags(monkeypatch):
    async def fake_workouts(tool_context, start, end):
        return [_run("2026-12-01", 10.0), _run("2026-12-03", 12.0), _run("2026-12-05", 10.0), _run("2026-12-06", 14.0)]

    async def fake_notes(tool_context, start, end):
        return []

    async def fake_tp(tool_context, name, **kw):
        return {"daily_data": [{"date": "2026-11-05", "ctl": 58.0}]}

    class Ctx:
        state = {"user_profile": PLAN}

    monkeypatch.setattr(tools, "_fetch_workouts", fake_workouts)
    monkeypatch.setattr(tools, "_fetch_notes", fake_notes)
    monkeypatch.setattr(tools, "_run_tp_tool", fake_tp)
    monkeypatch.setattr(tools, "get_today_date", lambda: TODAY)

    out = asyncio.run(tools.fetch_schedule_audit_data(Ctx(), weeks_forward=5))
    assert "Goal Plan Context" in out and "current CTL 58.0" in out
    assert "transition week (outside the 5K block)" in out
    assert "Long run: 14.0 km | target 16-" in out and FLAG_BELOW_FLOOR in out


def test_trend_target_matches_shared_rule():
    rows = [{"complete": True, "runs": 5, "km": km} for km in (50, 60, 65, 70, 65)]
    line = format_trend_long_run_target(PLAN, TODAY, rows, easy_pace_s=330)
    t = long_run_target("5K", "Marathon", 65, 330)
    assert f"build weeks {t['low_km']:g}-{t['high_km']:g} km" in line
    assert "last 2 weeks 12-16 km" in line
