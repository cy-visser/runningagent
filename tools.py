import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from google.adk.code_executors import UnsafeLocalCodeExecutor
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.skill_toolset import SkillToolset

from .services.firestore import (
    get_cached_workout_analysis,
    get_user_id,
    save_checkin_report as save_checkin_report_data,
    save_workout_analysis,
)
from .services.tp_mcp import get_tp_tool
from .services.weather import get_weather_conditions, get_weather_for_dates
from .utils import (
    ANALYSIS_SCHEMA_VERSION,
    PROJECTION_WINDOW_DAYS,
    coerce_mcp_payload,
    compile_checkin_summary,
    evaluate_goal_trajectory,
    extract_health_metrics,
    extract_health_metrics_dated,
    extract_thresholds,
    format_display_date,
    format_nutrition_context_summary,
    format_recovery_metrics,
    format_schedule_audit_summary,
    format_workout_analysis,
    get_today_date,
    is_workout_completed,
    iso_week_key,
    parse_date,
    parse_mcp_response,
    parse_target_time_minutes,
    partition_workouts_by_date,
    project_race,
    resolve_goal_distance,
    select_for_analysis,
    summarize_analysis,
)
from .utils import completed_runs as completed_goal_runs
from .utils.race_readiness import is_complete_summary
from .utils.paths import SKILLS_DIR

logger = logging.getLogger(__name__)

ISO_FMT = "%Y-%m-%d"

# Sport classification used by the schedule audit.
RUN_SPORTS = {"run", "running", "trail run", "treadmill"}
BIKE_SPORTS = {"bike", "cycling", "mtnbike", "gravel", "virtualride"}
STRENGTH_SPORTS = {"strength", "gym", "weighttraining", "s&c"}
# Calendar placeholders that carry no training load.
NON_TRAINING_SPORTS = {"DayOff", "Other"}
QUALITY_KEYWORDS = (
    "interval", "tempo", "threshold", "race", "speed",
    "reps", "mp", "push", "hills", "progression",
)

# ==============================================================================
# 1. Skills Toolset Configuration
# ==============================================================================
SKILL_NAMES = (
    "nutrition-planner",
    "check-in-report",
    "workout-analysis",
    "bike-workout-analysis",
    "schedule-audit",
    "workout-creator",
)


class CompactSkillToolset(SkillToolset):
    """SkillToolset that suppresses ListSkillsTool so the skills XML catalog is
    pre-injected into the system prompt, enabling single-turn skill loading.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tools = [t for t in self._tools if t.name != "list_skills"]


skill_toolset = CompactSkillToolset(
    skills=[load_skill_from_dir(os.path.join(SKILLS_DIR, name)) for name in SKILL_NAMES],
    code_executor=UnsafeLocalCodeExecutor(),
)


# ==============================================================================
# 2. Shared Helpers
# ==============================================================================
def _location_args(profile: dict) -> Optional[dict[str, Any]]:
    """Returns the geo kwargs for a weather lookup, or None if the runner has no location."""
    loc = profile.get("location", "")
    lat = profile.get("latitude")
    lon = profile.get("longitude")
    if not loc and (lat is None or lon is None):
        return None
    return {"location": loc or "", "lat": lat, "lon": lon}


async def _fetch_weather_text(profile: dict, dates: list[str]) -> str:
    """Returns a formatted weather narrative for the given dates, or '' when unavailable."""
    geo = _location_args(profile)
    if not geo or not dates:
        return ""
    result = await asyncio.to_thread(get_weather_for_dates, dates=dates, **geo)
    # The service reports failures as human-readable strings; never pass those to the model.
    if not result or result.startswith(("Error", "Could not geocode", "No weather", "Weather forecast is only")):
        logger.info("Weather text unavailable: %s", result)
        return ""
    return result


async def _fetch_weather_map(profile: dict, timestamps: list[str]) -> dict[str, str]:
    """Returns {timestamp: conditions} for the given run timestamps, or {} when unavailable."""
    geo = _location_args(profile)
    if not geo or not timestamps:
        return {}
    return await asyncio.to_thread(get_weather_conditions, dates=timestamps, **geo)


async def _run_tp_tool(tool_context: ToolContext, tool_name: str, **node_input: Any) -> Any:
    """Resolves a TrainingPeaks MCP tool by name and invokes it."""
    tool = await get_tp_tool(tool_name)
    return await tool_context.run_node(tool, node_input=node_input or None)


async def _fetch_workouts(tool_context: ToolContext, start: str, end: str) -> list[dict]:
    """Fetches the workout list for a date range, returning [] when nothing is available."""
    raw = await _run_tp_tool(tool_context, "tp_get_workouts", start_date=start, end_date=end)
    parsed = parse_mcp_response(raw) or {}
    workouts = parsed.get("workouts", [])
    return workouts if isinstance(workouts, list) else []


def _result_or_none(result: Any, label: str) -> Any:
    """Unwraps a gather() result, logging and discarding exceptions."""
    if isinstance(result, Exception):
        logger.warning("Failed to fetch %s: %s", label, result)
        return None
    return result


# ==============================================================================
# 3. Skill Facades (1 Facade per Skill)
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
        target_date = parse_date(date_str) or today_date

    target_iso = target_date.strftime(ISO_FMT)
    workout_start_time = None
    workout_sport = "Workout"
    workout_title = ""

    # 1. Resolve workout_id if not provided
    if not workout_id:
        try:
            workouts_list = await _fetch_workouts(tool_context, target_iso, target_iso)
        except Exception as e:
            logger.error("Failed to look up workout for %s: %s", target_iso, e)
            return f"Error: Failed to find workout for {target_iso}: {e}"

        completed_runs = [w for w in workouts_list if is_workout_completed(w)]
        if not completed_runs:
            if workouts_list:
                titles = ", ".join(
                    f"'{w.get('title') or w.get('sport', 'Workout')}'" for w in workouts_list
                )
                return f"No completed workout found for {target_iso}. Planned sessions found on calendar: {titles}."
            return f"No completed workouts found on {target_iso}."

        target_workout = completed_runs[-1]
        workout_id = str(target_workout.get("id") or target_workout.get("workoutId") or "")
        workout_sport = target_workout.get("sport", "Workout")
        workout_title = target_workout.get("title") or workout_sport
        workout_start_time = (
            target_workout.get("start_time")
            or target_workout.get("startTime")
            or target_workout.get("date")
        )

    if not workout_id:
        return "Error: No workout ID could be determined."

    # 2. Fetch workout analysis and recovery metrics concurrently
    try:
        tasks = [_run_tp_tool(tool_context, "tp_analyze_workout", workout_id=workout_id)]
        if include_recovery:
            metrics_start = (target_date - timedelta(days=7)).strftime(ISO_FMT)
            tasks.append(
                _run_tp_tool(
                    tool_context, "tp_get_metrics",
                    start_date=metrics_start, end_date=target_iso,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        analyze_res = results[0]
        if isinstance(analyze_res, Exception):
            return f"Error analyzing workout {workout_id}: {analyze_res}"

        data = parse_mcp_response(analyze_res)
        if not isinstance(data, dict) or not data:
            return f"No analysis data returned for workout {workout_id}."

        analysis_str = format_workout_analysis(
            data, title=workout_title or None, sport=workout_sport or None
        )

        # 3. Attach Environmental Weather
        weather_section = ""
        if include_weather:
            start_time = workout_start_time or data.get("startTime") or data.get("workoutDay") or target_iso
            weather_text = await _fetch_weather_text(profile, [str(start_time)])
            if weather_text:
                weather_section = f"\n\n**Environmental & Weather Context:**\n{weather_text}"

        # 4. Attach Recovery Context
        recovery_section = ""
        if include_recovery:
            metrics_res = _result_or_none(results[1], "recovery metrics")
            if metrics_res:
                rec_formatted = format_recovery_metrics(extract_health_metrics(metrics_res))
                if rec_formatted:
                    recovery_section = f"\n\n**Morning Physiological Recovery Context:**\n{rec_formatted}"

        return f"{analysis_str}{recovery_section}{weather_section}"
    except Exception as e:
        logger.error("analyze_workout failed for %s: %s", workout_id, e)
        return f"Error: Failed to analyze workout {workout_id}: {e}"


analyze_workout_tool = FunctionTool(analyze_workout)


# Check-In Report (for check-in-report skill) ---
# PMC history window (CTL-at-session lookup for the detraining adjustment).
PROJECTION_LOOKBACK_DAYS = 90
# Health baseline window for the readiness signal.
HEALTH_LOOKBACK_DAYS = 28


def _summarize_fitness(
    fitness_raw: Any, profile: dict, today_date: Any, window_start: Any = None
) -> Optional[dict]:
    """Extracts PMC start/end values and the resulting goal trajectory.

    When window_start is given, start/end bounds and daily_list cover only the
    check-in window; the full PMC series is kept under 'history'.
    """
    if not fitness_raw:
        return None

    fit_parsed = parse_mcp_response(fitness_raw) or {}
    history = fit_parsed.get("daily_data", [])
    if not isinstance(history, list):
        history = []

    window_date = parse_date(window_start)
    fitness_list = [
        d for d in history
        if window_date is None or (parse_date(d.get("date")) or window_date) >= window_date
    ]

    bounds = {f"{m}_{edge}": 0.0 for m in ("ctl", "atl", "tsb") for edge in ("start", "end")}
    if fitness_list:
        ordered = sorted(fitness_list, key=lambda x: str(x.get("date", "")))
        for metric in ("ctl", "atl", "tsb"):
            bounds[f"{metric}_start"] = ordered[0].get(metric, 0.0)
            bounds[f"{metric}_end"] = ordered[-1].get(metric, 0.0)

    return {
        **bounds,
        "daily_list": fitness_list,
        "history": history,
        "trajectory_info": evaluate_goal_trajectory(profile, bounds["ctl_end"], today_date),
    }


async def _cache_read(user_id: Optional[str], workout_id: str) -> Optional[dict]:
    """Returns a valid cached workout summary, or None (cache miss / unavailable)."""
    if not user_id or not workout_id:
        return None
    try:
        cached = await get_cached_workout_analysis(user_id, workout_id)
    except Exception as e:  # Firestore unavailable (e.g. local runs) -> just analyse
        logger.info("Workout analysis cache read failed for %s: %s", workout_id, e)
        return None
    if (isinstance(cached, dict) and cached.get("version") == ANALYSIS_SCHEMA_VERSION
            and is_complete_summary(cached)):
        return cached
    return None


async def _cache_write(user_id: Optional[str], workout_id: str, summary: dict) -> None:
    if not user_id or not workout_id:
        return
    try:
        await save_workout_analysis(user_id, workout_id, summary)
    except Exception as e:
        logger.info("Workout analysis cache write failed for %s: %s", workout_id, e)


async def _load_workout_summaries(
    tool_context: ToolContext,
    workouts: list[dict],
    user_id: Optional[str],
    refresh: bool = False,
) -> list[dict]:
    """Cache-first workout summaries: reads Firestore, analyses only misses, saves new ones.

    Completed workouts don't change, so each tp_analyze_workout call is made once
    per workout; `refresh` bypasses the cache (e.g. after a schema/lap fix in TP).
    """
    ids = [str(w.get("id") or "") for w in workouts]
    cached = (
        [None] * len(workouts) if refresh
        else await asyncio.gather(*(_cache_read(user_id, wid) for wid in ids))
    )
    misses = [i for i, c in enumerate(cached) if c is None and ids[i]]
    raws = await asyncio.gather(
        *(_run_tp_tool(tool_context, "tp_analyze_workout", workout_id=ids[i]) for i in misses),
        return_exceptions=True,
    )
    summaries: list[Optional[dict]] = list(cached)
    writes = []
    for i, raw in zip(misses, raws):
        raw = _result_or_none(raw, f"analysis {ids[i]}")
        summary = summarize_analysis(raw, workouts[i]) if raw else None
        summaries[i] = summary
        if is_complete_summary(summary):
            writes.append(_cache_write(user_id, ids[i], summary))
    if writes:
        await asyncio.gather(*writes)
    logger.info(
        "Workout summaries: %d cached, %d analysed", len(workouts) - len(misses), len(misses)
    )
    return [s for s in summaries if s]


async def _build_goal_projection(
    tool_context: ToolContext,
    goal: Optional[tuple[str, float, str]],
    profile: dict,
    all_workouts: list[dict],
    fitness_data: Optional[dict],
    settings_raw: Any,
    dated_metrics: Optional[dict],
    today_date: Any,
    refresh_cache: bool = False,
) -> dict:
    """Builds the evidence-based goal-race projection payload for compile_checkin_summary."""
    if not goal:
        return {"goal_label": None, "projection": None}
    label = goal[0]
    fitness_data = fitness_data or {}
    runs = completed_goal_runs(
        all_workouts, today_date - timedelta(days=PROJECTION_WINDOW_DAYS), today_date
    )
    user_id = get_user_id(profile.get("firstname"), profile.get("lastname"))
    user_id = user_id if user_id and user_id != "_" else None
    summaries = await _load_workout_summaries(
        tool_context, select_for_analysis(runs, label), user_id, refresh=refresh_cache
    )
    projection = project_race(
        goal_label=label,
        goal_minutes=parse_target_time_minutes(profile.get("training_goal")),
        runs=runs,
        summaries=summaries,
        thresholds=extract_thresholds(settings_raw),
        daily_pmc=fitness_data.get("history"),
        fitness=fitness_data,
        trajectory_info=fitness_data.get("trajectory_info"),
        dated_metrics=dated_metrics,
        today=today_date,
        block_start=profile.get("goal_set_date"),
    )
    return {"goal_label": label, "projection": projection}


async def fetch_checkin_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh_analysis_cache: bool = False,
) -> str:
    """Fetches all data needed for a comprehensive weekly check-in report.

    Includes:
    - 14-day past completed workouts with run-time weather
    - 7-day future scheduled workouts
    - 14-day recovery metrics (Sleep, HRV, RHR)
    - 14-day PMC fitness trends (CTL table, ATL/TSB load context, goal trajectory)
    - Projected goal-race time (today and race day) for the Firestore training_goal,
      from threshold laps, goal-pace segments, HR efficiency, durability, load
      and health readiness, with a 'Projection drivers' evidence table
    - Calendar notes (work stress, travel, illness)

    Args:
        refresh_analysis_cache: Re-analyse key workouts instead of using cached summaries.
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."

    today_date = get_today_date()
    q_start = parse_date(start_date) or (today_date - timedelta(days=14))
    q_end = parse_date(end_date) or (today_date + timedelta(days=7))
    goal = resolve_goal_distance(profile.get("training_goal"))

    start_str = q_start.strftime(ISO_FMT)
    end_str = q_end.strftime(ISO_FMT)
    recovery_end_str = min(q_end, today_date).strftime(ISO_FMT)
    workouts_start = min(q_start, today_date - timedelta(days=PROJECTION_WINDOW_DAYS))
    metrics_start = min(q_start, today_date - timedelta(days=HEALTH_LOOKBACK_DAYS))
    history_start_str = min(
        q_start, today_date - timedelta(days=PROJECTION_LOOKBACK_DAYS)
    ).strftime(ISO_FMT)

    # Phase 1: gather calendar, notes, metrics, PMC and athlete thresholds.
    fetches = {
        "workouts": _run_tp_tool(
            tool_context, "tp_get_workouts",
            start_date=workouts_start.strftime(ISO_FMT), end_date=end_str,
        ),
        "calendar notes": _run_tp_tool(tool_context, "tp_list_notes", start_date=start_str, end_date=end_str),
        "recovery metrics": _run_tp_tool(
            tool_context, "tp_get_metrics",
            start_date=metrics_start.strftime(ISO_FMT), end_date=recovery_end_str,
        ),
        "fitness PMC": _run_tp_tool(
            tool_context, "tp_get_fitness", start_date=history_start_str, end_date=recovery_end_str
        ),
    }
    if goal:
        fetches["athlete settings"] = _run_tp_tool(tool_context, "tp_get_athlete_settings")
    results = await asyncio.gather(*fetches.values(), return_exceptions=True)
    raw = {label: _result_or_none(r, label) for label, r in zip(fetches, results)}

    workouts_data = coerce_mcp_payload(raw["workouts"]) if raw["workouts"] else {}
    all_workouts = workouts_data.get("workouts", []) or []
    in_window = [
        w for w in all_workouts
        if (parse_date(w.get("date") or w.get("start_time")) or q_start) >= q_start
    ]
    workouts_past, workouts_future = partition_workouts_by_date(in_window, today_date)

    dated_metrics = extract_health_metrics_dated(raw["recovery metrics"]) if raw["recovery metrics"] else None
    metrics_data = (
        {k: [v for d, v in vals if d >= q_start] for k, vals in dated_metrics.items()}
        if dated_metrics else None
    )
    notes_raw = raw["calendar notes"]
    notes_list = (coerce_mcp_payload(notes_raw).get("notes", []) or []) if notes_raw else None
    fitness_data = _summarize_fitness(raw["fitness PMC"], profile, today_date, window_start=q_start)

    # Phase 2: analyse the key sessions (cache-first) and project the goal race.
    race_projection = await _build_goal_projection(
        tool_context, goal, profile, all_workouts, fitness_data,
        raw.get("athlete settings"), dated_metrics, today_date,
        refresh_cache=refresh_analysis_cache,
    )

    # Attach the real recorded conditions for each completed run.
    run_timestamps = [
        str(w.get("start_time") or w.get("date"))
        for w in workouts_past
        if (w.get("start_time") or w.get("date"))
    ]
    weather_map = await _fetch_weather_map(profile, run_timestamps)

    return compile_checkin_summary(
        lookback_days=(today_date - q_start).days,
        lookahead_days=(q_end - today_date).days,
        workouts_past=workouts_past,
        workouts_future=workouts_future,
        metrics_data=metrics_data,
        fitness_data=fitness_data,
        notes_list=notes_list,
        weather_map=weather_map,
        race_projection=race_projection,
    )


fetch_checkin_data_tool = FunctionTool(fetch_checkin_data)


# Schedule Audit (for schedule-audit skill) ---
def _new_week_bucket(day: Any) -> dict:
    """Creates an empty weekly aggregation bucket for the ISO week containing `day`."""
    w_start = day - timedelta(days=day.weekday())
    w_end = w_start + timedelta(days=6)
    return {
        "date_range": f"{w_start.strftime('%b %d')} - {w_end.strftime('%b %d, %Y')}",
        "start_date": w_start,
        "end_date": w_end,
        "total_distance_km": 0.0,
        "total_tss": 0.0,
        "easy_count": 0,
        "quality_count": 0,
        "bike_count": 0,
        "strength_count": 0,
        "other_sport_count": 0,
        "sessions": [],
        "travel_note": None,
    }


def _tally_workout(bucket: dict, workout: dict, w_date: Any) -> None:
    """Adds a single workout's volume, load, and intensity classification to its week bucket."""
    sport = (workout.get("sport") or "Run").strip()
    sport_lower = sport.lower()

    dist = float(
        workout.get("distance_planned_km")
        or workout.get("distance_km")
        or workout.get("distance_actual_km")
        or 0.0
    )
    tss = float(workout.get("tss_planned") or workout.get("tss") or workout.get("tss_actual") or 0.0)
    bucket["total_tss"] += tss

    title = workout.get("title") or sport
    title_lower = title.lower()

    if sport_lower in RUN_SPORTS:
        bucket["total_distance_km"] += dist
        is_quality = any(kw in title_lower for kw in QUALITY_KEYWORDS)
        bucket["quality_count" if is_quality else "easy_count"] += 1
    elif sport_lower in BIKE_SPORTS:
        bucket["bike_count"] += 1
    elif sport_lower in STRENGTH_SPORTS:
        bucket["strength_count"] += 1
    else:
        bucket["other_sport_count"] += 1

    dist_str = f"{round(dist, 1)}km, " if dist > 0 else ""
    bucket["sessions"].append(
        f"[{sport}] '{title}' on {format_display_date(w_date)} ({dist_str}TSS: {round(tss, 0)})"
    )


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

    start_str = q_start.strftime(ISO_FMT)
    end_str = q_end.strftime(ISO_FMT)

    workouts_raw, notes_raw = [
        _result_or_none(r, label)
        for r, label in zip(
            await asyncio.gather(
                _run_tp_tool(tool_context, "tp_get_workouts", start_date=start_str, end_date=end_str),
                _run_tp_tool(tool_context, "tp_list_notes", start_date=start_str, end_date=end_str),
                return_exceptions=True,
            ),
            ("workouts", "calendar notes"),
        )
    ]

    workouts_data = parse_mcp_response(workouts_raw) or {} if workouts_raw else {}
    workouts_list = workouts_data.get("workouts", [])
    notes_parsed = parse_mcp_response(notes_raw) or {} if notes_raw else {}
    notes_list = notes_parsed.get("notes", []) if notes_raw else []

    # Seed one bucket per ISO week in the audit window.
    weeks_dict: dict[str, dict] = {}
    cur = q_start
    while cur <= q_end:
        weeks_dict.setdefault(iso_week_key(cur), _new_week_bucket(cur))
        cur += timedelta(days=7)

    for w in workouts_list:
        w_date = parse_date(w.get("date") or w.get("start_time"))
        if not w_date:
            continue
        # Skip calendar rest placeholders and educational/tip cards.
        if (w.get("sport") or "Run").strip() in NON_TRAINING_SPORTS:
            continue
        bucket = weeks_dict.get(iso_week_key(w_date))
        if bucket:
            _tally_workout(bucket, w, w_date)

    for n in notes_list:
        n_date = parse_date(n.get("date"))
        bucket = weeks_dict.get(iso_week_key(n_date)) if n_date else None
        if bucket:
            n_title = n.get("title", "")
            n_desc = n.get("description", "")
            bucket["travel_note"] = f"{n_title}: {n_desc}" if n_desc else n_title

    return format_schedule_audit_summary(
        weeks_data=list(weeks_dict.values()),
        overall_notes=notes_list,
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

    upcoming = await _fetch_workouts(
        tool_context, today_date.strftime(ISO_FMT), end_date.strftime(ISO_FMT)
    )

    forecast_dates = [
        (today_date + timedelta(days=i)).strftime(ISO_FMT) for i in range(days_forward + 1)
    ]
    weather_str = await _fetch_weather_text(profile, forecast_dates)

    return format_nutrition_context_summary(
        profile=profile,
        upcoming_workouts=upcoming,
        weather_forecast=weather_str,
    )


fetch_nutrition_context_tool = FunctionTool(fetch_nutrition_context)


# Workout & Calendar Note Creation (for workout-creator skill) ---
async def _find_existing_workout(
    tool_context: ToolContext,
    target_iso: str,
    sport: str,
) -> Optional[str]:
    """Finds the ID of an existing planned workout on the target date, preferring a sport match."""
    try:
        raw_workouts = await _run_tp_tool(
            tool_context, "tp_get_workouts", start_date=target_iso, end_date=target_iso
        )
    except Exception as e:
        logger.warning("Failed checking existing workouts for %s: %s", target_iso, e)
        return None

    workouts_list = coerce_mcp_payload(raw_workouts).get("workouts", [])
    planned = [w for w in workouts_list if not is_workout_completed(w)]
    if not planned:
        return None

    matching = [w for w in planned if sport.lower() in (w.get("sport") or "").lower()]
    chosen = (matching or planned)[0]
    return str(chosen.get("id") or chosen.get("workoutId") or "") or None


# Per-action differences between the create and update MCP tools.
_CREATE_SPEC = {"tool": "tp_create_workout", "date_key": "date_str", "duration_cast": int}
_UPDATE_SPEC = {"tool": "tp_update_workout", "date_key": "date", "duration_cast": float}


async def _write_workout(
    tool_context: ToolContext,
    date_str: str,
    sport: str,
    title: str,
    workout_id: Optional[str] = None,
    duration_minutes: Optional[int | float] = None,
    distance_km: Optional[float] = None,
    tss_planned: Optional[float] = None,
    description: Optional[str] = None,
    structure: Optional[Any] = None,
) -> str:
    """Creates or updates a TrainingPeaks workout, depending on whether workout_id is set."""
    spec = _UPDATE_SPEC if workout_id else _CREATE_SPEC
    action = "updated" if workout_id else "created"

    node_input: dict[str, Any] = {
        spec["date_key"]: date_str,
        "sport": sport,
        "title": title,
    }
    if workout_id:
        node_input["workout_id"] = workout_id
    if duration_minutes is not None:
        node_input["duration_minutes"] = spec["duration_cast"](duration_minutes)
    if distance_km is not None:
        node_input["distance_km"] = float(distance_km)
    if tss_planned is not None:
        node_input["tss_planned"] = float(tss_planned)
    if description is not None:
        node_input["description"] = description
    if structure is not None:
        node_input["structure"] = structure

    try:
        result = await _run_tp_tool(tool_context, spec["tool"], **node_input)
    except Exception as e:
        logger.error("Failed to %s workout (%s): %s", action[:-1], date_str, e)
        return f"Error: Failed to {action[:-1]} workout: {e}"

    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return f"Error {action[:-1]}ing workout: {data.get('message', 'Unknown error')}"

    resolved_id = workout_id or data.get("id") or data.get("workoutId") or data.get("workout_id")
    return json.dumps({
        "success": True,
        "action": action,
        "workout_id": resolved_id,
        "title": title,
        "date": date_str,
        "sport": sport,
        "duration_minutes": duration_minutes,
        "distance_km": distance_km,
        "tss_planned": tss_planned,
    })


async def create_workout(
    tool_context: ToolContext,
    date_str: str,
    sport: str = "Run",
    title: str = "Planned Run",
    duration_minutes: Optional[int | float] = None,
    distance_km: Optional[float] = None,
    tss_planned: Optional[float] = None,
    description: Optional[str] = None,
    structure: Optional[Any] = None,
    workout_id: Optional[str] = None,
    create: bool = False,
) -> str:
    """Creates a new planned workout or updates an existing workout in TrainingPeaks.

    Acts as the intelligent workout management facade:
    - If `workout_id` is provided, updates that specific workout.
    - If `workout_id` is not provided and `create` is False, checks if an existing planned workout exists on `date_str`.
      - If an existing planned workout is found on that date, updates it.
      - If no existing planned workout is found on that date, creates a new workout.
    - If `create` is True, creates a new workout unconditionally.

    Args:
        tool_context: ADK tool context.
        date_str: Workout date in ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).
        sport: Sport type (default 'Run', e.g. 'Run', 'Bike', 'Swim', 'Strength', 'Walk', 'Crosstrain', 'Race').
        title: Workout title (e.g. 'Easy Aerobic Recovery Run', 'Threshold Intervals: 5x1km').
        duration_minutes: Planned duration in minutes.
        distance_km: Optional planned distance in kilometres.
        tss_planned: Optional planned Training Stress Score.
        description: Structured coaching instructions (warm-up, main set, cool-down, pacing cues).
        structure: Optional interval structure dictionary or JSON string.
        workout_id: Optional workout ID to update directly.
        create: If True, forces creating a new workout instead of updating an existing one on that date.
    """
    target_date = parse_date(date_str)
    target_iso = target_date.strftime(ISO_FMT) if target_date else date_str[:10]

    target_workout_id = workout_id
    if not target_workout_id and not create:
        target_workout_id = await _find_existing_workout(tool_context, target_iso, sport)

    return await _write_workout(
        tool_context=tool_context,
        date_str=date_str,
        sport=sport,
        title=title,
        workout_id=target_workout_id,
        duration_minutes=duration_minutes,
        distance_km=distance_km,
        tss_planned=tss_planned,
        description=description,
        structure=structure,
    )


create_workout_tool = FunctionTool(create_workout)


async def create_note(
    tool_context: ToolContext,
    date: str,
    title: str,
    description: Optional[str] = None,
) -> str:
    """Creates a calendar note in TrainingPeaks."""
    node_input: dict[str, Any] = {"date": date, "title": title}
    if description is not None:
        node_input["description"] = description

    try:
        result = await _run_tp_tool(tool_context, "tp_create_note", **node_input)
    except Exception as e:
        logger.error("Failed to create calendar note on %s: %s", date, e)
        return f"Error: Failed to create calendar note: {e}"

    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return f"Error creating note: {data.get('message', 'Unknown error')}"
    return json.dumps(data) if data else "Success: Calendar note created."


create_note_tool = FunctionTool(create_note)


# ==============================================================================
# 4. Action Tools (History Persistence, Goal Re-onboarding, General Weather)
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
        await save_checkin_report_data(user_id, doc_id, {
            "week": iso_week,
            "year": iso_year,
            "created_at": today.isoformat(),
            "report_markdown": report_content,
        })
    except Exception as e:
        logger.error("Failed to save check-in report '%s' for %s: %s", doc_id, user_id, e)
        return f"Error: Failed to save the report to Firestore: {e}"

    logger.info("Saved check-in report '%s' to Firestore for %s", doc_id, user_id)
    return f"Success: Your check-in report for Week {iso_week}, {iso_year} has been saved to your history."


save_checkin_report_tool = FunctionTool(save_checkin_report)


async def request_new_goal(tool_context: ToolContext) -> str:
    """Signals that the runner wants to set up a new training goal and trigger re-onboarding."""
    tool_context.state["reonboard_requested"] = True
    return "Re-onboarding initiated. Transitioning to onboarding agent to set up your new goal."


request_new_goal_tool = FunctionTool(request_new_goal)

get_weather_tool = FunctionTool(get_weather_for_dates)


# ==============================================================================
# 5. Public Tool Exports
# ==============================================================================
__all__ = [
    "skill_toolset",
    "analyze_workout_tool",
    "fetch_checkin_data_tool",
    "fetch_schedule_audit_data_tool",
    "fetch_nutrition_context_tool",
    "create_workout_tool",
    "create_note_tool",
    "save_checkin_report_tool",
    "request_new_goal_tool",
    "get_weather_tool",
]
