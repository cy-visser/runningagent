from typing import Any, Optional

from .date_helpers import get_today_str, parse_date


def normalize_timeline(timeline: Optional[str]) -> Optional[str]:
    """Returns the goal date as ISO (YYYY-MM-DD) when parseable, else the raw value."""
    parsed = parse_date(timeline) if timeline else None
    return parsed.isoformat() if parsed else timeline


def get_user_id(firstname: Optional[str], lastname: Optional[str] = "") -> str:
    """Returns the canonical lowercase user_id for Firestore document keys."""
    fn = str(firstname or "").strip().lower()
    ln = str(lastname or "").strip().lower()
    return f"{fn}_{ln}"


def profile_user_id(profile: Optional[dict]) -> Optional[str]:
    """Returns the Firestore user_id for a profile, or None when it has no name."""
    profile = profile or {}
    user_id = get_user_id(profile.get("firstname"), profile.get("lastname"))
    return None if user_id == "_" else user_id


def parse_runner_name(raw_name: Optional[str]) -> tuple[str, str, str]:
    """Extracts (firstname, lastname, user_id) from a raw name string."""
    clean_name = str(raw_name or "").strip()
    if not clean_name:
        return ("", "", "_")
    parts = clean_name.split(maxsplit=1)
    firstname = parts[0]
    lastname = parts[1] if len(parts) > 1 else ""
    return firstname, lastname, get_user_id(firstname, lastname)


def format_profile_summary(profile: dict) -> str:
    """Formats a slim, token-efficient markdown summary of the runner's profile."""
    if not profile:
        return ""
    return (
        f"Name: {profile.get('firstname')} {profile.get('lastname')} (Age: {profile.get('age')})\n"
        f"Location: {profile.get('location')}\n"
        f"Stats: Height: {profile.get('height')}, Weight: {profile.get('weight')}\n"
        f"Goal: {profile.get('training_goal')} (Timeline: {profile.get('timeline')})\n"
        f"Recent Races: {profile.get('recent_race_times')}\n"
        f"Injuries: {profile.get('injuries')}\n"
        f"Cross-Training: {profile.get('cross_training_strength')}\n"
        f"Shoe Rotation: {profile.get('shoe_rotation')}"
    )


# ADK user-scoped state (shared across all sessions of the signed-in ADK user):
# remembers which Firestore runner profile belongs to this user.
RUNNER_ID_STATE_KEY = "user:runner_id"


def sync_profile_to_state(ctx: Any, profile: dict) -> None:
    """Sets user_profile, its slim summary and the user-scoped runner id in state."""
    ctx.state["user_profile"] = profile
    ctx.state["user_profile_summary"] = format_profile_summary(profile)
    user_id = profile_user_id(profile)
    if user_id and ctx.state.get(RUNNER_ID_STATE_KEY) != user_id:
        ctx.state[RUNNER_ID_STATE_KEY] = user_id


# Fields sourced from the runner's onboarding answers, falling back to data
# already harvested from the TrainingPeaks profile.
_MERGED_FIELDS = (
    "age",
    "height",
    "weight",
    "recent_race_times",
    "injuries",
    "cross_training_strength",
    "shoe_rotation",
)

# Profile fields pre-filled from an existing profile so (re-)onboarding can
# skip questions the runner has already answered.
_PREFILL_FIELDS = ("firstname", "lastname", "location", *_MERGED_FIELDS)


def onboarding_prefill(profile: dict) -> dict:
    """Returns the temp_onboarding_data seed for re-onboarding an existing runner."""
    return {f: profile.get(f) for f in _PREFILL_FIELDS}


def merge_profile_data(
    answers: dict,
    temp_data: dict,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    location: Optional[str] = None,
) -> dict:
    """Consolidates onboarding answers with harvested temp data into a runner profile.

    The runner's name is only ever sourced from `temp_data` (harvested from the
    TrainingPeaks profile); the onboarding schema does not collect it.
    """
    profile = {
        "firstname": temp_data.get("firstname") or "",
        "lastname": temp_data.get("lastname") or "",
        "location": location or answers.get("location") or temp_data.get("location") or "",
        "latitude": lat,
        "longitude": lon,
        "training_goal": answers.get("training_goal"),
        "timeline": normalize_timeline(answers.get("timeline")),
        # Onboarding only runs for new profiles or a new goal, so this marks the
        # start of the current training block (used by the race projection).
        "goal_set_date": get_today_str(),
    }
    for field in _MERGED_FIELDS:
        profile[field] = answers.get(field) or temp_data.get(field)
    return profile
