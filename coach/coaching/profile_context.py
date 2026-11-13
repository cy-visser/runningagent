"""Runner-profile context for the coaching agent.

`ensure_profile_context` is the coach's first `before_model_callback` and the ONLY place the
runner profile enters the prompt:

- It runs on every model call (typed turns, calls after tool results, quick-action reports), so
  the model always reasons with the profile.
- The block goes into the request's system instruction, which ADK rebuilds from scratch for each
  call and never stores in session history, so the profile is never accumulated across turns.
- The block is delimited and replaced if already present, so it appears exactly once per call.
- If `user_profile` is missing from state it is reloaded from Firestore; if that fails the call is
  short-circuited with the "profile unavailable" reply instead of coaching without the profile.
"""

import logging
import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from ...shared.dates import get_today_date
from ..profile_lookup import (
    PROFILE_UNAVAILABLE_MESSAGE,
    activate_profile,
    caller_email,
    find_profile_by_email,
)
from .instruction import PROFILE_CONTEXT_END, PROFILE_CONTEXT_START, build_profile_context
from .skill_toolset import SKILL_CATALOG_END

logger = logging.getLogger(__name__)

_PROFILE_BLOCK_RE = re.compile(
    rf"\n*{re.escape(PROFILE_CONTEXT_START)}.*?{re.escape(PROFILE_CONTEXT_END)}", re.DOTALL
)


def inject_profile_context(llm_request: LlmRequest, block: str) -> None:
    """Puts `block` in the system instruction exactly once (before conditional protocols for prefix caching)."""
    llm_request.config = llm_request.config or types.GenerateContentConfig()
    current = llm_request.config.system_instruction
    if current is not None and not isinstance(current, str):
        # ADK builds string system instructions; never silently drop the profile for other types.
        logger.warning("Unexpected system_instruction type %s; appending profile block", type(current))
        llm_request.append_instructions([block])
        return
    base = _PROFILE_BLOCK_RE.sub("", current or "").rstrip()
    if SKILL_CATALOG_END in base:
        head, tail = base.split(SKILL_CATALOG_END, 1)
        tail = tail.strip()
        prefix = f"{head}{SKILL_CATALOG_END}\n\n{block}"
        llm_request.config.system_instruction = f"{prefix}\n\n{tail}" if tail else prefix
        return
    llm_request.config.system_instruction = f"{base}\n\n{block}" if base else block


async def _reload_profile(callback_context: CallbackContext) -> Optional[dict]:
    """Reloads the caller's profile from Firestore into state; None when it cannot be loaded."""
    email = caller_email(callback_context.state)
    if not email:
        return None
    try:
        found = await find_profile_by_email(email)
        return await activate_profile(callback_context, *found) if found else None
    except Exception:
        logger.exception("Failed to reload the runner profile for %s", email)
        return None


async def ensure_profile_context(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: guarantees the runner profile is in the prompt exactly once."""
    profile = callback_context.state.get("user_profile")
    if not profile:
        logger.warning("user_profile missing from state at model call; reloading from Firestore")
        profile = await _reload_profile(callback_context)
    if not profile:
        return LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=PROFILE_UNAVAILABLE_MESSAGE)])
        )
    inject_profile_context(llm_request, build_profile_context(profile, get_today_date()))
    return None
