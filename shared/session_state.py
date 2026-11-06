"""Shared ADK session-state keys and profile state synchronisation."""

from typing import Any

# ADK user-scoped state key set by the Cloud Run web backend on every turn with the IAP-verified email.
AUTH_EMAIL_STATE_KEY = "user:auth_email"


def sync_profile_to_state(ctx: Any, profile: dict) -> None:
    """Stores `user_profile` in session state.

    Everything else the coach needs (date, summary, goal plan) is derived from the
    profile when the instruction is built, so it is not duplicated in state.
    """
    ctx.state["user_profile"] = profile
