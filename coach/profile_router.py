import asyncio
import logging
from typing import Any, AsyncGenerator, Optional

from google.adk import Context, Event
from google.adk.workflow import node

from ..integrations import config, firestore
from ..integrations.trainingpeaks import credentials, tp_calls
from ..shared.runner_identity import normalize_email, profile_user_id
from ..shared.session_state import AUTH_EMAIL_STATE_KEY
from .onboarding.profile_creation import onboarding_prefill
from .profile_lookup import (
    PROFILE_UNAVAILABLE_MESSAGE,
    activate_profile,
    caller_email,
    find_profile_by_email,
    needs_onboarding,
)

logger = logging.getLogger(__name__)
_warmup_tasks: set[asyncio.Task[None]] = set()

ROUTE_ONBOARDING = "ONBOARDING"
ROUTE_COACHING = "COACHING"
ROUTE_NOT_LINKED = "NOT_LINKED"
ROUTE_TP_NOT_CONNECTED = "TP_NOT_CONNECTED"
ROUTE_UNAVAILABLE = "PROFILE_UNAVAILABLE"


def _caller_email(ctx: Context) -> Optional[str]:
    """Resolves the caller's email from the web app (`user:auth_email`) or local dev."""
    return caller_email(ctx.state)


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


def _schedule_tp_warmup(runner_id: Optional[str]) -> None:
    if not runner_id:
        return
    task = asyncio.create_task(tp_calls.warm_runner_tp(runner_id))
    _warmup_tasks.add(task)
    task.add_done_callback(_warmup_tasks.discard)


async def _resolve_profile_and_connection(
    email: str, known_runner_id: Optional[str]
) -> tuple[Optional[tuple[str, dict]], bool]:
    """Loads `(runner_id, profile)` and TP credential status, running both in parallel when `runner_id` is known."""
    candidate_id = known_runner_id or firestore.cached_runner_id_for_email(email)
    if candidate_id:
        doc, connected = await asyncio.gather(
            firestore.get_user_profile(candidate_id),
            credentials.has_tp_credential(candidate_id),
        )
        if doc is not None and normalize_email(doc.get("email")) == email:
            firestore.remember_email_runner_id(email, candidate_id)
            return (candidate_id, doc), connected
    found = await find_profile_by_email(email)
    if not found:
        return None, False
    firestore.remember_email_runner_id(email, found[0])
    return found, await credentials.has_tp_credential(found[0])


@node(name="profile_router", rerun_on_resume=True)
async def profile_router(ctx: Context, node_input: Any = None) -> None:
    """Identifies the runner by email and routes. No blocking TrainingPeaks call, no shared credential.

    Web turns set `user:auth_email` and always reload Firestore so profile edits apply immediately.
    Evals and local runs reuse a session-cached `user_profile` when already present.
    """
    auth_email = normalize_email(ctx.state.get(AUTH_EMAIL_STATE_KEY))
    cached_profile = ctx.state.get("user_profile")
    known_id = profile_user_id(cached_profile) if isinstance(cached_profile, dict) else None
    profile = None if auth_email else cached_profile
    runner_id: Optional[str] = None
    if not profile:
        email = _caller_email(ctx)
        if not email:
            ctx.route = ROUTE_NOT_LINKED
            return
        try:
            found, connected = await _resolve_profile_and_connection(email, known_id)
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
        runner_id = found[0]
        profile = await activate_profile(ctx, *found)
    elif isinstance(profile, dict):
        runner_id = known_id

    if needs_onboarding(profile) or ctx.state.get("reonboard_requested"):
        ctx.state["temp_onboarding_data"] = onboarding_prefill(profile)
        ctx.route = ROUTE_ONBOARDING
        return

    _schedule_tp_warmup(runner_id)
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
