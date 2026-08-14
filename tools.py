from datetime import datetime, timedelta
import asyncio
import os
import json
from typing import Optional, Any

from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.skills import load_skill_from_dir
from google.adk.code_executors import UnsafeLocalCodeExecutor

# Import modular services, analytics, utilities, and formatters
from .utils.date_helpers import get_today_date, parse_date, format_display_date
from .services.firestore import db_client, get_user_id
from .services.weather import geocode_location, get_weather_for_dates
from .services.tp_mcp import get_tp_tool
from .analytics.metrics import parse_mcp_response, extract_health_metrics
from .analytics.workouts import (
    is_workout_completed,
    partition_workouts_by_date,
    format_workout_analysis,
)
from .analytics.trajectory import evaluate_goal_trajectory
from .formatters.status_summary import (
    format_recovery_metrics,
    compile_checkin_summary,
    format_schedule_audit_summary,
    format_nutrition_context_summary,
)

# ==============================================================================
# 1. Skills Toolset Configuration
# ==============================================================================
current_dir = os.path.dirname(os.path.abspath(__file__))
nutrition_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "nutrition-planner"))
checkin_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "check-in-report"))
workout_analysis_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "workout-analysis"))
bike_workout_analysis_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "bike-workout-analysis"))
schedule_audit_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "schedule-audit"))
workout_creator_skill = load_skill_from_dir(os.path.join(current_dir, "skills", "workout-creator"))

class CompactSkillToolset(SkillToolset):
    """Custom SkillToolset that suppresses ListSkillsTool so that the skills XML
    catalog is directly pre-injected into the system prompt, enabling single-turn skill loading.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tools = [t for t in self._tools if t.name != "list_skills"]

skill_toolset = CompactSkillToolset(
    skills=[
        nutrition_skill,
        checkin_skill,
        workout_analysis_skill,
        bike_workout_analysis_skill,
        schedule_audit_skill,
        workout_creator_skill,
    ],
    code_executor=UnsafeLocalCodeExecutor(),
)

# ==============================================================================
# 2. Skill Facades (1 Facade per Skill)
# ==============================================================================

# Workout & Bike Analysis (for workout-analysis & bike-workout-analysis skills) ---
async def analyze_workout(
    tool_context: ToolContext,
    workout_id: Optional[str] = None,
    date_str: Optional[str] = None,
    include_weather: bool = True,
    include_recovery: bool = True,
) -> str:
    """Gets comprehensive physiological, telemetry, recovery, and environmental analysis for a workout.

    Args:
        workout_id: Specific workout ID to analyze. If omitted, automatically finds the completed workout for date_str.
        date_str: Target date in ISO format (YYYY-MM-DD or 'today'). Defaults to today if workout_id is not provided.
        include_weather: Whether to automatically fetch and correlate hourly weather for the workout start time. Defaults to True.
        include_recovery: Whether to include the runner's morning recovery metrics (HRV, Sleep, RHR). Defaults to True.
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()
    
    target_date = today_date
    if date_str and date_str.strip().lower() != "today":
        parsed = parse_date(date_str)
        if parsed:
            target_date = parsed

    target_iso = target_date.strftime("%Y-%m-%d")
    workout_start_time = None
    workout_sport = "Workout"
    workout_title = ""

    # 1. Resolve workout_id if not provided
    if not workout_id:
        try:
            tp_get_workouts_tool = await get_tp_tool("tp_get_workouts")
            raw_workouts = await tool_context.run_node(
                tp_get_workouts_tool,
                node_input={"start_date": target_iso, "end_date": target_iso}
            )
            parsed_wp = parse_mcp_response(raw_workouts) or {}
            workouts_list = parsed_wp.get("workouts", [])
            completed_runs = [w for w in workouts_list if is_workout_completed(w)]
            if not completed_runs:
                if workouts_list:
                    titles = ", ".join(f"'{w.get('title') or w.get('sport', 'Workout')}'" for w in workouts_list)
                    return f"No completed workout found for {target_iso}. Planned sessions found on calendar: {titles}."
                return f"No completed workouts found on {target_iso}."

            target_workout = completed_runs[-1]
            workout_id = str(target_workout.get("id") or target_workout.get("workoutId") or "")
            workout_sport = target_workout.get("sport", "Workout")
            workout_title = target_workout.get("title") or workout_sport
            workout_start_time = target_workout.get("start_time") or target_workout.get("startTime") or target_workout.get("date")
        except Exception as e:
            print(f"Error looking up workout for {target_iso}: {e}")
            return f"Error: Failed to find workout for {target_iso}: {e}"

    if not workout_id:
        return "Error: No workout ID could be determined."

    # 2. Fetch workout analysis and recovery metrics concurrently
    try:
        tp_analyze_tool = await get_tp_tool("tp_analyze_workout")
        tasks = [
            tool_context.run_node(tp_analyze_tool, node_input={"workout_id": workout_id})
        ]

        fetch_metrics_task_idx = None
        if include_recovery:
            tp_get_metrics_tool = await get_tp_tool("tp_get_metrics")
            metrics_start = (target_date - timedelta(days=7)).strftime("%Y-%m-%d")
            fetch_metrics_task_idx = len(tasks)
            tasks.append(
                tool_context.run_node(
                    tp_get_metrics_tool,
                    node_input={"start_date": metrics_start, "end_date": target_iso}
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        analyze_res = results[0]
        if isinstance(analyze_res, Exception):
            return f"Error analyzing workout {workout_id}: {analyze_res}"

        data = parse_mcp_response(analyze_res)
        if not data or not isinstance(data, dict):
            return f"No analysis data returned for workout {workout_id}."

        analysis_str = format_workout_analysis(data)

        if not workout_start_time:
            workout_start_time = data.get("startTime") or data.get("workoutDay") or target_iso

        # 3. Attach Environmental Weather
        weather_section = ""
        if include_weather:
            loc = profile.get("location", "")
            lat = profile.get("latitude")
            lon = profile.get("longitude")
            if workout_start_time and (loc or (lat is not None and lon is not None)):
                try:
                    weather_res = await asyncio.to_thread(
                        get_weather_for_dates,
                        location=loc or "",
                        dates=[str(workout_start_time)],
                        lat=lat,
                        lon=lon
                    )
                    if weather_res and not weather_res.startswith("Error") and not weather_res.startswith("Could not geocode"):
                        weather_section = f"\n\n**Environmental & Weather Context:**\n{weather_res}"
                except Exception as e:
                    print(f"Error fetching weather in analyze_workout: {e}")

        # 4. Attach Recovery Context
        recovery_section = ""
        if fetch_metrics_task_idx is not None:
            metrics_res = results[fetch_metrics_task_idx]
            if not isinstance(metrics_res, Exception) and metrics_res:
                metrics_data = extract_health_metrics(metrics_res)
                if metrics_data:
                    rec_formatted = format_recovery_metrics(metrics_data)
                    if rec_formatted:
                        recovery_section = f"\n\n**Morning Physiological Recovery Context:**\n{rec_formatted}"

        return f"{analysis_str}{recovery_section}{weather_section}"
    except Exception as e:
        print(f"Error in analyze_workout tool: {e}")
        return f"Error: Failed to analyze workout {workout_id}: {e}"

analyze_workout_tool = FunctionTool(analyze_workout)


# Check-In Report (for check-in-report skill) ---
async def fetch_checkin_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> str:
    """Fetches all data needed for a comprehensive weekly check-in report.
    
    Includes:
    - 14-day past completed workouts with run-time weather
    - 7-day future scheduled workouts
    - 14-day recovery metrics (Sleep, HRV, RHR)
    - 14-day PMC fitness trends (CTL, ATL, TSB, visual table, goal trajectory)
    - Calendar notes (work stress, travel, illness)
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."

    today_date = get_today_date()
    q_start = parse_date(start_date) or (today_date - timedelta(days=14))
    q_end = parse_date(end_date) or (today_date + timedelta(days=7))

    start_str = q_start.strftime("%Y-%m-%d")
    end_str = q_end.strftime("%Y-%m-%d")
    recovery_end_str = min(q_end, today_date).strftime("%Y-%m-%d")

    tp_get_workouts_tool = await get_tp_tool("tp_get_workouts")
    tp_list_notes_tool = await get_tp_tool("tp_list_notes")
    tp_get_metrics_tool = await get_tp_tool("tp_get_metrics")
    tp_get_fitness_tool = await get_tp_tool("tp_get_fitness")

    results = await asyncio.gather(
        tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": start_str, "end_date": end_str}),
        tool_context.run_node(tp_list_notes_tool, node_input={"start_date": start_str, "end_date": end_str}),
        tool_context.run_node(tp_get_metrics_tool, node_input={"start_date": start_str, "end_date": recovery_end_str}),
        tool_context.run_node(tp_get_fitness_tool, node_input={"start_date": start_str, "end_date": recovery_end_str}),
        return_exceptions=True
    )

    workouts_raw = results[0] if not isinstance(results[0], Exception) else None
    notes_raw = results[1] if not isinstance(results[1], Exception) else None
    metrics_raw = results[2] if not isinstance(results[2], Exception) else None
    fitness_raw = results[3] if not isinstance(results[3], Exception) else None

    # Partition workouts
    workouts_data = parse_mcp_response(workouts_raw) or {} if workouts_raw else {}
    workouts_list = workouts_data.get("workouts", [])
    workouts_past, workouts_future = partition_workouts_by_date(workouts_list, today_date, has_past=True)

    # Parse recovery & notes
    metrics_data = extract_health_metrics(metrics_raw) if metrics_raw else None
    notes_parsed = parse_mcp_response(notes_raw) or {} if notes_raw else {}
    notes_list = notes_parsed.get("notes", []) if notes_raw else None

    # Parse fitness PMC
    fitness_data = None
    if fitness_raw:
        fit_parsed = parse_mcp_response(fitness_raw) or {}
        fitness_list = fit_parsed.get("daily_data", [])
        ctl_start, ctl_end = 0.0, 0.0
        atl_start, atl_end = 0.0, 0.0
        tsb_start, tsb_end = 0.0, 0.0
        if isinstance(fitness_list, list) and fitness_list:
            fitness_sorted = sorted(fitness_list, key=lambda x: str(x.get("date", "")))
            ctl_start = fitness_sorted[0].get("ctl", 0.0)
            ctl_end = fitness_sorted[-1].get("ctl", 0.0)
            atl_start = fitness_sorted[0].get("atl", 0.0)
            atl_end = fitness_sorted[-1].get("atl", 0.0)
            tsb_start = fitness_sorted[0].get("tsb", 0.0)
            tsb_end = fitness_sorted[-1].get("tsb", 0.0)

        trajectory_info = evaluate_goal_trajectory(profile, ctl_end, today_date)
        fitness_data = {
            "ctl_start": ctl_start, "ctl_end": ctl_end,
            "atl_start": atl_start, "atl_end": atl_end,
            "tsb_start": tsb_start, "tsb_end": tsb_end,
            "daily_list": fitness_list if isinstance(fitness_list, list) else [],
            "trajectory_info": trajectory_info,
        }

    # Fetch weather for completed runs
    weather_map = {}
    loc = profile.get("location", "")
    lat = profile.get("latitude")
    lon = profile.get("longitude")
    if workouts_past and (loc or (lat is not None and lon is not None)):
        run_timestamps = [str(w.get("start_time") or w.get("date")) for w in workouts_past if (w.get("start_time") or w.get("date"))]
        if run_timestamps:
            try:
                wx_res = await asyncio.to_thread(
                    get_weather_for_dates,
                    location=loc or "",
                    dates=run_timestamps,
                    lat=lat,
                    lon=lon
                )
                if wx_res and not wx_res.startswith("Error"):
                    for ts in run_timestamps:
                        d_key = ts[:10]
                        weather_map[ts] = f"Recorded conditions on {d_key}"
            except Exception as e:
                print(f"Error fetching checkin weather: {e}")

    lookback_days = (today_date - q_start).days
    lookahead_days = (q_end - today_date).days

    return compile_checkin_summary(
        lookback_days=lookback_days,
        lookahead_days=lookahead_days,
        workouts_past=workouts_past,
        workouts_future=workouts_future,
        metrics_data=metrics_data,
        fitness_data=fitness_data,
        notes_list=notes_list,
        weather_map=weather_map
    )

fetch_checkin_data_tool = FunctionTool(fetch_checkin_data)


# Schedule Audit (for schedule-audit skill) ---
async def fetch_schedule_audit_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weeks_forward: int = 4,
) -> str:
    """Audits the runner's training schedule to calculate weekly volume, planned TSS,
    workout intensity distribution (easy vs. hard), travel alignment, and risk flags.
    """
    today_date = get_today_date()
    q_start = parse_date(start_date) or today_date
    q_end = parse_date(end_date) or (today_date + timedelta(weeks=weeks_forward))

    start_str = q_start.strftime("%Y-%m-%d")
    end_str = q_end.strftime("%Y-%m-%d")

    tp_get_workouts_tool = await get_tp_tool("tp_get_workouts")
    tp_list_notes_tool = await get_tp_tool("tp_list_notes")

    results = await asyncio.gather(
        tool_context.run_node(tp_get_workouts_tool, node_input={"start_date": start_str, "end_date": end_str}),
        tool_context.run_node(tp_list_notes_tool, node_input={"start_date": start_str, "end_date": end_str}),
    )

    workouts_raw, notes_raw = results
    workouts_data = parse_mcp_response(workouts_raw) or {} if workouts_raw else {}
    workouts_list = workouts_data.get("workouts", [])

    notes_parsed = parse_mcp_response(notes_raw) or {} if notes_raw else {}
    notes_list = notes_parsed.get("notes", []) if notes_raw else []

    # Group workouts and notes into weekly buckets
    weeks_dict = {}
    cur = q_start
    while cur <= q_end:
        iso_year, iso_week, _ = cur.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        if week_key not in weeks_dict:
            w_start = cur - timedelta(days=cur.weekday())
            w_end = w_start + timedelta(days=6)
            weeks_dict[week_key] = {
                "date_range": f"{w_start.strftime('%b %d')} - {w_end.strftime('%b %d, %Y')}",
                "start_date": w_start,
                "end_date": w_end,
                "total_distance_km": 0.0,
                "total_tss": 0.0,
                "easy_count": 0,
                "quality_count": 0,
                "sessions": [],
                "travel_note": None,
            }
        cur += timedelta(days=7)

    # Populate workouts
    for w in workouts_list:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date:
            continue
        iso_year, iso_week, _ = w_date.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        if week_key in weeks_dict:
            bucket = weeks_dict[week_key]
            dist = w.get("distance_planned_km") or w.get("distance_km") or w.get("distance_actual_km") or 0.0
            tss = w.get("tss_planned") or w.get("tss") or w.get("tss_actual") or 0.0
            bucket["total_distance_km"] += float(dist)
            bucket["total_tss"] += float(tss)

            sport = w.get("sport", "Run")
            title = w.get("title") or sport
            title_lower = title.lower()

            is_quality = any(kw in title_lower for kw in ["interval", "tempo", "threshold", "race", "speed", "reps", "mp", "push"])
            if is_quality:
                bucket["quality_count"] += 1
            else:
                bucket["easy_count"] += 1

            bucket["sessions"].append(f"[{sport}] '{title}' on {format_display_date(w_date)} ({round(dist, 1)}km, TSS: {round(tss, 0)})")

    # Match travel / calendar notes to weeks
    for n in notes_list:
        n_date = parse_date(n.get("date"))
        if not n_date:
            continue
        iso_year, iso_week, _ = n_date.isocalendar()
        week_key = f"{iso_year}-W{iso_week:02d}"
        if week_key in weeks_dict:
            n_title = n.get("title", "")
            n_desc = n.get("description", "")
            full_note = f"{n_title}: {n_desc}" if n_desc else n_title
            weeks_dict[week_key]["travel_note"] = full_note

    # Risk evaluation
    risk_flags = []
    weeks_list = list(weeks_dict.values())
    for idx, w in enumerate(weeks_list):
        if w["quality_count"] >= 3:
            risk_flags.append(f"High Intensity Risk in {w['date_range']}: {w['quality_count']} quality sessions scheduled (recommended: max 1-2).")
        if idx > 0:
            prev_vol = weeks_list[idx - 1]["total_distance_km"]
            cur_vol = w["total_distance_km"]
            if prev_vol > 10 and cur_vol > prev_vol * 1.25:
                growth_pct = round(((cur_vol - prev_vol) / prev_vol) * 100)
                risk_flags.append(f"Volume Spike Warning in {w['date_range']}: +{growth_pct}% mileage increase vs previous week.")

    return format_schedule_audit_summary(
        weeks_data=weeks_list,
        overall_notes=notes_list,
        risk_flags=risk_flags
    )

fetch_schedule_audit_data_tool = FunctionTool(fetch_schedule_audit_data)


# Nutrition & Fueling Context (for nutrition-planner skill) ---
async def fetch_nutrition_context(
    tool_context: ToolContext,
    days_forward: int = 3,
) -> str:
    """Fetches runner biometrics, upcoming training demands (next 3 days),
    and forecasted climate to provide customized sports nutrition and hydration guidance.
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()
    end_date = today_date + timedelta(days=days_forward)

    start_str = today_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    tp_get_workouts_tool = await get_tp_tool("tp_get_workouts")
    raw_workouts = await tool_context.run_node(
        tp_get_workouts_tool,
        node_input={"start_date": start_str, "end_date": end_str}
    )
    parsed = parse_mcp_response(raw_workouts) or {}
    upcoming = parsed.get("workouts", [])

    # Fetch weather forecast for upcoming window
    loc = profile.get("location", "")
    lat = profile.get("latitude")
    lon = profile.get("longitude")
    forecast_dates = [(today_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_forward + 1)]
    weather_str = ""
    if loc or (lat is not None and lon is not None):
        try:
            weather_str = await asyncio.to_thread(
                get_weather_for_dates,
                location=loc or "",
                dates=forecast_dates,
                lat=lat,
                lon=lon
            )
        except Exception as e:
            print(f"Error fetching weather forecast for nutrition: {e}")

    return format_nutrition_context_summary(
        profile=profile,
        upcoming_workouts=upcoming,
        weather_forecast=weather_str
    )

fetch_nutrition_context_tool = FunctionTool(fetch_nutrition_context)


# Workout & Calendar Note Creation (for workout-creator skill) ---
async def create_workout(
    tool_context: ToolContext,
    date_str: str,
    sport: str = "Run",
    title: str = "Planned Run",
    duration_minutes: Optional[int] = None,
    distance_km: Optional[float] = None,
    tss_planned: Optional[float] = None,
    description: Optional[str] = None,
    structure: Optional[Any] = None,
) -> str:
    """Creates a planned workout in TrainingPeaks."""
    try:
        tp_tool = await get_tp_tool("tp_create_workout")
        node_input: dict[str, Any] = {
            "date_str": date_str,
            "sport": sport,
            "title": title,
        }
        if duration_minutes is not None:
            node_input["duration_minutes"] = int(duration_minutes)
        if distance_km is not None:
            node_input["distance_km"] = float(distance_km)
        if tss_planned is not None:
            node_input["tss_planned"] = float(tss_planned)
        if description is not None:
            node_input["description"] = description
        if structure is not None:
            node_input["structure"] = structure

        result = await tool_context.run_node(tp_tool, node_input=node_input)
        data = parse_mcp_response(result)
        if data is None:
            if isinstance(result, dict):
                data = result
            elif isinstance(result, str):
                try:
                    data = json.loads(result)
                except Exception:
                    data = {"message": result}

        if isinstance(data, dict):
            if data.get("isError"):
                return f"Error creating workout: {data.get('message', 'Unknown error')}"
            return json.dumps(data)
        return "Success: Workout created."
    except Exception as e:
        print(f"Error in create_workout tool: {e}")
        return f"Error: Failed to create workout: {e}"

create_workout_tool = FunctionTool(create_workout)


async def create_note(
    tool_context: ToolContext,
    date: str,
    title: str,
    description: Optional[str] = None,
) -> str:
    """Creates a calendar note in TrainingPeaks."""
    try:
        tp_tool = await get_tp_tool("tp_create_note")
        node_input: dict[str, Any] = {
            "date": date,
            "title": title,
        }
        if description is not None:
            node_input["description"] = description

        result = await tool_context.run_node(tp_tool, node_input=node_input)
        data = parse_mcp_response(result)
        if data is None:
            if isinstance(result, dict):
                data = result
            elif isinstance(result, str):
                try:
                    data = json.loads(result)
                except Exception:
                    data = {"message": result}

        if isinstance(data, dict):
            if data.get("isError"):
                return f"Error creating note: {data.get('message', 'Unknown error')}"
            return json.dumps(data)
        return "Success: Calendar note created."
    except Exception as e:
        print(f"Error in create_note tool: {e}")
        return f"Error: Failed to create calendar note: {e}"

create_note_tool = FunctionTool(create_note)


# ==============================================================================
# 3. Action Tools (History Persistence, Goal Re-onboarding, General Weather)
# ==============================================================================
async def save_checkin_report(tool_context: ToolContext, report_content: str) -> str:
    """Saves the generated check-in report to Firestore for historical tracking."""
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."
        
    user_id = get_user_id(profile.get("firstname"), profile.get("lastname"))
    if not user_id or user_id == "_":
        return "Error: Name not found in profile."
        
    today = datetime.now()
    iso_year, iso_week, _ = today.isocalendar()
    doc_id = f"{iso_week}-{iso_year}"
    
    try:
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


async def request_new_goal(tool_context: ToolContext) -> str:
    """Signals that the runner wants to set up a new training goal and trigger re-onboarding."""
    tool_context.state["reonboard_requested"] = True
    return "Re-onboarding initiated. Transitioning to onboarding agent to set up your new goal."

request_new_goal_tool = FunctionTool(request_new_goal)

get_weather_tool = FunctionTool(get_weather_for_dates)

# ==============================================================================
# 4. Public Tool & Module Exports
# ==============================================================================
__all__ = [
    "skill_toolset",
    "CompactSkillToolset",
    "analyze_workout_tool",
    "fetch_checkin_data_tool",
    "fetch_schedule_audit_data_tool",
    "fetch_nutrition_context_tool",
    "create_workout_tool",
    "create_note_tool",
    "save_checkin_report_tool",
    "request_new_goal_tool",
    "get_weather_tool",
    # Internal service exports for backward-compatible imports in steps.py / tests
    "db_client",
    "get_user_id",
    "get_tp_tool",
    "geocode_location",
    "parse_mcp_response",
    "extract_health_metrics",
]

