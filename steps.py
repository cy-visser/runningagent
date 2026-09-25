import asyncio
import logging
from typing import Any, Optional

from google.adk import Context

from .services.firestore import (
    get_user_profile,
    save_user_profile,
    update_user_profile,
)
from .services.weather import geocode_location
from .utils import (
    calculate_age,
    get_today_date,
    merge_profile_data,
    onboarding_prefill,
    parse_date,
    parse_mcp_response,
    parse_runner_name,
    profile_user_id,
    sync_profile_to_state,
)

logger = logging.getLogger(__name__)


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


PROFILE_FOUND = "found"
PROFILE_NEW = "new"
PROFILE_TP_UNAVAILABLE = "tp_unavailable"


async def load_profile_by_id(ctx: Context, user_id: str) -> Optional[dict]:
    """Loads a Firestore profile by id into state. Returns None if it doesn't exist.

    Raises on Firestore errors so callers can tell "missing" from "unreachable".
    """
    profile = await get_user_profile(user_id)
    logger.info("Firestore profile lookup for '%s': exists=%s", user_id, profile is not None)
    if not profile:
        return None
    try:
        await _ensure_cached_coordinates(user_id, profile)
    except Exception as e:  # non-fatal: the profile itself was found
        logger.warning("Could not cache coordinates for %s: %s", user_id, e)
    sync_profile_to_state(ctx, profile)
    ctx.state["temp_onboarding_data"] = onboarding_prefill(profile)
    return profile


async def check_profile_step(ctx: Context, tp_profile: Any) -> str:
    """Identifies the runner from the TrainingPeaks profile and loads their Firestore profile.

    Returns PROFILE_FOUND (user_profile in state), PROFILE_NEW (no stored profile;
    `temp_onboarding_data` seeded from TrainingPeaks) or PROFILE_TP_UNAVAILABLE
    (the runner couldn't be identified or Firestore failed; must NOT onboard).
    """
    ctx.state["temp_onboarding_data"] = {}

    profile_data = parse_mcp_response(tp_profile)
    if not isinstance(profile_data, dict) or not profile_data:
        logger.error("Could not parse the TrainingPeaks profile response.")
        return PROFILE_TP_UNAVAILABLE

    name = str(profile_data.get("name", "")).strip()
    if not name:
        logger.error("Name not found in the TrainingPeaks profile.")
        return PROFILE_TP_UNAVAILABLE

    firstname, lastname, user_id = parse_runner_name(name)

    try:
        if await load_profile_by_id(ctx, user_id):
            return PROFILE_FOUND
    except Exception:
        logger.exception("Failed to load Firestore profile for %s", user_id)
        return PROFILE_TP_UNAVAILABLE

    # No stored profile: seed onboarding with the data harvested from TrainingPeaks.
    ctx.state["temp_onboarding_data"] = {
        "firstname": firstname,
        "lastname": lastname,
        "age": calculate_age(profile_data.get("birthDate")),
        "height": profile_data.get("height"),
        "weight": profile_data.get("weight"),
        "location": profile_data.get("city") or profile_data.get("country"),
    }
    return PROFILE_NEW


async def create_profile_step(ctx: Context) -> bool:
    """Resolves coordinates and saves the final profile to Firestore.

    Returns False (and writes nothing) when the runner's name is unknown.
    """
    onboarding_answers = _as_dict(ctx.state.get("onboarding_answers"))
    temp_data = ctx.state.get("temp_onboarding_data") or {}

    user_id = profile_user_id(temp_data)
    if not user_id:
        logger.error("Refusing to save a profile without a runner name.")
        return False

    location = onboarding_answers.get("location") or temp_data.get("location") or ""
    lat, lon = None, None
    if location:
        coords = await asyncio.to_thread(geocode_location, location)
        if coords:
            lat, lon = coords

    profile = merge_profile_data(
        answers=onboarding_answers,
        temp_data=temp_data,
        lat=lat,
        lon=lon,
        location=location,
    )

    await save_user_profile(user_id, profile)
    sync_profile_to_state(ctx, profile)

    # Clean up temporary onboarding state
    ctx.state["temp_onboarding_data"] = None
    ctx.state["onboarding_answers"] = None
    return True
