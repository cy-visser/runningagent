"""Behavioural test for the nutrition planner feature (`fetch_nutrition_context`)."""

import asyncio

from running_coach.tools import fetch_nutrition_context


def test_nutrition_planner_surfaces_biometrics_upcoming_sessions_and_forecast(runner):
    out = asyncio.run(fetch_nutrition_context(runner.ctx(), days_forward=3))

    assert "Weight: 72 kg | Age: 38" in out
    assert "Sub-43 10K" in out
    assert "**2. Upcoming Training Sessions (Next 3 Days):**" in out
    assert "Amsterdam" in out and "12°C" in out
