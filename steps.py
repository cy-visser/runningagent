import asyncio
from datetime import datetime, timedelta
import json
from typing import Any
from google.adk.events.event import Event

# Import clients and tools from tools.py
from .tools import db_client, get_tp_tool, geocode_location, parse_mcp_response, extract_health_metrics, calculate_weekly_mileage

def format_profile_summary(profile: dict) -> str:
    """Formats a slim, token-efficient markdown summary of the runner's profile."""
    return (
        f"Name: {profile.get('firstname')} {profile.get('lastname')} (Age: {profile.get('age')})\n"
        f"Location: {profile.get('location')} (Lat: {profile.get('latitude')}, Lon: {profile.get('longitude')})\n"
        f"Stats: Height: {profile.get('height')}, Weight: {profile.get('weight')}\n"
        f"Goal: {profile.get('training_goal')} (Timeline: {profile.get('timeline')})\n"
        f"Recent Races: {profile.get('recent_race_times')}\n"
        f"Injuries: {profile.get('injuries')}\n"
        f"Cross-Training: {profile.get('cross_training_strength')}\n"
        f"Sleep Avg (2w): {profile.get('sleep_hours_2w_avg')}h | Weekly Mileage Avg (1m): {profile.get('weekly_mileage_past_month')}km\n"
        f"Last Communication: {profile.get('last_active', 'Never')}"
    )

async def check_profile_step(ctx: Any, tp_profile: Any) -> bool:
    """Process the TrainingPeaks profile and check if a Firestore profile exists.
    
    Returns:
        True if the profile exists (and is loaded into state), False otherwise.
    """
    print(f"DEBUG: tp_profile type={type(tp_profile)}, value={tp_profile}")
    
    # Initialize temp_onboarding_data to an empty dict to prevent prompt formatting errors
    ctx.state["temp_onboarding_data"] = {}
    
    # Parse the MCP envelope
    profile_data = parse_mcp_response(tp_profile)
    if not profile_data or not isinstance(profile_data, dict):
        print("Error: Could not parse TP profile or it is not a dict.")
        return False
        
    name = profile_data.get("name", "").strip()
    if not name:
        print("Error: Name not found in TP profile.")
        return False
        
    # Split name into first and last name
    parts = name.split(maxsplit=1)
    firstname = parts[0]
    lastname = parts[1] if len(parts) > 1 else ""
    
    user_id = f"{firstname.lower()}_{lastname.lower()}"
    
    try:
        doc_ref = db_client.collection("users").document(user_id)
        doc = doc_ref.get()
        print(f"DEBUG: Firestore doc_id={user_id}, exists={doc.exists}")
        if doc.exists:
            profile = doc.to_dict()
            
            # Geocode and cache coordinates in Firestore if missing
            if "latitude" not in profile or "longitude" not in profile:
                print(f"Coordinates missing for {name}. Geocoding...")
                coords = geocode_location(profile.get("location", ""))
                if coords:
                    profile["latitude"], profile["longitude"] = coords
                    doc_ref.update({"latitude": coords[0], "longitude": coords[1]})
                    print(f"Cached coordinates in Firestore: {coords}")
            
            
            ctx.state["user_profile"] = profile
            # Generate and store the slim token-efficient summary
            ctx.state["user_profile_summary"] = format_profile_summary(profile)
            return True
    except Exception as e:
        print(f"Error checking profile: {e}")
        
    # Store harvested TP data in temp state to skip questions
    dob_str = profile_data.get("birthDate")
    age = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str.split("T")[0], "%Y-%m-%d")
            age = str((datetime.now() - dob).days // 365)
        except:
            pass
            
    ctx.state["temp_onboarding_data"] = {
        "firstname": firstname,
        "lastname": lastname,
        "age": age,
        "height": profile_data.get("height"),
        "weight": profile_data.get("weight"),
        "location": profile_data.get("city") or profile_data.get("country"),
    }
    return False

async def create_profile_step(ctx: Any) -> None:
    """Fetch metrics, calculate averages, and save the final profile to Firestore."""
    onboarding_answers = ctx.state.get("onboarding_answers", {})
    temp_data = ctx.state.get("temp_onboarding_data", {})
    
    firstname = temp_data.get("firstname")
    lastname = temp_data.get("lastname")
    user_id = f"{firstname.lower()}_{lastname.lower()}"
    
    today = datetime.now()
    end_date_str = today.strftime("%Y-%m-%d")
    
    # Fetch metrics and workouts concurrently to optimize network latency
    sleep_avg = 7.0
    weekly_mileage = 0.0
    
    async def fetch_sleep_avg():
        try:
            start_date_metrics = (today - timedelta(days=14)).strftime("%Y-%m-%d")
            tp_get_metrics_tool = await get_tp_tool("tp_get_metrics")
            raw_response = await ctx.run_node(
                tp_get_metrics_tool, 
                node_input={"start_date": start_date_metrics, "end_date": end_date_str}
            )
            extracted = extract_health_metrics(raw_response)
            sleep_hours = extracted["sleep"]
            if sleep_hours:
                return round(sum(sleep_hours) / len(sleep_hours), 2)
        except Exception as e:
            print(f"Error fetching metrics: {e}")
        return 7.0
        
    async def fetch_weekly_mileage():
        try:
            start_date_workouts = (today - timedelta(days=28)).strftime("%Y-%m-%d")
            tp_get_workouts_tool = await get_tp_tool("tp_get_workouts")
            raw_response = await ctx.run_node(
                tp_get_workouts_tool,
                node_input={"start_date": start_date_workouts, "end_date": end_date_str}
            )
            return calculate_weekly_mileage(raw_response, weeks=4.0)
        except Exception as e:
            print(f"Error fetching workouts: {e}")
        return 0.0

    sleep_avg, weekly_mileage = await asyncio.gather(
        fetch_sleep_avg(),
        fetch_weekly_mileage()
    )

    # Geocode location during profile creation
    location = onboarding_answers.get("location") or temp_data.get("location") or ""
    lat, lon = None, None
    if location:
        print(f"Geocoding location '{location}' for new profile...")
        coords = geocode_location(location)
        if coords:
            lat, lon = coords
            print(f"Geocoded to: {coords}")

    # 3. Build profile (Streamlined: 9 core fields + coordinates)
    profile = {
        "firstname": firstname,
        "lastname": lastname,
        "age": onboarding_answers.get("age") or temp_data.get("age"),
        "height": onboarding_answers.get("height") or temp_data.get("height"),
        "weight": onboarding_answers.get("weight") or temp_data.get("weight"),
        "location": location,
        "latitude": lat,
        "longitude": lon,
        "training_goal": onboarding_answers.get("training_goal"),
        "timeline": onboarding_answers.get("timeline"),
        "recent_race_times": onboarding_answers.get("recent_race_times"),
        "injuries": onboarding_answers.get("injuries"),
        "cross_training_strength": onboarding_answers.get("cross_training_strength"),
        "sleep_hours_2w_avg": sleep_avg,
        "weekly_mileage_past_month": weekly_mileage,
        "last_active": datetime.now().strftime("%Y-%m-%d")
    }
    
    # Save to Firestore & State
    db_client.collection("users").document(user_id).set(profile)
    ctx.state["user_profile"] = profile
    # Generate and store the slim token-efficient summary
    ctx.state["user_profile_summary"] = format_profile_summary(profile)
    
    # Clean up temp state
    ctx.state.pop("temp_onboarding_data", None)
    ctx.state.pop("onboarding_answers", None)

async def update_last_active_step(ctx: Any) -> None:
    """Updates the last_active timestamp in Firestore and session state."""
    profile = ctx.state.get("user_profile")
    if not profile:
        return
        
    firstname = profile.get("firstname")
    lastname = profile.get("lastname")
    if not firstname:
        return
        
    user_id = f"{firstname.lower()}_{lastname.lower()}"
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Only update if the date has changed
    if profile.get("last_active") == today_str:
        return
        
    # Update local state
    profile["last_active"] = today_str
    ctx.state["user_profile"] = profile
    ctx.state["user_profile_summary"] = format_profile_summary(profile)
    
    # Update Firestore
    try:
        db_client.collection("users").document(user_id).update({"last_active": today_str})
        print(f"DEBUG: Updated last_active to {today_str} for {user_id}")
    except Exception as e:
        print(f"Error updating last_active: {e}")
