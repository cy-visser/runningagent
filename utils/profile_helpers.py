from typing import Optional, Any
from ..services.firestore import get_user_id

def parse_runner_name(raw_name: Optional[str]) -> tuple[str, str, str]:
    """Extracts (firstname, lastname, user_id) from a raw name string."""
    clean_name = str(raw_name or "").strip()
    if not clean_name:
        return ("", "", "_")
    parts = clean_name.split(maxsplit=1)
    firstname = parts[0]
    lastname = parts[1] if len(parts) > 1 else ""
    user_id = get_user_id(firstname, lastname)
    return firstname, lastname, user_id

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

def sync_profile_to_state(ctx: Any, profile: dict) -> None:
    """Atomically sets user_profile and its slim summary in the ADK session state."""
    ctx.state["user_profile"] = profile
    ctx.state["user_profile_summary"] = format_profile_summary(profile)

def merge_profile_data(
    answers: dict,
    temp_data: dict,
    sleep_avg: float = 7.0,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    location: Optional[str] = None
) -> dict:
    """Consolidates onboarding answers with temp data into a complete runner profile."""
    firstname = temp_data.get("firstname") or answers.get("firstname") or ""
    lastname = temp_data.get("lastname") or answers.get("lastname") or ""
    loc = location or answers.get("location") or temp_data.get("location") or ""
    
    return {
        "firstname": firstname,
        "lastname": lastname,
        "age": answers.get("age") or temp_data.get("age"),
        "height": answers.get("height") or temp_data.get("height"),
        "weight": answers.get("weight") or temp_data.get("weight"),
        "location": loc,
        "latitude": lat,
        "longitude": lon,
        "training_goal": answers.get("training_goal"),
        "timeline": answers.get("timeline"),
        "recent_race_times": answers.get("recent_race_times") or temp_data.get("recent_race_times"),
        "injuries": answers.get("injuries") or temp_data.get("injuries"),
        "cross_training_strength": answers.get("cross_training_strength") or temp_data.get("cross_training_strength"),
        "shoe_rotation": answers.get("shoe_rotation") or temp_data.get("shoe_rotation"),
        "sleep_hours_2w_avg": sleep_avg
    }
