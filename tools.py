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

tp_toolset = McpToolset(
    connection_params=StdioServerParameters(
        command=tp_mcp_path,
        args=["serve"],
        env=tp_env
    )
)

async def get_tp_tool(name: str) -> Any:
    """Asynchronously retrieves a specific tool from the TrainingPeaks MCP toolset by name."""
    tools = await tp_toolset.get_tools()
    try:
        return next(t for t in tools if t.name == name)
    except StopIteration:
        raise ValueError(f"Tool '{name}' not found in TrainingPeaks MCP toolset.")

# --- Skills ---
nutrition_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "nutrition-planner"))
checkin_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "check-in-report"))
workout_analysis_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "workout-analysis"))
schedule_audit_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "schedule-audit"))
detailed_report_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "detailed-report"))
skill_toolset = SkillToolset(
    skills=[nutrition_skill, checkin_skill, workout_analysis_skill, schedule_audit_skill, detailed_report_skill],
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
    workouts_past: Optional[list[dict]],
    workouts_future: Optional[list[dict]],
    metrics_data: Optional[dict],
    fitness_data: Optional[dict],
    notes_list: Optional[list[dict]]
) -> str:
    """Compiles a highly compact, token-efficient summary of the runner's data."""
    
    # 1. Summarize past workouts (if available)
    workouts_past_summary = ""
    if workouts_past is not None:
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
                    try:
                        if "T" in time_identifier:
                            dt = datetime.strptime(time_identifier.split(".")[0], "%Y-%m-%dT%H:%M:%S")
                            time_display = dt.strftime("%A, %b %d, %Y at %H:%M:%S")
                        else:
                            dt = datetime.strptime(time_identifier[:10], "%Y-%m-%d")
                            time_display = dt.strftime("%A, %b %d, %Y")
                    except Exception:
                        time_display = time_identifier
                    completed_runs.append(
                        f"- Run [ID: {w_id}] on {time_display}: {dist_km}km (Planned: {planned_km}km) | TSS: {actual_tss} (Planned: {planned_tss})"
                    )
                elif "strength" in sport.lower() or "strength" in w_title:
                    completed_strength += 1
        workouts_past_summary = "\n".join(completed_runs) if completed_runs else "No completed runs."
        workouts_past_summary += f"\n- Completed Strength Sessions: {completed_strength}"

    # 2. Summarize upcoming workouts (if available)
    workouts_future_summary = ""
    if workouts_future is not None:
        upcoming_runs = []
        for w in workouts_future:
            if w.get("sport") == "Run":
                planned_km = w.get("distance_planned_km") or 0.0
                planned_km = round(planned_km, 2)
                planned_tss = w.get("tss_planned") or 0
                w_id = w.get("id", "")
                date_str = w.get("date", "")[:10]
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    date_display = dt.strftime("%A, %b %d, %Y")
                except Exception:
                    date_display = date_str
                upcoming_runs.append(
                    f"- Planned Run [ID: {w_id}] on {date_display}: {planned_km}km | Planned TSS: {planned_tss}"
                )
        workouts_future_summary = "\n".join(upcoming_runs) if upcoming_runs else "No upcoming runs planned."

    # 3. Summarize recovery metrics (if available)
    metrics_summary = ""
    if metrics_data is not None:
        sleep_hours = metrics_data.get("sleep", [])
        hrv_clean = metrics_data.get("hrv", [])
        rhr_clean = metrics_data.get("rhr", [])
        
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
    if notes_list is not None:
        notes_summary_list = []
        for n in notes_list:
            n_date = n.get("date")
            try:
                dt = datetime.strptime(n_date[:10], "%Y-%m-%d")
                date_display = dt.strftime("%A, %b %d, %Y")
            except Exception:
                date_display = n_date
            n_title = n.get("title") or "Note"
            n_desc = n.get("description") or ""
            notes_summary_list.append(f"- {date_display}: {n_title} | {n_desc}")
        notes_summary = "\n".join(notes_summary_list) if notes_summary_list else "No calendar notes."

    # 4. Summarize fitness PMC trends (if available)
    fitness_summary = ""
    if fitness_data is not None:
        ctl_start = round(fitness_data.get("ctl_start", 0), 1)
        ctl_end = round(fitness_data.get("ctl_end", 0), 1)
        atl_start = round(fitness_data.get("atl_start", 0), 1)
        atl_end = round(fitness_data.get("atl_end", 0), 1)
        tsb_start = round(fitness_data.get("tsb_start", 0), 1)
        tsb_end = round(fitness_data.get("tsb_end", 0), 1)
        fitness_summary = (
            f"- CTL (Fitness): Started at {ctl_start} -> Ended at {ctl_end}\n"
            f"- ATL (Fatigue): Started at {atl_start} -> Ended at {atl_end}\n"
            f"- TSB (Form/Readiness): Started at {tsb_start} -> Ended at {tsb_end}"
        )

    # Build the final output dynamically
    parts = []
    if workouts_past is not None:
        parts.append(f"### Summary of Your Training & Recovery\n")
        parts.append(f"**1. Completed Workouts & Training Compliance:**\n{workouts_past_summary}\n")
    else:
        parts.append(f"### Summary of Your Training Calendar (Future Query)\n")
        
    if workouts_future is not None:
        parts.append(f"**2. Planned Workouts:**\n{workouts_future_summary}\n")
        
    if metrics_data is not None:
        parts.append(f"**3. Recovery & Physiological Metrics (Past {n_days} days):**\n{metrics_summary}\n")
        
    if notes_list is not None:
        parts.append(f"**4. Calendar Notes:**\n{notes_summary}\n")
        
    if fitness_data is not None:
        parts.append(f"**5. Fitness PMC Trends (Past {n_days} days):**\n{fitness_summary}\n")
        
    return "\n".join(parts)

async def fetch_runner_status(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """Fetches and summarizes the runner's training, recovery, and fitness status.
    
    Args:
        start_date: Optional start date (YYYY-MM-DD) to query. If omitted, defaults to 
                    fetching recent history based on last active date.
        end_date: Optional end date (YYYY-MM-DD) to query. If omitted, defaults to 
                  fetching the upcoming 7 days of planned workouts.
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
        q_start = datetime.strptime(start_date[:10], "%Y-%m-%d").date() if start_date else today_date
        q_end = datetime.strptime(end_date[:10], "%Y-%m-%d").date() if end_date else today_date
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

    start_str = q_start.strftime("%Y-%m-%d")
    end_str = q_end.strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    # Get required tools
    tools = await tp_toolset.get_tools()
    tp_get_workouts_tool = next(t for t in tools if t.name == "tp_get_workouts")
    tp_list_notes_tool = next(t for t in tools if t.name == "tp_list_notes")

    # Create concurrent tasks for workouts and notes across the full range
    tasks = [
        tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": start_str, "end_date": end_str}),
        tool_context.run_node(tp_list_notes_tool, node_input={"start_date": start_str, "end_date": end_str})
    ]

    # Fetch metrics and fitness only if the query starts in the past or today
    has_past = (q_start <= today_date)
    if has_past:
        tp_get_metrics_tool = next(t for t in tools if t.name == "tp_get_metrics")
        tp_get_fitness_tool = next(t for t in tools if t.name == "tp_get_fitness")
        
        # Query metrics up to today (or end_date if the query is past-only)
        recovery_end_str = min(q_end, today_date).strftime("%Y-%m-%d")
        
        tasks.append(tool_context.run_node(tp_get_metrics_tool, node_input={"start_date": start_str, "end_date": recovery_end_str}))
        tasks.append(tool_context.run_node(tp_get_fitness_tool, node_input={"start_date": start_str, "end_date": recovery_end_str}))

    # Await all results
    results = await asyncio.gather(*tasks)
    workouts_raw = results[0]
    notes_raw = results[1]
    metrics_raw = results[2] if len(results) > 2 else None
    fitness_raw = results[3] if len(results) > 3 else None

    # Parse and partition workouts locally based on today's date
    workouts_past = None
    workouts_future = None
    if workouts_raw:
        workouts_data = parse_mcp_response(workouts_raw) or {}
        workouts_list = workouts_data.get("workouts", [])
        
        past_list = []
        future_list = []
        for w in workouts_list:
            w_date = datetime.strptime(w.get("date", "")[:10], "%Y-%m-%d").date()
            is_completed = (
                bool(w.get("completed"))
                or (w.get("distance_actual_km") is not None and w.get("distance_actual_km") > 0)
                or (w.get("tss_actual") is not None and w.get("tss_actual") > 0)
                or (w.get("duration_actual_min") is not None and w.get("duration_actual_min") > 0)
                or (w.get("duration_actual") is not None and w.get("duration_actual") > 0)
            )
            if w_date < today_date or (w_date == today_date and is_completed):
                past_list.append(w)
            else:
                future_list.append(w)
                
        if past_list or has_past:
            workouts_past = past_list
        if future_list:
            workouts_future = future_list

    # Parse recovery metrics
    metrics_data = None
    if metrics_raw:
        metrics_data = extract_health_metrics(metrics_raw)

    # Parse calendar notes
    notes_list = None
    if notes_raw:
        notes_parsed = parse_mcp_response(notes_raw) or {}
        notes_list = notes_parsed.get("notes", [])

    # Parse fitness performance metrics
    fitness_data = None
    if fitness_raw:
        fit_parsed = parse_mcp_response(fitness_raw) or {}
        fitness_list = fit_parsed.get("daily_data", [])
        ctl_start, ctl_end = 0.0, 0.0
        atl_start, atl_end = 0.0, 0.0
        tsb_start, tsb_end = 0.0, 0.0
        if isinstance(fitness_list, list) and len(fitness_list) > 0:
            try:
                fitness_sorted = sorted(fitness_list, key=lambda x: x.get("date", ""))
                start_entry = fitness_sorted[0]
                end_entry = fitness_sorted[-1]
                ctl_start = start_entry.get("ctl", 0.0)
                ctl_end = end_entry.get("ctl", 0.0)
                atl_start = start_entry.get("atl", 0.0)
                atl_end = end_entry.get("atl", 0.0)
                tsb_start = start_entry.get("tsb", 0.0)
                tsb_end = end_entry.get("tsb", 0.0)
            except Exception as e:
                print(f"Error parsing fitness trend: {e}")
        fitness_data = {
            "ctl_start": ctl_start, "ctl_end": ctl_end,
            "atl_start": atl_start, "atl_end": atl_end,
            "tsb_start": tsb_start, "tsb_end": tsb_end
        }

    n_days = (today_date - q_start).days if has_past else 0

    return compile_data_summary(
        n_days,
        workouts_past,
        workouts_future,
        metrics_data,
        fitness_data,
        notes_list
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
        return json.dumps(data) if data else "No analysis data returned."
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
