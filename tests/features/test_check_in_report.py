"""Behavioural test for the check-in report feature (`fetch_checkin_data`)."""

import asyncio
import json

from running_coach.tools import fetch_checkin_data, fetch_trend_data


def test_check_in_report_populates_sections_tables_and_web_payload(runner):
    # Populate the training log via trend gap-fill so LT1/LT2 paces and start positions exist.
    asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))

    ctx = runner.ctx()
    out = asyncio.run(fetch_checkin_data(ctx))

    assert "### Weekly Check-In Training & Physiological Report" in out
    assert "**1. Fitness PMC Trends, Goal Race Projection & Trajectory" in out
    assert "**3. Weekly Totals (completed, pre-computed; do not recompute):**" in out
    assert "### North Star Progress" in out
    assert "London Marathon 2028" in out
    assert "Slight calf tightness" in out

    tables = ctx.state.get("checkin_tables")
    assert tables and "| Metric | Current Value | Target / Reference | Progress & Trajectory |" in tables
    assert "**CTL (Fitness)**" in tables

    report = json.loads(json.dumps(ctx.state.get("checkin_report_data")))
    assert report["version"] == 1
    assert report["ctl"]["current"] > 0
    assert report["projection"]["goal_label"] == "10K"
    assert len(report["weeks"]) >= 2
