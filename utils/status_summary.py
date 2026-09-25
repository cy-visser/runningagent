from typing import Optional
from .date_helpers import format_display_date
from .race_readiness import format_drivers_table, format_projection_row
from .trajectory import DEFAULT_PEAK_CTL, DEFAULT_PEAK_RANGE, TAPER_WEEKS, ramp_status

PROGRESS_BAR_SEGMENTS = 10

def format_completed_workouts(
    workouts_past: Optional[list[dict]], 
    weather_map: Optional[dict[str, str]] = None
) -> str:
    """Formats past completed workouts across all sports with optional embedded run-time weather."""
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
        dur_hrs = w.get("duration_actual")
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

def format_fitness_pmc(fitness_data: Optional[dict], race_projection: Optional[dict] = None) -> str:
    """Renders the CTL + goal-race projection table for LLM trajectory reasoning.

    ATL/TSB are not displayed as table rows; they are kept as an analysis-only
    line so recovery reasoning (TSB vs HRV/RHR) remains possible.
    """
    if fitness_data is None:
        return ""

    trajectory_info = fitness_data.get("trajectory_info", {})
    ctl_end = round(fitness_data.get("ctl_end", 0.0), 1)
    atl_end = round(fitness_data.get("atl_end", 0.0), 1)
    tsb_end = round(fitness_data.get("tsb_end", 0.0), 1)

    target_peak = trajectory_info.get("target_peak_ctl", DEFAULT_PEAK_CTL)
    ref_range = trajectory_info.get("reference_range", list(DEFAULT_PEAK_RANGE))
    req_ramp = trajectory_info.get("required_ramp_rate")
    weeks_rem = trajectory_info.get("weeks_remaining")

    pct = min(100, max(0, int((ctl_end / target_peak) * 100))) if target_peak > 0 else 100
    filled = pct // PROGRESS_BAR_SEGMENTS
    bar = "█" * filled + "░" * (PROGRESS_BAR_SEGMENTS - filled)

    ramp_str = (
        f" | Req. Ramp: `+{req_ramp} pts/wk` {ramp_status(req_ramp)} (build to {int(TAPER_WEEKS)}-week taper)"
        if req_ramp is not None else ""
    )
    weeks_str = f" ({weeks_rem}w out)" if weeks_rem is not None else ""
    range_str = f" (Range: `{ref_range[0]}-{ref_range[1]}`)" if ref_range and len(ref_range) == 2 else ""

    race_projection = race_projection or {}
    projection_row = format_projection_row(
        race_projection.get("projection"), race_projection.get("goal_label"), weeks_str
    )
    drivers = format_drivers_table(race_projection.get("projection"))
    drivers_str = f"\n{drivers}\n" if drivers else ""

    return (
        "| Metric | Current Value | Target / Reference | Progress & Trajectory |\n"
        "|---|---|---|---|\n"
        f"| **CTL (Fitness)** | `{ctl_end}` | Target: `{target_peak}`{range_str}{weeks_str} | `[{bar}]` **{pct}%**{ramp_str} |\n"
        f"{projection_row}"
        f"{drivers_str}"
        f"\nLoad context (analysis only, not displayed): ATL `{atl_end}` | TSB `{tsb_end:+.1f}`\n"
    )

def compile_checkin_summary(
    lookback_days: int,
    lookahead_days: int,
    workouts_past: Optional[list[dict]],
    workouts_future: Optional[list[dict]],
    metrics_data: Optional[dict],
    fitness_data: Optional[dict],
    notes_list: Optional[list[dict]],
    weather_map: Optional[dict[str, str]] = None,
    race_projection: Optional[dict] = None,
    weekly_totals: Optional[list[dict]] = None,
) -> str:
    """Compiles a complete, unified Check-In Summary payload for the check-in-report skill.

    race_projection: {"goal_label": str | None, "projection": dict | None} from race_readiness.project_race.
    weekly_totals: completed-week buckets from utils.weekly (km, TSS, easy/quality counts).
    """
    parts = ["### Weekly Check-In Training & Physiological Report\n"]

    if fitness_data is not None:
        parts.append(
            f"**1. Fitness PMC Trends, Goal Race Projection & Trajectory (Past {lookback_days} days):**\n"
            f"{format_fitness_pmc(fitness_data, race_projection)}\n"
        )

    if metrics_data is not None:
        parts.append(f"**2. Autonomic & Physiological Recovery Trends (Past {lookback_days} days):**\n{format_recovery_metrics(metrics_data)}\n")

    if weekly_totals is not None:
        parts.append(f"**3. Weekly Totals (completed, pre-computed; do not recompute):**\n{format_weekly_totals(weekly_totals)}\n")

    if workouts_past is not None:
        parts.append(f"**4. Completed Workouts & Environmental Context (Past {lookback_days} days):**\n{format_completed_workouts(workouts_past, weather_map)}\n")

    if notes_list is not None:
        parts.append(f"**5. Calendar & Travel Notes:**\n{format_calendar_notes(notes_list)}\n")

    if workouts_future is not None:
        parts.append(f"**6. Upcoming Scheduled Workouts (Next {lookahead_days} days):**\n{format_planned_workouts(workouts_future)}\n")

    return "\n".join(parts)

def _format_week_line(w: dict) -> str:
    """One-line weekly totals: running km, run split, cross-training and TSS."""
    w_range = w.get("date_range", "Week")
    total_vol = round(w.get("total_distance_km", 0.0), 1)
    total_tss = round(w.get("total_tss", 0.0), 1)
    easy_runs = w.get("easy_count", 0)
    quality_runs = w.get("quality_count", 0)
    total_runs = easy_runs + quality_runs

    cross_parts = []
    bike_count = w.get("bike_count", 0)
    if bike_count > 0:
        cross_parts.append(f"{bike_count} bike" if bike_count == 1 else f"{bike_count} bikes")
    strength_count = w.get("strength_count", 0)
    if strength_count > 0:
        cross_parts.append(f"{strength_count} strength")
    other_count = w.get("other_sport_count", 0)
    if other_count > 0:
        cross_parts.append(f"{other_count} other")
    cross_str = f" | {', '.join(cross_parts)}" if cross_parts else ""

    return (
        f"* **{w_range}:** {total_vol} km ({total_runs} runs: {easy_runs} easy, "
        f"{quality_runs} quality{cross_str}) | TSS: {total_tss}"
    )


def format_weekly_totals(weeks: Optional[list[dict]]) -> str:
    """Pre-computed weekly totals (no LLM arithmetic needed)."""
    if not weeks:
        return "No completed training in this window."
    return "\n".join(_format_week_line(w) for w in weeks)


def format_schedule_audit_summary(weeks_data: list[dict]) -> str:
    """Formats a multi-week schedule audit breakdown with each week's sessions and notes."""
    lines = ["### Training Schedule Audit & Workload Assessment\n"]

    for w in weeks_data:
        lines.append(_format_week_line(w))
        for s in w.get("sessions", []):
            lines.append(f"    - {s}")
        for note in w.get("notes", []):
            lines.append(f"    - 📝 Note: {note}")
        lines.append("")

    return "\n".join(lines)


def format_nutrition_context_summary(
    profile: dict,
    upcoming_workouts: list[dict],
    weather_forecast: Optional[str] = None,
    days_forward: int = 3,
) -> str:
    """Formats athlete biometrics, upcoming training demands, and forecasted climate for nutrition planning."""
    lines = ["### Athlete Nutrition & Fueling Context\n"]

    # Biometrics & Goal
    lines.append("**1. Runner Biometrics & Target:**")
    weight = profile.get("weight") or "Not recorded"
    age = profile.get("age") or "Not recorded"
    goal = profile.get("training_goal") or "Not set"
    timeline = profile.get("timeline") or "Not set"
    lines.append(f"- Weight: {weight} | Age: {age}")
    lines.append(f"- Training Goal: {goal} (Target Date: {timeline})\n")

    # Upcoming Workouts
    lines.append(f"**2. Upcoming Training Sessions (Next {days_forward} Days):**")
    if upcoming_workouts:
        for w in upcoming_workouts:
            sport = w.get("sport", "Run")
            title = w.get("title") or sport
            date_str = format_display_date(w.get("date") or w.get("start_time"))
            dist = w.get("distance_planned_km") or 0.0
            hours = w.get("duration_planned")
            dur_str = f"{round(float(hours) * 60)} min" if isinstance(hours, (int, float)) and hours > 0 else "n/a"
            tss = w.get("tss_planned") or 0
            lines.append(f"- [{sport}] '{title}' on {date_str} | Distance: {dist}km | Duration: {dur_str} | Planned TSS: {tss}")
    else:
        lines.append(f"No planned sessions in the next {days_forward} days.")
    lines.append("")

    # Weather
    if weather_forecast:
        lines.append(f"**3. Local Climate & Weather Forecast:**\n{weather_forecast}\n")

    return "\n".join(lines)
