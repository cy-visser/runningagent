import asyncio
import logging
from typing import Any, Optional

from google.adk import Context

from .services.firestore import (
    find_user_profile_by_email,
    get_user_profile,
    save_user_profile,
    update_user_profile,
)
from .services.weather import geocode_location
from .utils import (
    AUTH_EMAIL_STATE_KEY,
    merge_profile_data,
    normalize_email,
    onboarding_prefill,
    profile_user_id,
    sync_profile_to_state,
)

logger = logging.getLogger(__name__)

PROFILE_SAVED = "saved"
PROFILE_NO_NAME = "no_name"
PROFILE_EMAIL_CONFLICT = "email_conflict"


def _as_dict(value: Any) -> dict:
    """Normalises ADK structured output (pydantic model or dict) into a plain dict."""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


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


async def find_profile_by_email(email: str) -> Optional[tuple[str, dict]]:
    """Looks up `(runner_id, profile)` in Firestore by normalized email.

    Raises on Firestore errors or duplicate mappings so callers can fail closed.
    """
    found = await find_user_profile_by_email(email)
    logger.info("Firestore email lookup for %r: exists=%s", email, found is not None)
    return found


async def activate_profile(ctx: Context, user_id: str, profile: dict) -> dict:
    """Caches missing coordinates (best-effort) and activates `profile` in session state."""
    try:
        await _ensure_cached_coordinates(user_id, profile)
    except Exception as exc:  # non-fatal: the profile itself was loaded
        logger.warning("Could not cache coordinates for %s: %s", user_id, exc)
    sync_profile_to_state(ctx, profile)
    ctx.state["temp_onboarding_data"] = onboarding_prefill(profile)
    return profile


async def create_profile_step(ctx: Context) -> str:
    """Resolves coordinates and saves the final profile to Firestore.

    Returns:
      - `PROFILE_SAVED`: profile written and synced into session state.
      - `PROFILE_NO_NAME`: refused because no runner name was present.
      - `PROFILE_EMAIL_CONFLICT`: refused because `users/{user_id}` already belongs to a
        different (or unlinked) account.
    """
    onboarding_answers = _as_dict(ctx.state.get("onboarding_answers"))
    temp_data = dict(ctx.state.get("temp_onboarding_data") or {})

    incoming_email = normalize_email(
        temp_data.get("email")
        or (ctx.state.get("user_profile") or {}).get("email")
        or ctx.state.get(AUTH_EMAIL_STATE_KEY)
    )
    if incoming_email:
        temp_data["email"] = incoming_email

    user_id = profile_user_id(temp_data)
    if not user_id:
        logger.error("Refusing to save a profile without a runner name.")
        return PROFILE_NO_NAME

    existing = await get_user_profile(user_id)
    if existing is not None:
        existing_email = normalize_email(existing.get("email"))
        if existing_email != incoming_email:
            logger.error(
                "Refusing to overwrite users/%s: existing email %r != incoming email %r",
                user_id,
                existing_email,
                incoming_email,
            )
            return PROFILE_EMAIL_CONFLICT

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

    ctx.state["temp_onboarding_data"] = None
    ctx.state["onboarding_answers"] = None
    return PROFILE_SAVED
