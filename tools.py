from datetime import datetime, timedelta
import asyncio
import os
import urllib.request
import urllib.parse
import json
import shutil
from typing import Optional, Any
from google.adk.tools import FunctionTool, ToolContext, McpToolset
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.skills import load_skill_from_dir
from google.cloud import firestore
from google.genai import types
from mcp import StdioServerParameters
from google.adk.code_executors import UnsafeLocalCodeExecutor

# --- Clients ---
project = os.environ.get("FIRESTORE_PROJECT_ID")
database = os.environ.get("FIRESTORE_DATABASE", "running-coach")
db_client = firestore.Client(project=project, database=database)

# --- Helper Tools ---
def parse_mcp_response(response: Any) -> Any:
    """Parses the JSON payload from a raw MCP tool response envelope."""
    if not response or not isinstance(response, dict):
        print(f"DEBUG: parse_mcp_response received invalid response type: {type(response)}")
        return None
    content = response.get("content", [])
    if not content:
        print(f"DEBUG: parse_mcp_response received empty content. Full response: {response}")
        return None
    text = content[0].get("text", "")
    if not text:
        print(f"DEBUG: parse_mcp_response received empty text. Full response: {response}")
        return None
    try:
        return json.loads(text)
    except Exception as e:
        print(f"Error parsing MCP JSON: {e}")
        print(f"DEBUG: Raw text that failed to parse (first 500 chars): {text[:500]}")
        return None

def get_current_date() -> str:
    return datetime.now().strftime("%Y-%m-%d (%A)")

current_date_tool = FunctionTool(get_current_date)

def geocode_location(location: str) -> Optional[tuple[float, float]]:
    """Helper to geocode a location string to (latitude, longitude)."""
    try:
        # Sanitize: take the first part before any comma (e.g., "Amsterdam, Netherlands" -> "Amsterdam")
        city = location.split(",")[0].strip() if location else ""
        if not city:
            return None
        geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=en&format=json"
        req = urllib.request.Request(geocode_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            geocode_data = json.loads(response.read().decode())
        if geocode_data.get("results"):
            result = geocode_data["results"][0]
            return float(result["latitude"]), float(result["longitude"])
    except Exception as e:
        print(f"Geocoding error: {e}")
    return None

def get_weather_for_dates(location: str, dates: list[str], lat: Optional[float] = None, lon: Optional[float] = None) -> str:
    """Fetches weather data (daily and hourly) for a list of dates/timestamps in a single API call.
    Bypasses geocoding if lat and lon are provided.
    
    Args:
        location: The city and country (e.g., "Amsterdam, Netherlands").
        dates: A list of date/timestamp strings (e.g., "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS").
        lat: Optional latitude float.
        lon: Optional longitude float.
    """
    print(f"DEBUG: get_weather_for_dates called for location='{location}' with dates={dates}")
    if not dates:
        return "No dates provided."
        
    try:
        resolved_name = location
        if lat is None or lon is None:
            # Fallback to geocoding if coordinates not provided
            coords = geocode_location(location)
            if not coords:
                return f"Could not geocode location: {location}"
            lat, lon = coords
            
        # Parse dates/timestamps to find the min and max dates for the range query
        parsed_dates = []
        input_mapping = [] # List of (input_str, date_str, hour_int)
        
        for d in dates:
            # Check if it is a timestamp (e.g., has 'T' or ' ')
            if "T" in d or " " in d:
                # Replace space with T for consistency
                d_clean = d.replace(" ", "T")
                try:
                    # Parse up to seconds, ignoring milliseconds if present
                    dt = datetime.strptime(d_clean.split(".")[0], "%Y-%m-%dT%H:%M:%S")
                    parsed_dates.append(dt.date())
                    input_mapping.append((d, dt.strftime("%Y-%m-%d"), dt.hour))
                except Exception as e:
                    print(f"Error parsing timestamp '{d}': {e}")
                    # Fallback to date only
                    date_part = d[:10]
                    parsed_dates.append(datetime.strptime(date_part, "%Y-%m-%d").date())
                    input_mapping.append((d, date_part, None))
            else:
                try:
                    parsed_dates.append(datetime.strptime(d[:10], "%Y-%m-%d").date())
                    input_mapping.append((d, d[:10], None))
                except Exception as e:
                    print(f"Error parsing date '{d}': {e}")
                
        if not parsed_dates:
            return "No valid dates could be parsed."
            
        min_date = min(parsed_dates)
        max_date = max(parsed_dates)
        
        # Check if the max_date is too far in the future (Open-Meteo forecast limit is 16 days)
        today_date = datetime.now().date()
        if max_date > today_date + timedelta(days=16):
            limit_date_str = (today_date + timedelta(days=16)).strftime("%Y-%m-%d")
            return (
                f"Weather forecast is only available up to 16 days in advance. "
                f"Cannot fetch live weather for dates beyond {limit_date_str} (requested range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')})."
            )
            
        start_date_str = min_date.strftime("%Y-%m-%d")
        end_date_str = max_date.strftime("%Y-%m-%d")
        
        # Fetch both daily and hourly weather in one call
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&start_date={start_date_str}&end_date={end_date_str}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
            f"&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m"
            f"&timezone=auto"
        )
            
        req = urllib.request.Request(weather_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            weather_data = json.loads(response.read().decode())
            
        daily = weather_data.get("daily", {})
        hourly = weather_data.get("hourly", {})
        
        if not daily or not daily.get("temperature_2m_max"):
            return f"No weather data available for {resolved_name} in range {start_date_str} to {end_date_str}."
            
        # 1. Process Daily Weather
        times_daily = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precips_daily = daily.get("precipitation_sum", [])
        winds_daily = daily.get("wind_speed_10m_max", [])
        
        daily_units = weather_data.get("daily_units", {})
        temp_unit = daily_units.get("temperature_2m_max", "°C")
        precip_unit = daily_units.get("precipitation_sum", "mm")
        wind_unit = daily_units.get("wind_speed_10m_max", "km/h")
        
        daily_map = {}
        for i, t_str in enumerate(times_daily):
            daily_map[t_str] = {
                "max_temp": f"{max_temps[i]}{temp_unit}",
                "min_temp": f"{min_temps[i]}{temp_unit}",
                "precipitation": f"{precips_daily[i]}{precip_unit}",
                "max_wind": f"{winds_daily[i]}{wind_unit}"
            }
            
        # 2. Process Hourly Weather
        times_hourly = hourly.get("time", [])
        temps_hourly = hourly.get("temperature_2m", [])
        humidity_hourly = hourly.get("relative_humidity_2m", [])
        apparent_hourly = hourly.get("apparent_temperature", [])
        precips_hourly = hourly.get("precipitation", [])
        winds_hourly = hourly.get("wind_speed_10m", [])
        
        hourly_units = weather_data.get("hourly_units", {})
        h_temp_unit = hourly_units.get("temperature_2m", "°C")
        h_humidity_unit = hourly_units.get("relative_humidity_2m", "%")
        h_precip_unit = hourly_units.get("precipitation", "mm")
        h_wind_unit = hourly_units.get("wind_speed_10m", "km/h")
        
        hourly_map = {}
        for i, t_str in enumerate(times_hourly):
            # t_str is like "2026-06-26T06:00"
            hourly_map[t_str] = {
                "temp": f"{temps_hourly[i]}{h_temp_unit}",
                "humidity": f"{humidity_hourly[i]}{h_humidity_unit}",
                "apparent": f"{apparent_hourly[i]}{h_temp_unit}",
                "precipitation": f"{precips_hourly[i]}{h_precip_unit}",
                "wind": f"{winds_hourly[i]}{h_wind_unit}"
            }
            
        # 3. Compile results for the requested dates/timestamps
        results = []
        for input_str, date_str, hour_int in input_mapping:
            d_weather = daily_map.get(date_str)
            if not d_weather:
                results.append(f"- {input_str}: No weather data found.")
                continue
                
            daily_summary_str = (
                f"Daily Max: {d_weather['max_temp']}, Daily Min: {d_weather['min_temp']}, "
                f"Precipitation: {d_weather['precipitation']}, Max Wind: {d_weather['max_wind']}"
            )
            
            if hour_int is not None:
                # Find the hourly weather for this hour
                target_hour_str = f"{date_str}T{hour_int:02d}:00"
                h_weather = hourly_map.get(target_hour_str)
                if h_weather:
                    results.append(
                        f"- {input_str}: Temp at run time: {h_weather['temp']} (Feels like: {h_weather['apparent']}), "
                        f"Humidity: {h_weather['humidity']}, Wind: {h_weather['wind']}, Precip: {h_weather['precipitation']} | "
                        f"[{daily_summary_str}]"
                    )
                else:
                    results.append(f"- {input_str}: {daily_summary_str} (Hourly data missing for {target_hour_str})")
            else:
                results.append(f"- {input_str}: {daily_summary_str}")
                
        return f"Weather in {resolved_name} for requested dates/times:\n" + "\n".join(results)
        
    except Exception as e:
        print(f"Error in get_weather_for_dates: {e}")
        return f"Error fetching weather data: {e}"

get_weather_tool = FunctionTool(get_weather_for_dates)

# --- Shared TrainingPeaks Data Parsing Helpers (DRY) ---
def extract_health_metrics(metrics_raw: Any) -> dict[str, list[float]]:
    """Extracts sleep, HRV, and RHR (Pulse) values from raw TrainingPeaks metrics.
    Returns a dictionary of lists: {'sleep': [...], 'hrv': [...], 'rhr': [...]}
    """
    metrics_data = parse_mcp_response(metrics_raw) or {}
    metrics_list = metrics_data.get("metrics", [])
    
    sleep_hours = []
    hrv_values = []
    rhr_values = []
    
    if isinstance(metrics_list, list):
        for m in metrics_list:
            details = m.get("details", [])
            for detail in details:
                val = detail.get("value")
                if val is None:
                    continue
                m_type = detail.get("type")
                if m_type == 6:     # Sleep
                    sleep_hours.append(val)
                elif m_type == 60:   # HRV
                    hrv_values.append(val)
                elif m_type == 5:    # Pulse (RHR)
                    rhr_values.append(val)
                    
    return {
        "sleep": sleep_hours,
        "hrv": hrv_values,
        "rhr": rhr_values
    }

def calculate_weekly_mileage(workouts_raw: Any, weeks: float = 4.0) -> float:
    """Calculates average weekly running mileage (in km) from raw workouts over a given number of weeks."""
    workouts_data = parse_mcp_response(workouts_raw) or {}
    workouts_list = workouts_data.get("workouts", [])
    
    total_dist = 0.0
    if isinstance(workouts_list, list):
        run_distances = [
            w.get("distance_actual_km", 0.0)
            for w in workouts_list
            if w.get("sport") == "Run" and w.get("type") == "completed"
        ]
        total_dist = sum(run_distances)
        
    return round(total_dist / weeks, 2)

# --- TrainingPeaks MCP Toolset ---
current_dir = os.path.dirname(os.path.abspath(__file__))
tp_mcp_path = shutil.which("tp-mcp") or os.path.join(
    current_dir, "trainingpeaks-mcp", ".venv", "bin", "tp-mcp"
)
def inject_production_secrets():
    """Injects secrets from GCP Secret Manager into environment variables at runtime in production."""
    if not os.environ.get("K_SERVICE"):
        return  # Local development; rely on local .env file
        
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = "projects/firestore-cyvisser/secrets/tp-auth-cookie/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        cookie_value = response.payload.data.decode("UTF-8").strip()
        
        # Inject into environment so the MCP subprocess inherits it
        os.environ["TP_AUTH_COOKIE"] = cookie_value
        print("DEBUG: Successfully injected TP_AUTH_COOKIE from Secret Manager.")
    except Exception as e:
        print(f"Error injecting production secrets: {e}")

# Call this during module initialization to ensure the MCP subprocess inherits it
inject_production_secrets()

cookie_value = os.environ.get("TP_AUTH_COOKIE")
tp_env = {"TP_AUTH_COOKIE": cookie_value} if cookie_value else None

_tp_toolset = None

async def get_tp_tool(name: str) -> Any:
    """Asynchronously retrieves a specific tool from the TrainingPeaks MCP toolset by name."""
    global _tp_toolset
    if _tp_toolset is None:
        _tp_toolset = McpToolset(
            connection_params=StdioServerParameters(
                command=tp_mcp_path,
                args=["serve"],
                env=tp_env
            )
        )
    tools = await _tp_toolset.get_tools()
    try:
        return next(t for t in tools if t.name == name)
    except StopIteration:
        raise ValueError(f"Tool '{name}' not found in TrainingPeaks MCP toolset.")

# --- Skills ---
nutrition_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "nutrition-planner"))
checkin_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "check-in-report"))
workout_analysis_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "workout-analysis"))
skill_toolset = SkillToolset(
    skills=[nutrition_skill, checkin_skill, workout_analysis_skill],
    code_executor=UnsafeLocalCodeExecutor()
)

# --- Artifacts Tool ---
async def save_report_to_artifacts(
    filename: str,
    content_markdown: str,
    tool_context: ToolContext
) -> str:
    """Saves a structured coaching report (markdown) to the session artifacts.
    
    Args:
        filename: The filename of the report (e.g., 'weekly_checkin_report.md').
        content_markdown: The markdown content of the report.
    """
    try:
        part = types.Part(text=content_markdown)
        await tool_context.save_artifact(filename=filename, artifact=part)
        return f"Successfully saved and rendered '{filename}' in artifacts."
    except Exception as e:
        return f"Failed to save report to artifacts: {e}"

save_artifacts_tool = FunctionTool(save_report_to_artifacts)

# --- Consolidated Check-In Tool ---
def compile_data_summary(
    n_days: int,
    workouts_past_raw: Any,
    workouts_future_raw: Any,
    metrics_raw: Any,
    fitness_raw: Any,
    notes_raw: Any
) -> str:
    """Parses and compiles a highly compact, token-efficient summary of the runner's data."""
    
    # 1. Summarize past workouts (if available)
    workouts_past_summary = ""
    if workouts_past_raw is not None:
        workouts_past_data = parse_mcp_response(workouts_past_raw) or {}
        workouts_past = workouts_past_data.get("workouts", [])
        completed_runs = []
        completed_strength = 0
        for w in workouts_past:
            if w.get("type") == "completed":
                sport = w.get("sport", "")
                w_title = w.get("title", "").lower()
                if sport == "Run":
                    dist_km = w.get("distance_actual_km") or 0.0
                    dist_km = round(dist_km, 2)
                    planned_km = w.get("distance_planned_km") or 0.0
                    planned_km = round(planned_km, 2)
                    actual_tss = w.get("tss_actual") or w.get("tss") or 0
                    planned_tss = w.get("tss_planned") or 0
                    w_id = w.get("id", "")
                    time_identifier = w.get("start_time") or w.get("date", "")
                    completed_runs.append(
                        f"- Run [ID: {w_id}] on {time_identifier}: {dist_km}km (Planned: {planned_km}km) | TSS: {actual_tss} (Planned: {planned_tss})"
                    )
                elif "strength" in sport.lower() or "strength" in w_title:
                    completed_strength += 1
        workouts_past_summary = "\n".join(completed_runs) if completed_runs else "No completed runs."
        workouts_past_summary += f"\n- Completed Strength Sessions: {completed_strength}"

    # 2. Summarize upcoming workouts (if available)
    workouts_future_summary = ""
    if workouts_future_raw is not None:
        workouts_future_data = parse_mcp_response(workouts_future_raw) or {}
        workouts_future = workouts_future_data.get("workouts", [])
        upcoming_runs = []
        for w in workouts_future:
            if w.get("sport") == "Run":
                planned_km = w.get("distance_planned_km") or 0.0
                planned_km = round(planned_km, 2)
                planned_tss = w.get("tss_planned") or 0
                w_id = w.get("id", "")
                date_str = w.get("date", "")[:10]
                upcoming_runs.append(
                    f"- Planned Run [ID: {w_id}] on {date_str}: {planned_km}km | Planned TSS: {planned_tss}"
                )
        workouts_future_summary = "\n".join(upcoming_runs) if upcoming_runs else "No upcoming runs planned."

    # 3. Summarize recovery metrics (if available)
    metrics_summary = ""
    if metrics_raw is not None:
        extracted = extract_health_metrics(metrics_raw)
        sleep_hours = extracted["sleep"]
        hrv_clean = extracted["hrv"]
        rhr_clean = extracted["rhr"]
        
        sleep_avg = round(sum(sleep_hours) / len(sleep_hours), 2) if sleep_hours else "N/A"
        hrv_trend = ", ".join(str(h) for h in hrv_clean) if hrv_clean else "N/A"
        hrv_latest = hrv_clean[-1] if hrv_clean else "N/A"
        rhr_trend = ", ".join(str(r) for r in rhr_clean) if rhr_clean else "N/A"
        rhr_latest = rhr_clean[-1] if rhr_clean else "N/A"
        
        metrics_summary = (
            f"- Sleep Duration: Average of {sleep_avg} hours/night\n"
            f"- HRV Trend (past to latest): [{hrv_trend}] (Latest: {hrv_latest}ms)\n"
            f"- Resting Heart Rate (RHR) Trend (past to latest): [{rhr_trend}] bpm (Latest: {rhr_latest} bpm)"
        )

    # 3.5. Summarize calendar notes (if available)
    notes_summary = ""
    if notes_raw is not None:
        notes_data = parse_mcp_response(notes_raw) or {}
        notes_list = notes_data.get("notes", [])
        notes_summary_list = []
        for n in notes_list:
            n_date = n.get("date")
            n_title = n.get("title") or "Note"
            n_desc = n.get("description") or ""
            notes_summary_list.append(f"- {n_date}: {n_title} | {n_desc}")
        notes_summary = "\n".join(notes_summary_list) if notes_summary_list else "No calendar notes."

    # 4. Summarize fitness PMC trends (if available)
    fitness_summary = ""
    if fitness_raw is not None:
        fitness_data = parse_mcp_response(fitness_raw) or {}
        fitness_list = fitness_data.get("daily_data", [])
        ctl_start, ctl_end = "N/A", "N/A"
        atl_start, atl_end = "N/A", "N/A"
        tsb_start, tsb_end = "N/A", "N/A"
        if isinstance(fitness_list, list) and len(fitness_list) > 0:
            try:
                fitness_sorted = sorted(fitness_list, key=lambda x: x.get("date", ""))
                start_entry = fitness_sorted[0]
                end_entry = fitness_sorted[-1]
                ctl_start = round(start_entry.get("ctl", 0), 1)
                ctl_end = round(end_entry.get("ctl", 0), 1)
                atl_start = round(start_entry.get("atl", 0), 1)
                atl_end = round(end_entry.get("atl", 0), 1)
                tsb_start = round(start_entry.get("tsb", 0), 1)
                tsb_end = round(end_entry.get("tsb", 0), 1)
            except Exception as e:
                print(f"Error parsing fitness trend: {e}")
        fitness_summary = (
            f"- CTL (Fitness): Started at {ctl_start} -> Ended at {ctl_end}\n"
            f"- ATL (Fatigue): Started at {atl_start} -> Ended at {atl_end}\n"
            f"- TSB (Form/Readiness): Started at {tsb_start} -> Ended at {tsb_end}"
        )

    # Build the final output dynamically
    parts = []
    if workouts_past_raw is not None:
        parts.append(f"### Summary of Your Training & Recovery (Past {n_days} Days)\n")
        parts.append(f"**1. Training Consistency & Compliance (Past {n_days} days):**\n{workouts_past_summary}\n")
    else:
        parts.append(f"### Summary of Your Training Calendar (Future Query)\n")
        
    if workouts_future_raw is not None:
        parts.append(f"**2. Planned Workouts:**\n{workouts_future_summary}\n")
        
    if metrics_raw is not None:
        parts.append(f"**3. Recovery & Physiological Metrics (Past {n_days} days):**\n{metrics_summary}\n")
        
    if notes_raw is not None:
        parts.append(f"**4. Calendar Notes:**\n{notes_summary}\n")
        
    if fitness_raw is not None:
        parts.append(f"**5. Fitness PMC Trends (Past {n_days} days):**\n{fitness_summary}\n")
        
    return "\n".join(parts)

async def fetch_runner_status(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """Fetches and summarizes the runner's training, recovery, and fitness status.
    
    Args:
        start_date: Optional start date (YYYY-MM-DD) to query. Must be calculated and passed explicitly if the user is asking about a specific period.
        end_date: Optional end date (YYYY-MM-DD) to query. Must be calculated and passed explicitly if the user is asking about a specific period.
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."
        
    today = datetime.now()
    today_date = today.date()
    
    # Resolve query range
    is_custom_query = bool(start_date or end_date)
    
    if is_custom_query:
        # Parse custom dates (fallback to today if one is missing)
        q_start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else today_date
        q_end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else today_date
        
        # Determine if this is a future-only query
        is_future_only = (q_start > today_date)
    else:
        # Default Check-In Behavior
        last_active_str = profile.get("last_active", "Never")
        if last_active_str == "Never":
            n_days = 7
        else:
            try:
                last_active = datetime.strptime(last_active_str, "%Y-%m-%d")
                n_days = (today - last_active).days
                n_days = max(7, min(30, n_days))
            except:
                n_days = 7
        
        q_start = (today - timedelta(days=n_days)).date()
        q_end = (today + timedelta(days=7)).date()
        is_future_only = False

    # Convert back to strings for API calls
    start_str = q_start.strftime("%Y-%m-%d")
    end_str = q_end.strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")
    
    # Initialize variables
    workouts_past_raw = None
    workouts_future_raw = None
    metrics_raw = None
    fitness_raw = None
    notes_raw = None
    
    tp_get_workouts_tool = await get_tp_tool("tp_get_workouts")
    tp_list_notes_tool = await get_tp_tool("tp_list_notes")
    
    if is_future_only:
        # Bypassing past data
        print(f"DEBUG: Smart Routing - Future-Only Query ({start_str} to {end_str}). Bypassing recovery/past data.")
        
        # Fetch workouts and notes concurrently
        t_fut = tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": start_str, "end_date": end_str})
        t_not = tool_context.run_node(tp_list_notes_tool, node_input={"start_date": start_str, "end_date": end_str})
        workouts_future_raw, notes_raw = await asyncio.gather(t_fut, t_not)
        n_days = 0
    else:
        # Full Fetch (Past + Future or Past-Only)
        print(f"DEBUG: Smart Routing - Full Query ({start_str} to {end_str}). Fetching history and recovery.")
        tp_get_metrics_tool = await get_tp_tool("tp_get_metrics")
        tp_get_fitness_tool = await get_tp_tool("tp_get_fitness")
        
        # Split range at 'today' to separate past and future workouts
        if q_start < today_date and q_end > today_date:
            # Overlapping range: run all 5 queries concurrently
            t_past = tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": start_str, "end_date": today_str})
            t_fut = tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": today_str, "end_date": end_str})
            t_met = tool_context.run_node(tp_get_metrics_tool, node_input={"start_date": start_str, "end_date": today_str})
            t_fit = tool_context.run_node(tp_get_fitness_tool, node_input={"start_date": start_str, "end_date": today_str})
            t_not = tool_context.run_node(tp_list_notes_tool, node_input={"start_date": start_str, "end_date": end_str})
            
            results = await asyncio.gather(t_past, t_fut, t_met, t_fit, t_not)
            workouts_past_raw, workouts_future_raw, metrics_raw, fitness_raw, notes_raw = results
        else:
            # Past-only range: run all 4 queries concurrently
            t_past = tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": start_str, "end_date": end_str})
            t_met = tool_context.run_node(tp_get_metrics_tool, node_input={"start_date": start_str, "end_date": end_str})
            t_fit = tool_context.run_node(tp_get_fitness_tool, node_input={"start_date": start_str, "end_date": end_str})
            t_not = tool_context.run_node(tp_list_notes_tool, node_input={"start_date": start_str, "end_date": end_str})
            
            results = await asyncio.gather(t_past, t_met, t_fit, t_not)
            workouts_past_raw, metrics_raw, fitness_raw, notes_raw = results
            
        n_days = (today_date - q_start).days

    return compile_data_summary(
        n_days,
        workouts_past_raw,
        workouts_future_raw,
        metrics_raw,
        fitness_raw,
        notes_raw
    )

fetch_runner_status_tool = FunctionTool(fetch_runner_status)

async def analyze_workout(tool_context: ToolContext, workout_id: str) -> str:
    """Gets detailed analysis for a specific workout ID, including metrics, zones, and laps.
    
    Args:
        workout_id: The unique TrainingPeaks workout ID.
    """
    try:
        tp_analyze_tool = await get_tp_tool("tp_analyze_workout")
        result = await tool_context.run_node(
            tp_analyze_tool,
            node_input={"workout_id": workout_id}
        )
        data = parse_mcp_response(result)
        if not data:
            return "No analysis data returned."
            
        filtered_data = {
            "workoutId": data.get("workoutId"),
            "startTimestamp": data.get("startTimestamp"),
            "stopTimestamp": data.get("stopTimestamp"),
            "totals": data.get("totals"),
        }
        
        # Filter channels to key physiological metrics
        if "dataChannels" in data:
            filtered_channels = []
            for ch in data["dataChannels"]:
                if ch.get("identifier") in ["HeartRate", "Pace", "Power", "Cadence"]:
                    filtered_channels.append({
                        "identifier": ch.get("identifier"),
                        "name": ch.get("name"),
                        "unit": ch.get("unit"),
                        "min": ch.get("min"),
                        "max": ch.get("max"),
                        "average": ch.get("average"),
                        "zones": ch.get("zones")
                    })
            filtered_data["dataChannels"] = filtered_channels
            
        # Filter laps to strip redundant columns
        if "lapData" in data:
            filtered_laps = []
            for lap in data["lapData"]:
                filtered_laps.append({
                    "id": lap.get("id"),
                    "Name": lap.get("Name"),
                    "TotalElapsedTime": lap.get("TotalElapsedTime"),
                    "TotalDistance": lap.get("TotalDistance"),
                    "AveragePace": lap.get("AveragePace"),
                    "AverageHeartRate": lap.get("AverageHeartRate"),
                    "MaximumHeartRate": lap.get("MaximumHeartRate"),
                    "AverageCadence": lap.get("AverageCadence"),
                    "AveragePower": lap.get("AveragePower"),
                    "NormalizedPower": lap.get("NormalizedPower"),
                    "TSS": lap.get("TSS"),
                    "hrTSS": lap.get("hrTSS"),
                    "PowerPulseDecoupling": lap.get("PowerPulseDecoupling")
                })
            filtered_data["lapData"] = filtered_laps
            
        return json.dumps(filtered_data)
    except Exception as e:
        print(f"Error in analyze_workout tool: {e}")
        return f"Error: Failed to analyze workout {workout_id}: {e}"

analyze_workout_tool = FunctionTool(analyze_workout)

async def save_checkin_report(tool_context: ToolContext, report_content: str) -> str:
    """Saves the generated check-in report to Firestore for historical tracking.
    Call this only after the user explicitly confirms they want to save the report.
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."
        
    firstname = profile.get("firstname")
    lastname = profile.get("lastname")
    if not firstname:
        return "Error: First name not found in profile."
        
    user_id = f"{firstname.lower()}_{lastname.lower()}"
    
    # Calculate ISO week and year
    today = datetime.now()
    iso_year, iso_week, _ = today.isocalendar()
    doc_id = f"{iso_week}-{iso_year}"
    
    try:
        # Write to users/{user_id}/checkins/{doc_id}
        doc_ref = db_client.collection("users").document(user_id).collection("checkins").document(doc_id)
        doc_ref.set({
            "week": iso_week,
            "year": iso_year,
            "created_at": today.isoformat(),
            "report_markdown": report_content
        })
        print(f"DEBUG: Saved check-in report '{doc_id}' to Firestore for {user_id}")
        return f"Success: Your check-in report for Week {iso_week}, {iso_year} has been saved to your history."
    except Exception as e:
        print(f"Error saving check-in report: {e}")
        return f"Error: Failed to save the report to Firestore: {e}"

save_checkin_report_tool = FunctionTool(save_checkin_report)
