from typing import Any, Optional

from .date_helpers import get_today_str


def get_user_id(firstname: Optional[str], lastname: Optional[str] = "") -> str:
    """Returns the canonical lowercase user_id for Firestore document keys."""
    fn = str(firstname or "").strip().lower()
    ln = str(lastname or "").strip().lower()
    return f"{fn}_{ln}"


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
        f"Location: {profile.get('location')} (Lat: {profile.get('latitude')}, Lon: {profile.get('longitude')})\n"
        f"Stats: Height: {profile.get('height')}, Weight: {profile.get('weight')}\n"
        f"Goal: {profile.get('training_goal')} (Timeline: {profile.get('timeline')})\n"
        f"Recent Races: {profile.get('recent_race_times')}\n"
        f"Injuries: {profile.get('injuries')}\n"
        f"Cross-Training: {profile.get('cross_training_strength')}\n"
        f"Shoe Rotation: {profile.get('shoe_rotation')}\n"
        f"Sleep Avg (2w): {profile.get('sleep_hours_2w_avg')}h"
    )


# ADK user-scoped state (shared across all sessions of the signed-in ADK user):
# remembers which Firestore runner profile belongs to this user.
RUNNER_ID_STATE_KEY = "user:runner_id"


def sync_profile_to_state(ctx: Any, profile: dict) -> None:
    """Sets user_profile, user_id, its slim summary and the user-scoped runner id in state."""
    ctx.state["user_profile"] = profile
    ctx.state["user_profile_summary"] = format_profile_summary(profile)
    fn = profile.get("firstname")
    ln = profile.get("lastname")
    if fn or ln:
        user_id = get_user_id(fn, ln)
        ctx.state["user_id"] = user_id
        if ctx.state.get(RUNNER_ID_STATE_KEY) != user_id:
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


def merge_profile_data(
    answers: dict,
    temp_data: dict,
    sleep_avg: float = 7.0,
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
        "timeline": answers.get("timeline"),
        # Onboarding only runs for new profiles or a new goal, so this marks the
        # start of the current training block (used by the race projection).
        "goal_set_date": get_today_str(),
        "sleep_hours_2w_avg": sleep_avg,
    }
    for field in _MERGED_FIELDS:
        profile[field] = answers.get(field) or temp_data.get(field)
    return profile
