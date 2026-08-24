import asyncio
from typing import Any, Optional

from google.adk import Context

# Import clients and tools
from .tools import (
    db_client,
    get_tp_tool,
    geocode_location,
    parse_mcp_response,
    extract_health_metrics,
)
from .utils.date_helpers import (
    parse_date,
    get_today_date,
    get_today_str,
    get_past_date_str,
    calculate_age,
)
from .utils.profile_helpers import (
    parse_runner_name,
    sync_profile_to_state,
    merge_profile_data,
)

def check_timeline_expiration(profile: Optional[dict]) -> tuple[bool, Optional[str]]:
    """Compares today's date with the runner's profile timeline (YYYY-MM-DD).
    Returns (is_expired, timeline_date_str).
    """
    if not profile:
        return False, None
    timeline_str = profile.get("timeline")
    if not timeline_str:
        return False, None
        
    try:
        timeline_date = parse_date(timeline_str)
        if timeline_date and get_today_date() > timeline_date:
            return True, str(timeline_str).strip()
    except Exception as e:
        print(f"Error parsing timeline date '{timeline_str}': {e}")
    return False, None

async def check_profile_step(ctx: Context, tp_profile: Any) -> bool:
    """Process the TrainingPeaks profile and check if a Firestore profile exists.
    
    Returns:
        True if the profile exists (and is loaded into state), False otherwise.
    """
    ctx.state["temp_onboarding_data"] = {}
    
    profile_data = parse_mcp_response(tp_profile)
    if not profile_data or not isinstance(profile_data, dict):
        print("Error: Could not parse TP profile or it is not a dict.")
        return False
        
    name = profile_data.get("name", "").strip()
    if not name:
        print("Error: Name not found in TP profile.")
        return False
        
    firstname, lastname, user_id = parse_runner_name(name)
    
    try:
        doc_ref = db_client.collection("users").document(user_id)
        doc = await asyncio.to_thread(doc_ref.get)
        print(f"DEBUG: Firestore doc_id={user_id}, exists={doc.exists}")
        
        if doc.exists:
            profile = doc.to_dict()
            
            # Geocode and cache coordinates in Firestore if missing
            if "latitude" not in profile or "longitude" not in profile:
                loc = profile.get("location", "")
                if loc:
                    coords = await asyncio.to_thread(geocode_location, loc)
                    if coords:
                        profile["latitude"], profile["longitude"] = coords
                        await asyncio.to_thread(doc_ref.update, {"latitude": coords[0], "longitude": coords[1]})
                        print(f"Cached coordinates in Firestore: {coords}")

            sync_profile_to_state(ctx, profile)
            ctx.state["temp_onboarding_data"] = {
                "firstname": profile.get("firstname"),
                "lastname": profile.get("lastname"),
                "age": profile.get("age"),
                "height": profile.get("height"),
                "weight": profile.get("weight"),
                "location": profile.get("location"),
                "injuries": profile.get("injuries"),
                "recent_race_times": profile.get("recent_race_times"),
                "cross_training_strength": profile.get("cross_training_strength"),
                "shoe_rotation": profile.get("shoe_rotation"),
            }
            return True
    except Exception as e:
        print(f"Error checking Firestore profile for {user_id}: {e}")
        
    # Store harvested TP data in temp state to skip questions
    age = calculate_age(profile_data.get("birthDate"))
    ctx.state["temp_onboarding_data"] = {
        "firstname": firstname,
        "lastname": lastname,
        "age": age,
        "height": profile_data.get("height"),
        "weight": profile_data.get("weight"),
        "location": profile_data.get("city") or profile_data.get("country"),
    }
    return False

async def create_profile_step(ctx: Context) -> None:
    """Fetch metrics, calculate averages, and save the final profile to Firestore."""
    onboarding_answers = ctx.state.get("onboarding_answers", {})
    temp_data = ctx.state.get("temp_onboarding_data", {})
    
    firstname = temp_data.get("firstname") or onboarding_answers.get("firstname") or ""
    lastname = temp_data.get("lastname") or onboarding_answers.get("lastname") or ""
    _, _, user_id = parse_runner_name(f"{firstname} {lastname}")
    
    # 1. Fetch 14-day sleep average
    sleep_avg = 7.0
    try:
        start_date_metrics = get_past_date_str(days=14)
        end_date_str = get_today_str()
        tp_get_metrics_tool = await get_tp_tool("tp_get_metrics")
        raw_response = await ctx.run_node(
            tp_get_metrics_tool, 
            node_input={"start_date": start_date_metrics, "end_date": end_date_str}
        )
        extracted = extract_health_metrics(raw_response)
        sleep_hours = extracted.get("sleep", [])
        if sleep_hours:
            sleep_avg = round(sum(sleep_hours) / len(sleep_hours), 2)
    except Exception as e:
        print(f"Error fetching metrics for new profile: {e}")

    # 2. Non-blocking geocoding
    location = onboarding_answers.get("location") or temp_data.get("location") or ""
    lat, lon = None, None
    if location:
        coords = await asyncio.to_thread(geocode_location, location)
        if coords:
            lat, lon = coords

    # 3. Consolidate profile and persist to Firestore
    profile = merge_profile_data(
        answers=onboarding_answers,
        temp_data=temp_data,
        sleep_avg=sleep_avg,
        lat=lat,
        lon=lon,
        location=location
    )
    
    doc_ref = db_client.collection("users").document(user_id)
    await asyncio.to_thread(doc_ref.set, profile)
    sync_profile_to_state(ctx, profile)
    
    # Clean up temporary onboarding state
    ctx.state.pop("temp_onboarding_data", None)
    ctx.state.pop("onboarding_answers", None)
