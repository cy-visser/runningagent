from typing import Optional
from ..utils.date_helpers import format_display_date, parse_date
from ..analytics.visualization import generate_visual_progress_table

def format_completed_workouts(workouts_past: Optional[list[dict]]) -> str:
    """Formats past completed workouts across all sports compactly."""
    if workouts_past is None:
        return ""
    completed_items = []
    for w in workouts_past:
        sport = w.get("sport", "Workout")
        w_id = w.get("id", "")
        w_title = w.get("title") or sport
        time_identifier = w.get("start_time") or w.get("date", "")
        time_display = format_display_date(time_identifier)
        dist_km = round(w.get("distance_actual_km") or 0.0, 1)
        dur_hrs = w.get("duration_actual") or w.get("duration_actual_min")
        dur_str = f" | Dur: {round(dur_hrs, 2)}h" if dur_hrs and isinstance(dur_hrs, (int, float)) else ""
        dist_str = f": {dist_km}km" if dist_km > 0 else ""
        actual_tss = w.get("tss_actual") or w.get("tss") or 0
        completed_items.append(
            f"- [{sport}] '{w_title}' [{w_id}] on {time_display}{dist_str}{dur_str} | TSS: {actual_tss}"
        )
    return "\n".join(completed_items) if completed_items else "No completed sessions found."

def format_planned_workouts(workouts_future: Optional[list[dict]]) -> str:
    """Formats upcoming scheduled workouts across all sports compactly."""
    if workouts_future is None:
        return ""
    upcoming_items = []
    for w in workouts_future:
        sport = w.get("sport", "Workout")
        w_id = w.get("id", "")
        w_title = w.get("title") or sport
        planned_km = round(w.get("distance_planned_km") or 0.0, 1)
        planned_tss = w.get("tss_planned") or 0
        date_str = str(w.get("date", ""))[:10]
        date_display = format_display_date(date_str)
        dist_str = f": {planned_km}km" if planned_km > 0 else ""
        upcoming_items.append(
            f"- [{sport}] '{w_title}' [{w_id}] on {date_display}{dist_str} | Planned TSS: {planned_tss}"
        )
    return "\n".join(upcoming_items) if upcoming_items else "No upcoming workouts planned."

def format_recovery_metrics(metrics_data: Optional[dict]) -> str:
    """Formats sleep averages, HRV trends, and resting pulse compactly."""
    if metrics_data is None:
        return ""
    sleep_hours = metrics_data.get("sleep", [])
    hrv_clean = metrics_data.get("hrv", [])
    rhr_clean = metrics_data.get("rhr", [])
    
    sleep_avg = round(sum(sleep_hours) / len(sleep_hours), 2) if sleep_hours else "N/A"
    hrv_trend = ", ".join(str(h) for h in hrv_clean[-5:]) if hrv_clean else "N/A"
    hrv_latest = hrv_clean[-1] if hrv_clean else "N/A"
    rhr_trend = ", ".join(str(r) for r in rhr_clean[-5:]) if rhr_clean else "N/A"
    rhr_latest = rhr_clean[-1] if rhr_clean else "N/A"
    
    return (
        f"- Sleep: Avg {sleep_avg} hrs/night\n"
        f"- HRV Trend: [{hrv_trend}] (Latest: {hrv_latest} ms)\n"
        f"- RHR Trend: [{rhr_trend}] (Latest: {rhr_latest} bpm)"
    )

def format_calendar_notes(notes_list: Optional[list[dict]]) -> str:
    """Formats runner calendar notes and context compactly."""
    if notes_list is None:
        return ""
    notes_summary_list = []
    for n in notes_list:
        n_date = str(n.get("date", ""))[:10]
        date_display = format_display_date(n_date)
        n_title = n.get("title") or "Note"
        n_desc = n.get("description") or ""
        desc_str = f" | {n_desc}" if n_desc else ""
        notes_summary_list.append(f"- {date_display}: {n_title}{desc_str}")
    return "\n".join(notes_summary_list) if notes_summary_list else "No calendar notes."

def format_fitness_pmc(fitness_data: Optional[dict]) -> str:
    """Formats the PMC metrics progress table and goal trajectory status."""
    if fitness_data is None:
        return ""
        
    ctl_end = round(fitness_data.get("ctl_end", 0.0), 1)
    trajectory_info = fitness_data.get("trajectory_info", {})
    
    progress_table = generate_visual_progress_table(fitness_data, trajectory_info)
    
    weeks_rem = f", {trajectory_info.get('weeks_remaining')}w out" if trajectory_info.get("weeks_remaining") is not None else ""
    status_header = f"**Fitness Status:** {trajectory_info.get('status_label', 'On Track')} (CTL: {ctl_end}, Target: {trajectory_info.get('target_peak_ctl')}{weeks_rem})"
    
    return f"{progress_table}\n\n{status_header}"

def format_completed_workouts_with_weather(
    workouts_past: Optional[list[dict]], 
    weather_map: Optional[dict[str, str]] = None
) -> str:
    """Formats past completed workouts across all sports with embedded run-time weather."""
    if workouts_past is None:
        return ""
    completed_items = []
    weather_map = weather_map or {}
    for w in workouts_past:
        sport = w.get("sport", "Workout")
        w_id = w.get("id", "")
        w_title = w.get("title") or sport
        time_identifier = w.get("start_time") or w.get("date", "")
        time_display = format_display_date(time_identifier)
        dist_km = round(w.get("distance_actual_km") or 0.0, 1)
        dur_hrs = w.get("duration_actual") or w.get("duration_actual_min")
        dur_str = f" | Dur: {round(dur_hrs, 2)}h" if dur_hrs and isinstance(dur_hrs, (int, float)) else ""
        dist_str = f": {dist_km}km" if dist_km > 0 else ""
        actual_tss = w.get("tss_actual") or w.get("tss") or 0
        
        # Check for weather match
        date_key = str(time_identifier)[:10]
        wx_snippet = weather_map.get(str(time_identifier)) or weather_map.get(date_key)
        wx_str = f" [Weather: {wx_snippet}]" if wx_snippet else ""
        
        completed_items.append(
            f"- [{sport}] '{w_title}' [{w_id}] on {time_display}{dist_str}{dur_str} | TSS: {actual_tss}{wx_str}"
        )
    return "\n".join(completed_items) if completed_items else "No completed sessions found."

def compile_data_summary(
    n_days: int,
    workouts_past: Optional[list[dict]],
    workouts_future: Optional[list[dict]],
    metrics_data: Optional[dict],
    fitness_data: Optional[dict],
    notes_list: Optional[list[dict]]
) -> str:
    """Compiles a summary of the runner's data (backward compatible wrapper)."""
    return compile_checkin_summary(
        lookback_days=n_days,
        lookahead_days=7,
        workouts_past=workouts_past,
        workouts_future=workouts_future,
        metrics_data=metrics_data,
        fitness_data=fitness_data,
        notes_list=notes_list
    )

def compile_checkin_summary(
    lookback_days: int,
    lookahead_days: int,
    workouts_past: Optional[list[dict]],
    workouts_future: Optional[list[dict]],
    metrics_data: Optional[dict],
    fitness_data: Optional[dict],
    notes_list: Optional[list[dict]],
    weather_map: Optional[dict[str, str]] = None
) -> str:
    """Compiles a complete, unified Check-In Summary payload for the check-in-report skill."""
    parts = ["### Weekly Check-In Training & Physiological Report\n"]

    if fitness_data is not None:
        parts.append(f"**1. Fitness PMC Trends & Goal Trajectory (Past {lookback_days} days):**\n{format_fitness_pmc(fitness_data)}\n")

    if metrics_data is not None:
        parts.append(f"**2. Autonomic & Physiological Recovery Trends (Past {lookback_days} days):**\n{format_recovery_metrics(metrics_data)}\n")

    if workouts_past is not None:
        parts.append(f"**3. Completed Workouts & Environmental Context (Past {lookback_days} days):**\n{format_completed_workouts_with_weather(workouts_past, weather_map)}\n")

    if notes_list is not None:
        parts.append(f"**4. Calendar & Travel Notes:**\n{format_calendar_notes(notes_list)}\n")

    if workouts_future is not None:
        parts.append(f"**5. Upcoming Scheduled Workouts (Next {lookahead_days} days):**\n{format_planned_workouts(workouts_future)}\n")

    return "\n".join(parts)

def format_schedule_audit_summary(
    weeks_data: list[dict],
    overall_notes: Optional[list[dict]] = None,
    risk_flags: Optional[list[str]] = None
) -> str:
    """Formats a multi-week schedule audit breakdown."""
    lines = ["### Training Schedule Audit & Workload Assessment\n"]

    for w in weeks_data:
        w_range = w.get("date_range", "Week")
        total_vol = round(w.get("total_distance_km", 0.0), 1)
        total_tss = round(w.get("total_tss", 0.0), 1)
        easy_runs = w.get("easy_count", 0)
        quality_runs = w.get("quality_count", 0)
        total_runs = easy_runs + quality_runs
        travel_info = w.get("travel_note")
        travel_str = f" | ✈️ Travel: {travel_info}" if travel_info else ""

        lines.append(
            f"* **{w_range}:** {total_vol} km ({total_runs} runs: {easy_runs} easy, {quality_runs} quality) | Planned TSS: {total_tss}{travel_str}"
        )
        
        # List individual sessions in that week
        sessions = w.get("sessions", [])
        for s in sessions:
            lines.append(f"    - {s}")
        lines.append("")

    if overall_notes:
        lines.append(f"**Calendar & Life Context:**\n{format_calendar_notes(overall_notes)}\n")

    if risk_flags:
        lines.append("**⚠️ Training Risk & Compliance Flags:**")
        for flag in risk_flags:
            lines.append(f"- {flag}")

    return "\n".join(lines)

def format_nutrition_context_summary(
    profile: dict,
    upcoming_workouts: list[dict],
    weather_forecast: Optional[str] = None
) -> str:
    """Formats athlete biometrics, upcoming training demands, and forecasted climate for nutrition planning."""
    lines = ["### Athlete Nutrition & Fueling Context\n"]

    # Biometrics & Goal
    lines.append("**1. Runner Biometrics & Target:**")
    weight = profile.get("weight") or "Not recorded"
    age = profile.get("age") or "Not recorded"
    goal = profile.get("training_goal") or "Marathon Training"
    timeline = profile.get("timeline") or "Upcoming"
    lines.append(f"- Weight: {weight} | Age: {age}")
    lines.append(f"- Training Goal: {goal} (Target Date: {timeline})\n")

    # Upcoming Workouts
    lines.append("**2. Upcoming Training Sessions (Next 3 Days):**")
    if upcoming_workouts:
        for w in upcoming_workouts:
            sport = w.get("sport", "Run")
            title = w.get("title") or sport
            date_str = format_display_date(w.get("date") or w.get("start_time"))
            dist = w.get("distance_planned_km") or w.get("distance_km") or 0.0
            dur_min = w.get("duration_planned_min") or w.get("duration_minutes") or 0
            tss = w.get("tss_planned") or 0
            lines.append(f"- [{sport}] '{title}' on {date_str} | Distance: {dist}km | Duration: {dur_min}m | Planned TSS: {tss}")
    else:
        lines.append("No planned sessions in the next 3 days.")
    lines.append("")

    # Weather
    if weather_forecast:
        lines.append(f"**3. Local Climate & Weather Forecast:**\n{weather_forecast}\n")

    return "\n".join(lines)

