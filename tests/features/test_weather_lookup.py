"""Behavioural test for weather lookup (`get_weather`)."""

import asyncio

from running_coach.features.weather_lookup.get_weather_tool import get_weather


def test_weather_lookup_uses_home_location_destination_or_prompts_when_missing(runner):
    home = asyncio.run(get_weather(runner.ctx(), dates=["2026-10-28", "2026-10-29"]))
    assert "Weather for Amsterdam:" in home and "2026-10-28" in home

    dest = asyncio.run(get_weather(runner.ctx(), dates=["2026-10-28"], location="Valencia"))
    assert "Weather for Valencia:" in dest

    missing = asyncio.run(get_weather(runner.ctx(profile={"firstname": "Cyrille"}), dates=["2026-10-28"]))
    assert "No location on file" in missing
