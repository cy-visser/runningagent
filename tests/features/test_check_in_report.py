"""Behavioural test for the check-in report feature (`fetch_checkin_data`)."""

import asyncio
import json

from running_coach.features.check_in_report.fetch_checkin_data_tool import fetch_checkin_data
from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data


def test_check_in_report_populates_sections_tables_and_web_payload(runner):
    # Populate the training log via trend gap-fill so LT1/LT2 paces and start positions exist.
    asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))

    ctx = runner.ctx()
    out = asyncio.run(fetch_checkin_data(ctx))

    assert "### Weekly Check-In Training & Physiological Report" in out
    assert "**1. Fitness PMC Trends, Goal Race Projection & Trajectory" in out
    assert "**3. Weekly Totals (completed, pre-computed; do not recompute):**" in out
    assert "### North Star Progress" in out
    assert "Slight calf tightness" in out
    # The goal-plan table is in the coach instruction; the check-in references it instead of repeating it.
    assert "see GOAL PLAN in your instructions" in out
    assert "| Sub goal | Block | Status |" not in out
    assert "north-star equivalent" in out
    assert "█" not in out

    # Metrics are rendered by the web app from the payload; nothing is spliced into the coach's text.
    assert ctx.state.get("checkin_tables") is None

    report = json.loads(json.dumps(ctx.state.get("checkin_report_data")))
    assert report["version"] == 1
    assert report["ctl"]["current"] > 0
    assert report["projection"]["goal_label"] == "10K"
    drivers = report["projection"]["drivers"]
    assert [d["driver"] for d in drivers][-2:] == ["Load", "Health"]
    assert all({"driver", "evidence", "implied"} == set(d) for d in drivers)
    assert len(report["weeks"]) >= 2
