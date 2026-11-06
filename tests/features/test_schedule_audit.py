"""Behavioural test for the schedule audit feature (`fetch_schedule_audit_data`)."""

import asyncio
import json

from running_coach.tools import fetch_schedule_audit_data


def test_schedule_audit_surfaces_goal_context_long_run_floor_and_web_payload(runner):
    ctx = runner.ctx()
    out = asyncio.run(fetch_schedule_audit_data(ctx, weeks_forward=4, weeks_back=1))

    assert "**Goal Plan Context**" in out
    assert "London Marathon 2028" in out
    assert "transition week (outside the 10K block)" in out
    assert "Long run: 14.0 km | target 16-" in out
    assert "⚠ below north-star floor" in out
    assert "Work trip to Berlin" in out

    report = json.loads(json.dumps(ctx.state.get("audit_report_data")))
    assert report["version"] == 1
    assert len(report["weeks"]) >= 4
    assert any(w.get("long_run") and "below north-star floor" in w["long_run"] for w in report["weeks"])
