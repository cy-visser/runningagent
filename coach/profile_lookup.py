import asyncio
import logging
from typing import Any, Optional

from google.adk import Context

from ..integrations import config, firestore, open_meteo
from ..shared.runner_identity import normalize_email
from ..shared.session_state import AUTH_EMAIL_STATE_KEY, sync_profile_to_state
from .onboarding.profile_creation import onboarding_prefill

logger = logging.getLogger(__name__)

PROFILE_UNAVAILABLE_MESSAGE = (
    "I couldn't load your runner profile from Firestore just now, so I've paused rather than "
    "starting onboarding. Please send your message again in a moment."
)


def caller_email(state: Any) -> Optional[str]:
    """Resolves the caller's email from the web app (`user:auth_email`) or local dev."""
    return normalize_email(state.get(AUTH_EMAIL_STATE_KEY)) or config.dev_runner_email()


def needs_onboarding(profile: Optional[dict]) -> bool:
    """True when a profile is missing or is a web skeleton (TrainingPeaks connected, no goal yet)."""
    if not profile or profile.get("onboarding_pending"):
        return True
    has_single = bool(profile.get("training_goal") or profile.get("timeline"))
    has_plan = bool((profile.get("north_star") or {}).get("goal"))
    return not (has_single or has_plan)


async def _ensure_cached_coordinates(user_id: str, profile: dict) -> None:
    """Geocodes and caches the runner's coordinates in Firestore when missing."""
    if "latitude" in profile and "longitude" in profile:
        return
    location = profile.get("location", "")
    if not location:
        return

    coords = await asyncio.to_thread(open_meteo.geocode_location, location)
    if not coords:
        return

    profile["latitude"], profile["longitude"] = coords
    await firestore.update_user_profile(user_id, {"latitude": coords[0], "longitude": coords[1]})
    logger.info("Cached coordinates %s for %s", coords, user_id)


async def find_profile_by_email(email: str) -> Optional[tuple[str, dict]]:
    """Looks up `(runner_id, profile)` in Firestore by normalized email.

    Raises on Firestore errors or duplicate mappings so callers can fail closed.
    """
    found = await firestore.find_user_profile_by_email(email)
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
