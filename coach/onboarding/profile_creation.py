from datetime import date
from typing import Any, Optional

from ...integrations import firestore, open_meteo
from ...shared.dates import get_today_str, parse_date
from ...shared.goal_plan import GOAL_TYPE_PLAN, GOAL_TYPE_SINGLE
from ...shared.race_time import normalize_personal_records, normalize_shoe_rotation
from ...shared.runner_identity import normalize_email, profile_user_id
from ...shared.session_state import AUTH_EMAIL_STATE_KEY, sync_profile_to_state
import asyncio
import logging

from google.adk import Context

logger = logging.getLogger(__name__)

PROFILE_SAVED = "saved"
PROFILE_NO_NAME = "no_name"
PROFILE_EMAIL_CONFLICT = "email_conflict"


def normalize_timeline(timeline: Optional[str]) -> Optional[str]:
    """Returns the goal date as ISO (YYYY-MM-DD) when parseable, else the raw value."""
    parsed = parse_date(timeline) if timeline else None
    return parsed.isoformat() if parsed else timeline

# Fields sourced from the runner's onboarding answers, falling back to data
# already present on the profile skeleton.
_MERGED_FIELDS = (
    "age",
    "height",
    "weight",
    "personal_records",
    "injuries",
    "cross_training_strength",
    "shoe_rotation",
)
# Structured fields normalised on merge (answer first, then the existing profile value).
_STRUCTURED_NORMALIZERS = {
    "personal_records": normalize_personal_records,
    "shoe_rotation": normalize_shoe_rotation,
}

# Profile fields pre-filled from an existing profile so (re-)onboarding can
# skip questions the runner has already answered and preserve immutable identity fields.
_PREFILL_FIELDS = ("firstname", "lastname", "email", "location", *_MERGED_FIELDS)

# Current goal fields shown to the onboarding agent on re-onboarding (and used by
# merge_profile_data to keep saved sub-goal results).
_GOAL_PREFILL_FIELDS = ("goal_type", "training_goal", "timeline", "north_star", "sub_goals")


def onboarding_prefill(profile: dict) -> dict:
    """Returns the temp_onboarding_data seed for onboarding or re-onboarding a runner."""
    seed = {f: profile.get(f) for f in _PREFILL_FIELDS}
    seed.update({f: profile.get(f) for f in _GOAL_PREFILL_FIELDS if profile.get(f) is not None})
    return seed


def _sub_goal_key(sub_goal: dict) -> tuple:
    return (
        str(sub_goal.get("goal") or "").strip().lower(),
        normalize_timeline(sub_goal.get("race_date")),
    )


def _plan_fields(answers: dict, previous_sub_goals: Any) -> dict:
    """north_star + sorted sub_goals from onboarding answers; saved results survive re-onboarding."""
    saved_results = {
        _sub_goal_key(s): s.get("result")
        for s in previous_sub_goals or []
        if isinstance(s, dict) and s.get("result")
    }
    sub_goals = []
    for answer in answers.get("sub_goals") or []:
        if not isinstance(answer, dict):
            continue
        sub_goal = {
            "goal": answer.get("goal"),
            "race_name": answer.get("race_name"),
            "start_date": normalize_timeline(answer.get("start_date")),
            "race_date": normalize_timeline(answer.get("race_date")),
            "taper_weeks": answer.get("taper_weeks"),
        }
        sub_goal["result"] = saved_results.get(_sub_goal_key(sub_goal))
        sub_goals.append(sub_goal)
    sub_goals.sort(key=lambda s: parse_date(s["race_date"]) or date.max)
    return {
        "goal_type": GOAL_TYPE_PLAN,
        "north_star": {
            "goal": answers.get("north_star_goal"),
            "race_name": answers.get("north_star_race_name"),
            "start_date": normalize_timeline(answers.get("north_star_start_date")),
            "race_date": normalize_timeline(answers.get("north_star_race_date")),
            "taper_weeks": answers.get("taper_weeks"),
        },
        "sub_goals": sub_goals,
        "training_goal": None,
        "timeline": None,
        "taper_weeks": None,
    }


def merge_profile_data(
    answers: dict,
    temp_data: dict,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    location: Optional[str] = None,
) -> dict:
    """Consolidates onboarding answers with prefill data into a runner profile.

    The runner's name and email come from `temp_data` (populated from TrainingPeaks and
    verified sign-in when the account was connected); the onboarding schema does not
    collect them, and `onboarding_pending` is cleared by omission.
    A goal plan (north star + sub goals) replaces training_goal/timeline; the
    active block is derived from it on read (see shared.goal_plan.current_goal).
    """
    profile: dict[str, Any] = {
        "firstname": temp_data.get("firstname") or "",
        "lastname": temp_data.get("lastname") or "",
        "location": location or answers.get("location") or temp_data.get("location") or "",
        "latitude": lat,
        "longitude": lon,
        "goal_type": GOAL_TYPE_SINGLE,
        "training_goal": answers.get("training_goal"),
        "timeline": normalize_timeline(answers.get("timeline")),
        # Optional taper override for this goal; None -> goal-distance default.
        "taper_weeks": answers.get("taper_weeks"),
        # Onboarding only runs for new profiles or a new goal, so this marks the
        # start of the current training block (used by the race projection).
        "goal_set_date": get_today_str(),
    }
    email = normalize_email(temp_data.get("email"))
    if email:
        profile["email"] = email
    if answers.get("goal_type") == GOAL_TYPE_PLAN:
        profile.update(_plan_fields(answers, temp_data.get("sub_goals")))
    for field in _MERGED_FIELDS:
        normalize = _STRUCTURED_NORMALIZERS.get(field)
        if normalize:
            profile[field] = normalize(answers.get(field)) or normalize(temp_data.get(field))
        else:
            profile[field] = answers.get(field) or temp_data.get(field)
    return profile


def _as_dict(value: Any) -> dict:
    """Normalises ADK structured output (pydantic model or dict) into a plain dict."""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return {}


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

    existing = await firestore.get_user_profile(user_id)
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
        coords = await asyncio.to_thread(open_meteo.geocode_location, location)
        if coords:
            lat, lon = coords

    profile = merge_profile_data(
        answers=onboarding_answers,
        temp_data=temp_data,
        lat=lat,
        lon=lon,
        location=location,
    )

    await firestore.save_user_profile(user_id, profile)
    sync_profile_to_state(ctx, profile)

    ctx.state["temp_onboarding_data"] = None
    ctx.state["onboarding_answers"] = None
    return PROFILE_SAVED
