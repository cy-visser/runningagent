"""Nutrition context tool for the `nutrition-planner` skill."""

import asyncio
import logging
from datetime import timedelta

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date
from ...shared.runner_weather import fetch_weather_text
from .helpers.nutrition_context_text import format_nutrition_context_summary

logger = logging.getLogger(__name__)


async def fetch_nutrition_context(
    tool_context: ToolContext,
    days_forward: int = 3,
) -> str:
    """Upcoming training and the weather forecast for fueling and hydration guidance (biometrics and
    goal are in the runner profile).

    Args:
        days_forward: Days ahead to plan (default 3).
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()
    end_date = today_date + timedelta(days=days_forward)
    forecast_dates = [iso_date(today_date + timedelta(days=i)) for i in range(days_forward + 1)]

    upcoming, weather_str = await asyncio.gather(
        tp_calls.fetch_workouts(tool_context, iso_date(today_date), iso_date(end_date)),
        fetch_weather_text(profile, forecast_dates),
        return_exceptions=True,
    )
    if isinstance(upcoming, Exception):
        logger.warning("Failed to fetch upcoming workouts for nutrition context: %s", upcoming)
        return (f"Error: Could not load the upcoming TrainingPeaks workouts ({iso_date(today_date)} to "
                f"{iso_date(end_date)}). This is a data-loading failure: do NOT assume there is no training "
                "planned. Ask the runner what sessions are coming up, or suggest trying again shortly.")
    if isinstance(weather_str, Exception):
        logger.warning("Failed to fetch weather for nutrition context: %s", weather_str)
        weather_str = "Weather forecast unavailable."

    return format_nutrition_context_summary(
        upcoming_workouts=upcoming,
        weather_forecast=weather_str,
        days_forward=days_forward,
    )


fetch_nutrition_context_tool = FunctionTool(fetch_nutrition_context)
