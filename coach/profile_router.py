import logging
from typing import Any, AsyncGenerator, Optional

from google.adk import Context, Event
from google.adk.workflow import node

from ..integrations import config
from ..integrations.trainingpeaks import credentials
from ..shared.runner_identity import normalize_email
from ..shared.session_state import AUTH_EMAIL_STATE_KEY
from .onboarding.profile_creation import onboarding_prefill
from .profile_lookup import activate_profile, find_profile_by_email, needs_onboarding

logger = logging.getLogger(__name__)

ROUTE_ONBOARDING = "ONBOARDING"
ROUTE_COACHING = "COACHING"
ROUTE_NOT_LINKED = "NOT_LINKED"
ROUTE_TP_NOT_CONNECTED = "TP_NOT_CONNECTED"
ROUTE_UNAVAILABLE = "PROFILE_UNAVAILABLE"

PROFILE_UNAVAILABLE_MESSAGE = (
    "I couldn't load your runner profile from Firestore just now, so I've paused rather than "
    "starting onboarding. Please send your message again in a moment."
)


def _caller_email(ctx: Context) -> Optional[str]:
    """Resolves the caller's email from the web app (`user:auth_email`) or local dev."""
    return normalize_email(ctx.state.get(AUTH_EMAIL_STATE_KEY)) or config.dev_runner_email()


def _not_linked_message(email: Optional[str]) -> str:
    who = f" ({email})" if email else ""
    url = config.web_app_url()
    where = f"open the Running Coach web app ({url})" if url else "open the Running Coach web app"
    return (
        f"No runner profile is linked to your account{who} yet — "
        f"{where} to connect TrainingPeaks and set up your profile."
    )


def _tp_not_connected_message() -> str:
    url = config.web_app_url()
    where = f"in the Running Coach web app ({url})" if url else "in the Running Coach web app"
    return (
        f"Your runner profile doesn't have an active TrainingPeaks connection yet. "
        f"Please reconnect TrainingPeaks from your profile {where}, then message me again."
    )


@node(name="profile_router", rerun_on_resume=True)
async def profile_router(ctx: Context, node_input: Any = None) -> None:
    """Identifies the runner by email and routes. No TrainingPeaks call, no shared credential.

    Web turns set `user:auth_email` and always reload Firestore so profile edits apply immediately.
    Evals and local runs reuse a session-cached `user_profile` when already present.
    """
    auth_email = normalize_email(ctx.state.get(AUTH_EMAIL_STATE_KEY))
    profile = None if auth_email else ctx.state.get("user_profile")
    if not profile:
        email = _caller_email(ctx)
        if not email:
            ctx.route = ROUTE_NOT_LINKED
            return
        try:
            found = await find_profile_by_email(email)
            connected = bool(found) and await credentials.has_tp_credential(found[0])
        except Exception:
            logger.exception("Failed to resolve the runner profile for %s", email)
            ctx.route = ROUTE_UNAVAILABLE
            return
        if not found:
            ctx.route = ROUTE_NOT_LINKED
            return
        if not connected:
            ctx.route = ROUTE_TP_NOT_CONNECTED
            return
        profile = await activate_profile(ctx, *found)

    if needs_onboarding(profile) or ctx.state.get("reonboard_requested"):
        ctx.state["temp_onboarding_data"] = onboarding_prefill(profile)
        ctx.route = ROUTE_ONBOARDING
        return

    ctx.route = ROUTE_COACHING


@node(name="not_linked_node", rerun_on_resume=True)
async def not_linked_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Directs an unlinked account to the web app to connect TrainingPeaks and create a profile."""
    yield Event(author="model", message=_not_linked_message(_caller_email(ctx)))


@node(name="tp_not_connected_node", rerun_on_resume=True)
async def tp_not_connected_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Directs a runner whose profile lacks an encrypted TrainingPeaks cookie to reconnect."""
    yield Event(author="model", message=_tp_not_connected_message())


@node(name="profile_unavailable_node", rerun_on_resume=True)
async def profile_unavailable_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Tells the runner we couldn't load their profile, instead of wrongly onboarding."""
    yield Event(author="model", message=PROFILE_UNAVAILABLE_MESSAGE)
