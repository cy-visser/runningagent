import asyncio
import logging
from typing import Any, Optional

from google.adk import Context

from .services.firestore import (
    get_user_profile,
    save_user_profile,
    update_user_profile,
)
from .services.tp_mcp import get_tp_tool
from .services.weather import geocode_location
from .utils import (
    calculate_age,
    extract_health_metrics,
    get_past_date_str,
    get_today_date,
    get_today_str,
    merge_profile_data,
    parse_date,
    parse_mcp_response,
    parse_runner_name,
    sync_profile_to_state,
)

logger = logging.getLogger(__name__)

DEFAULT_SLEEP_HOURS = 7.0
METRICS_LOOKBACK_DAYS = 14

# Profile fields pre-filled from an existing Firestore record so onboarding can
# skip questions the runner has already answered.
_PREFILL_FIELDS = (
    "firstname",
    "lastname",
    "age",
    "height",
    "weight",
    "location",
    "injuries",
    "recent_race_times",
    "cross_training_strength",
    "shoe_rotation",
)


def _as_dict(value: Any) -> dict:
    """Normalises ADK structured output (pydantic model or dict) into a plain dict."""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


def check_timeline_expiration(profile: Optional[dict]) -> tuple[bool, Optional[str]]:
    """Compares today's date with the runner's profile timeline (YYYY-MM-DD).

    Returns (is_expired, timeline_date_str).
    """
    timeline_str = (profile or {}).get("timeline")
    if not timeline_str:
        return False, None

    timeline_date = parse_date(timeline_str)
    if not timeline_date:
        logger.warning("Could not parse profile timeline date '%s'", timeline_str)
        return False, None

    if get_today_date() > timeline_date:
        return True, str(timeline_str).strip()
    return False, None


async def _ensure_cached_coordinates(user_id: str, profile: dict) -> None:
    """Geocodes and caches the runner's coordinates in Firestore when missing."""
    if "latitude" in profile and "longitude" in profile:
        return
    location = profile.get("location", "")
    if not location:
        return

    coords = await asyncio.to_thread(geocode_location, location)
    if not coords:
        return

    profile["latitude"], profile["longitude"] = coords
    await update_user_profile(user_id, {"latitude": coords[0], "longitude": coords[1]})
    logger.info("Cached coordinates %s for %s", coords, user_id)


async def check_profile_step(ctx: Context, tp_profile: Any) -> None:
    """Processes the TrainingPeaks profile and loads any existing Firestore profile into state.

    On success `user_profile` is populated in state; otherwise only
    `temp_onboarding_data` is seeded with whatever TrainingPeaks knew about the runner.
    """
    ctx.state["temp_onboarding_data"] = {}

    profile_data = parse_mcp_response(tp_profile)
    if not isinstance(profile_data, dict) or not profile_data:
        logger.error("Could not parse the TrainingPeaks profile response.")
        return

    name = str(profile_data.get("name", "")).strip()
    if not name:
        logger.error("Name not found in the TrainingPeaks profile.")
        return

    firstname, lastname, user_id = parse_runner_name(name)

    try:
        profile = await get_user_profile(user_id)
        logger.info("Firestore profile lookup for '%s': exists=%s", user_id, profile is not None)
        if profile:
            await _ensure_cached_coordinates(user_id, profile)
            sync_profile_to_state(ctx, profile)
            ctx.state["temp_onboarding_data"] = {f: profile.get(f) for f in _PREFILL_FIELDS}
            return
    except Exception as e:
        logger.error("Failed to load Firestore profile for %s: %s", user_id, e)

    # No stored profile: seed onboarding with the data harvested from TrainingPeaks.
    ctx.state["temp_onboarding_data"] = {
        "firstname": firstname,
        "lastname": lastname,
        "age": calculate_age(profile_data.get("birthDate")),
        "height": profile_data.get("height"),
        "weight": profile_data.get("weight"),
        "location": profile_data.get("city") or profile_data.get("country"),
    }


async def _fetch_sleep_average(ctx: Context) -> float:
    """Returns the runner's mean nightly sleep over the recent metrics window."""
    try:
        tp_get_metrics_tool = await get_tp_tool("tp_get_metrics")
        raw_response = await ctx.run_node(
            tp_get_metrics_tool,
            node_input={
                "start_date": get_past_date_str(days=METRICS_LOOKBACK_DAYS),
                "end_date": get_today_str(),
            },
        )
        sleep_hours = extract_health_metrics(raw_response).get("sleep", [])
        if sleep_hours:
            return round(sum(sleep_hours) / len(sleep_hours), 2)
    except Exception as e:
        logger.warning("Could not fetch sleep metrics for the new profile: %s", e)
    return DEFAULT_SLEEP_HOURS


async def create_profile_step(ctx: Context) -> None:
    """Fetches metrics, resolves coordinates, and saves the final profile to Firestore."""
    onboarding_answers = _as_dict(ctx.state.get("onboarding_answers"))
    temp_data = ctx.state.get("temp_onboarding_data") or {}

    _, _, user_id = parse_runner_name(
        f"{temp_data.get('firstname', '')} {temp_data.get('lastname', '')}"
    )

    sleep_avg = await _fetch_sleep_average(ctx)

    location = onboarding_answers.get("location") or temp_data.get("location") or ""
    lat, lon = None, None
    if location:
        coords = await asyncio.to_thread(geocode_location, location)
        if coords:
            lat, lon = coords

    profile = merge_profile_data(
        answers=onboarding_answers,
        temp_data=temp_data,
        sleep_avg=sleep_avg,
        lat=lat,
        lon=lon,
        location=location,
    )

    await save_user_profile(user_id, profile)
    sync_profile_to_state(ctx, profile)

    # Clean up temporary onboarding state
    ctx.state["temp_onboarding_data"] = None
    ctx.state["onboarding_answers"] = None
