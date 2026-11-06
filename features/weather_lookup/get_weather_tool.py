"""Weather lookup tool for home or destination locations."""

import asyncio
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations import open_meteo
from ...shared.runner_weather import location_args


async def get_weather(tool_context: ToolContext, dates: list[str], location: Optional[str] = None) -> str:
    """Weather (daily + hourly) for ISO dates/timestamps at the runner's home location,
    or at `location` (e.g. a travel or race destination). Forecasts reach 16 days ahead.

    Args:
        dates: ISO dates (YYYY-MM-DD) or timestamps (YYYY-MM-DDTHH:MM).
        location: Optional city name; defaults to the runner's home location.
    """
    profile = tool_context.state.get("user_profile") or {}
    geo = {"location": location, "lat": None, "lon": None} if location else location_args(profile)
    if not geo:
        return "No location on file; ask the runner where they will be running."
    return await asyncio.to_thread(open_meteo.get_weather_for_dates, dates=dates, **geo)


get_weather_tool = FunctionTool(get_weather)
