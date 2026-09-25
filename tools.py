import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from google.adk.skills import load_skill_from_dir
from google.adk.skills.prompt import format_skills_as_xml
from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.skill_toolset import SkillToolset

from .services.firestore import (
    get_cached_workout_analysis,
    save_checkin_report as save_checkin_report_data,
    save_workout_analysis,
)
from .services.tp_mcp import get_tp_tool
from .services.weather import format_weather_conditions, get_weather_conditions, get_weather_for_dates
from .utils import (
    ANALYSIS_SCHEMA_VERSION,
    PROJECTION_WINDOW_DAYS,
    coerce_mcp_payload,
    compile_checkin_summary,
    evaluate_goal_trajectory,
    extract_health_metrics,
    extract_health_metrics_dated,
    extract_thresholds,
    format_nutrition_context_summary,
    format_recovery_metrics,
    format_schedule_audit_summary,
    format_other_sessions,
    format_workout_analysis,
    get_today_date,
    is_workout_completed,
    select_primary_workout,
    parse_date,
    parse_mcp_response,
    parse_target_time_minutes,
    partition_workouts_by_date,
    profile_user_id,
    project_race,
    resolve_goal_distance,
    select_for_analysis,
    summarize_analysis,
)
from .utils import completed_runs as completed_goal_runs
from .utils.date_helpers import ISO_DATE_FMT
from .utils.paths import SKILLS_DIR
from .utils.race_readiness import HEALTH_BASELINE_DAYS, is_complete_summary
from .utils.weekly import add_notes_to_weeks, build_week_buckets
from .utils.structure import (
    align_laps,
    flatten_structure,
    format_structured_execution,
    has_structure,
    session_decoupling,
    sport_thresholds,
)

logger = logging.getLogger(__name__)

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

_SKILL_INSTRUCTION = (
    "You can use specialized skills. Each skill has a SKILL.md with the protocol and output "
    "format for one task. When a skill matches the request, call `load_skill` with its name "
    "BEFORE any other tool, then follow its instructions exactly and complete every step. "
    "Available skills:"
)


class CompactSkillToolset(SkillToolset):
    """Exposes only `load_skill`, with a compact prompt and the pre-rendered skill catalog.

    ADK's default skill prompt (~300 words, sent on every model call) documents
    list_skills / load_skill_resource / run_skill_script and references/assets/scripts
    folders; no skill here ships any of those, so they are dropped.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tools = [t for t in self._tools if t.name == "load_skill"]

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: Any) -> None:
        llm_request.append_instructions([_SKILL_INSTRUCTION, format_skills_as_xml(self._list_skills())])


skill_toolset = CompactSkillToolset(
    skills=[load_skill_from_dir(os.path.join(SKILLS_DIR, name)) for name in SKILL_NAMES],
)


# ==============================================================================
# 2. Shared Helpers
# ==============================================================================
def _iso(day: Any) -> str:
    return day.strftime(ISO_DATE_FMT)


def _location_args(profile: dict) -> Optional[dict[str, Any]]:
    """Returns the geo kwargs for a weather lookup, or None if the runner has no location."""
    loc = profile.get("location", "")
    lat = profile.get("latitude")
    lon = profile.get("longitude")
    if not loc and (lat is None or lon is None):
        return None
    return {"location": loc or "", "lat": lat, "lon": lon}


async def _fetch_weather_map(profile: dict, timestamps: list[str]) -> dict[str, str]:
    """Returns {timestamp: conditions} for the given timestamps, or {} when unavailable."""
    geo = _location_args(profile)
    if not geo or not timestamps:
        return {}
    return await asyncio.to_thread(get_weather_conditions, dates=timestamps, **geo)


async def _fetch_weather_text(profile: dict, dates: list[str]) -> str:
    """Returns a formatted weather narrative for the given dates, or '' when unavailable."""
    conditions = await _fetch_weather_map(profile, dates)
    return format_weather_conditions(profile.get("location", ""), conditions)


async def _run_tp_tool(tool_context: ToolContext, tool_name: str, **node_input: Any) -> Any:
    """Resolves a TrainingPeaks MCP tool by name and invokes it."""
    tool = await get_tp_tool(tool_name)
    return await tool_context.run_node(tool, node_input=node_input or None)


async def _fetch_list(tool_context: ToolContext, tool_name: str, key: str, start: str, end: str) -> list[dict]:
    """Fetches a dated TP list payload (workouts / notes), returning [] when nothing is available."""
    raw = await _run_tp_tool(tool_context, tool_name, start_date=start, end_date=end)
    items = coerce_mcp_payload(raw).get(key) if raw else None
    return items if isinstance(items, list) else []


async def _fetch_workouts(tool_context: ToolContext, start: str, end: str) -> list[dict]:
    return await _fetch_list(tool_context, "tp_get_workouts", "workouts", start, end)


async def _fetch_notes(tool_context: ToolContext, start: str, end: str) -> list[dict]:
    return await _fetch_list(tool_context, "tp_list_notes", "notes", start, end)


def _result_or_none(result: Any, label: str) -> Any:
    """Unwraps a gather() result, logging and discarding exceptions."""
    if isinstance(result, Exception):
        logger.warning("Failed to fetch %s: %s", label, result)
        return None
    return result


async def _gather_labeled(fetches: dict[str, Any]) -> dict[str, Any]:
    """Runs labelled coroutines concurrently; failed ones map to None (and are logged)."""
    results = await asyncio.gather(*fetches.values(), return_exceptions=True)
    return {label: _result_or_none(r, label) for label, r in zip(fetches, results)}


# ==============================================================================
# 3. Skill Facades (1 Facade per Skill)
# ==============================================================================

# Workout & Bike Analysis (for workout-analysis & bike-workout-analysis skills) ---
RECOVERY_LOOKBACK_DAYS = 7
PLANNED_NOTES_MAX_CHARS = 800
_SERIES_KEYS = ("time", "HeartRate", "Speed", "Power", "Distance")


def _load_series(path: Any) -> Optional[list[dict]]:
    """Reads the time series tp_analyze_workout saved to `data_file` (MCP runs as a local subprocess)."""
    if not path:
        return None
    try:
        with open(str(path), encoding="utf-8") as f:
            points = json.load(f).get("data") or []
    except (OSError, ValueError, AttributeError) as e:
        logger.info("Time series unavailable (%s): %s", path, e)
        return None
    series = [{k: p[k] for k in _SERIES_KEYS if k in p} for p in points if isinstance(p, dict)]
    return series or None


def _planned_notes(meta: dict) -> str:
    """The workout's planned description (coach notes), capped for token efficiency."""
    notes = str(meta.get("description") or "").strip()
    if len(notes) > PLANNED_NOTES_MAX_CHARS:
        notes = notes[:PLANNED_NOTES_MAX_CHARS].rstrip() + "…"
    return notes


def _format_athlete_feedback(meta: dict) -> str:
    """RPE / feeling / comment recorded by the athlete in TrainingPeaks, or ''."""
    parts = []
    if meta.get("rpe") is not None:
        parts.append(f"RPE {meta['rpe']}/10")
    if meta.get("feeling") is not None:
        parts.append(f"Feeling {meta['feeling']}/10")
    calories = (meta.get("metrics") or {}).get("calories")
    if calories:
        parts.append(f"{calories} kcal")
    if meta.get("new_comment"):
        parts.append(f'Comment: "{meta["new_comment"]}"')
    return " | ".join(parts)


async def analyze_workout(
    tool_context: ToolContext,
    workout_id: Optional[str] = None,
    date_str: Optional[str] = None,
    sport: Optional[str] = None,
    include_weather: bool = True,
    include_recovery: bool = True,
) -> str:
    """Gets comprehensive physiological, telemetry, recovery, and environmental analysis for a workout.

    Args:
        workout_id: Specific workout ID to analyze. If omitted, automatically finds the completed workout for date_str.
        date_str: Target date in ISO format (YYYY-MM-DD or 'today'). Defaults to today if workout_id is not provided.
        sport: Optional 'run' or 'bike'. When resolving by date, prefer a completed workout of this sport.
        include_weather: Whether to fetch the hourly weather at the workout's start time. Defaults to True.
        include_recovery: Whether to include the morning recovery metrics (HRV, Sleep, RHR) before the workout. Defaults to True.
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()

    target_date = today_date
    if date_str and date_str.strip().lower() != "today":
        target_date = parse_date(date_str) or today_date
    target_iso = _iso(target_date)
    sport_hint = sport
    sport, title, start = "Workout", "", None
    other_sessions: list[dict] = []

    # 1. Resolve workout_id if not provided
    if not workout_id:
        try:
            workouts_list = await _fetch_workouts(tool_context, target_iso, target_iso)
        except Exception as e:
            logger.error("Failed to look up workout for %s: %s", target_iso, e)
            return f"Error: Failed to find workout for {target_iso}: {e}"

        completed = [w for w in workouts_list if is_workout_completed(w)]
        if not completed:
            if workouts_list:
                titles = ", ".join(
                    f"'{w.get('title') or w.get('sport', 'Workout')}'" for w in workouts_list
                )
                return f"No completed workout found for {target_iso}. Planned sessions found on calendar: {titles}."
            return f"No completed workouts found on {target_iso}."

        # Pick the day's key session (not simply the last one listed) and disclose the rest.
        target_workout, other_sessions = select_primary_workout(completed, sport_hint)
        workout_id = str(target_workout.get("id") or "")
        sport = target_workout.get("sport") or sport
        title = target_workout.get("title") or sport
        start = target_workout.get("start_time") or target_workout.get("date")

    if not workout_id:
        return "Error: No workout ID could be determined."

    try:
        # 2. Workout details (real date, sport, RPE) and telemetry, concurrently
        meta_raw, analysis_raw = await asyncio.gather(
            _run_tp_tool(tool_context, "tp_get_workout", workout_id=workout_id),
            _run_tp_tool(tool_context, "tp_analyze_workout", workout_id=workout_id),
            return_exceptions=True,
        )
        if isinstance(analysis_raw, Exception):
            return f"Error analyzing workout {workout_id}: {analysis_raw}"
        data = parse_mcp_response(analysis_raw)
        if not isinstance(data, dict) or not data:
            return f"No analysis data returned for workout {workout_id}."

        meta_payload = _result_or_none(meta_raw, "workout details")
        meta = coerce_mcp_payload(meta_payload) if meta_payload else {}
        if meta.get("isError"):
            meta = {}

        # The workout's own date drives the recovery window and the weather lookup.
        start = data.get("startTimestamp") or start or meta.get("date") or target_iso
        workout_date = parse_date(start) or target_date
        sport = meta.get("sport") or sport
        title = meta.get("title") or title or sport

        structured = meta.get("structured_workout")
        is_structured = has_structure(structured)

        # 3. Recovery (the days leading up to the workout), weather and, for builder
        #    workouts, the thresholds that turn %-targets into paces, concurrently
        extras: dict[str, Any] = {}
        if is_structured:
            extras["athlete settings"] = _run_tp_tool(tool_context, "tp_get_athlete_settings")
        if include_recovery:
            extras["recovery metrics"] = _run_tp_tool(
                tool_context, "tp_get_metrics",
                start_date=_iso(workout_date - timedelta(days=RECOVERY_LOOKBACK_DAYS)),
                end_date=_iso(workout_date),
            )
        if include_weather:
            extras["weather"] = _fetch_weather_text(profile, [str(start)])
        extra, series = await asyncio.gather(
            _gather_labeled(extras), asyncio.to_thread(_load_series, data.get("data_file"))
        )

        # 4. Planned vs executed: align laps to the builder steps; decoupling always skips the
        #    first minutes and, when aligned, the warm-up / cool-down steps.
        laps = data.get("lapData") if isinstance(data.get("lapData"), list) else []
        alignment, structure_section = None, ""
        if is_structured:
            thresholds = sport_thresholds(extra.get("athlete settings"), sport)
            alignment = align_laps(flatten_structure(structured), laps)
            structure_section = format_structured_execution(
                structured, laps, thresholds, series, sport, alignment
            )
        sections = [format_workout_analysis(
            data, title=title or None, sport=sport or None,
            include_laps=alignment is None,
            decoupling_override=session_decoupling(series, laps, sport, alignment),
        )]
        if other_sessions:
            sections.insert(0, format_other_sessions(other_sessions, target_iso))
        if structure_section:
            sections.append(structure_section)
        notes = _planned_notes(meta)
        if notes:
            sections.append(f"**Planned session notes:** {notes}")
        feedback = _format_athlete_feedback(meta)
        if feedback:
            sections.append(f"**Athlete feedback:** {feedback}")
        if extra.get("recovery metrics"):
            rec_formatted = format_recovery_metrics(extract_health_metrics(extra["recovery metrics"]))
            if rec_formatted:
                sections.append(
                    f"**Recovery context ({RECOVERY_LOOKBACK_DAYS} days to {_iso(workout_date)}):**\n{rec_formatted}"
                )
        if extra.get("weather"):
            sections.append(f"**Environmental & Weather Context:**\n{extra['weather']}")
        return "\n\n".join(sections)
    except Exception as e:
        logger.error("analyze_workout failed for %s: %s", workout_id, e)
        return f"Error: Failed to analyze workout {workout_id}: {e}"


analyze_workout_tool = FunctionTool(analyze_workout)


# Check-In Report (for check-in-report skill) ---
# PMC history window (CTL-at-session lookup for the detraining adjustment).
PROJECTION_LOOKBACK_DAYS = 90


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
    goal_label: Optional[str],
    profile: dict,
    all_workouts: list[dict],
    fitness_data: Optional[dict],
    settings_raw: Any,
    dated_metrics: Optional[dict],
    today_date: Any,
    refresh_cache: bool = False,
) -> dict:
    """Builds the evidence-based goal-race projection payload for compile_checkin_summary."""
    if not goal_label:
        return {"goal_label": None, "projection": None}
    fitness_data = fitness_data or {}
    runs = completed_goal_runs(
        all_workouts, today_date - timedelta(days=PROJECTION_WINDOW_DAYS), today_date
    )
    summaries = await _load_workout_summaries(
        tool_context, select_for_analysis(runs, goal_label), profile_user_id(profile),
        refresh=refresh_cache,
    )
    projection = project_race(
        goal_label=goal_label,
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
    return {"goal_label": goal_label, "projection": projection}


async def fetch_checkin_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh_analysis_cache: bool = False,
) -> str:
    """Fetches all data needed for a comprehensive weekly check-in report.

    Includes:
    - 14-day past completed workouts with run-time weather, plus pre-computed weekly totals
    - 7-day future scheduled workouts
    - 14-day recovery metrics (Sleep, HRV, RHR)
    - 14-day PMC fitness trends (CTL table, ATL/TSB load context, goal trajectory)
    - Projected goal-race time (today and race day) for the Firestore training_goal,
      from threshold laps, goal-pace segments, HR efficiency, durability, load
      and health readiness, with a 'Projection drivers' evidence table
    - Calendar notes (work stress, travel, illness)

    Args:
        start_date: Optional window start (YYYY-MM-DD). Defaults to 14 days ago.
        end_date: Optional window end (YYYY-MM-DD). Defaults to 7 days ahead.
        refresh_analysis_cache: Re-analyse key workouts instead of using cached summaries.
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."

    today_date = get_today_date()
    q_start = parse_date(start_date) or (today_date - timedelta(days=14))
    q_end = parse_date(end_date) or (today_date + timedelta(days=7))
    goal_label = resolve_goal_distance(profile.get("training_goal"))

    start_str, end_str = _iso(q_start), _iso(q_end)
    recovery_end_str = _iso(min(q_end, today_date))
    workouts_start = min(q_start, today_date - timedelta(days=PROJECTION_WINDOW_DAYS))
    metrics_start = min(q_start, today_date - timedelta(days=HEALTH_BASELINE_DAYS))
    history_start = min(q_start, today_date - timedelta(days=PROJECTION_LOOKBACK_DAYS))

    # Phase 1: gather calendar, notes, metrics, PMC and athlete thresholds.
    fetches = {
        "workouts": _fetch_workouts(tool_context, _iso(workouts_start), end_str),
        "calendar notes": _fetch_notes(tool_context, start_str, end_str),
        "recovery metrics": _run_tp_tool(
            tool_context, "tp_get_metrics", start_date=_iso(metrics_start), end_date=recovery_end_str,
        ),
        "fitness PMC": _run_tp_tool(
            tool_context, "tp_get_fitness", start_date=_iso(history_start), end_date=recovery_end_str,
        ),
    }
    if goal_label:
        fetches["athlete settings"] = _run_tp_tool(tool_context, "tp_get_athlete_settings")
    raw = await _gather_labeled(fetches)

    all_workouts = raw["workouts"] or []
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
    fitness_data = _summarize_fitness(raw["fitness PMC"], profile, today_date, window_start=q_start)
    weekly_totals = list(build_week_buckets(workouts_past, q_start, min(q_end, today_date)).values())

    # Phase 2: project the goal race (cache-first analyses) while fetching run-time weather.
    run_timestamps = [
        str(w.get("start_time") or w.get("date"))
        for w in workouts_past
        if (w.get("start_time") or w.get("date"))
    ]
    race_projection, weather_map = await asyncio.gather(
        _build_goal_projection(
            tool_context, goal_label, profile, all_workouts, fitness_data,
            raw.get("athlete settings"), dated_metrics, today_date,
            refresh_cache=refresh_analysis_cache,
        ),
        _fetch_weather_map(profile, run_timestamps),
    )

    return compile_checkin_summary(
        lookback_days=(today_date - q_start).days,
        lookahead_days=(q_end - today_date).days,
        workouts_past=workouts_past,
        workouts_future=workouts_future,
        metrics_data=metrics_data,
        fitness_data=fitness_data,
        notes_list=raw["calendar notes"],
        weather_map=weather_map,
        race_projection=race_projection,
        weekly_totals=weekly_totals,
    )


fetch_checkin_data_tool = FunctionTool(fetch_checkin_data)


# Schedule Audit (for schedule-audit skill) ---
async def fetch_schedule_audit_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weeks_forward: int = 4,
    weeks_back: int = 1,
) -> str:
    """Audits the runner's training schedule per ISO week: running volume, TSS, easy vs. quality
    split, cross-training, and calendar notes (travel, illness, work stress).

    Past weeks use completed values, so week-over-week growth and taper checks can include
    the prior week(s).

    Args:
        start_date: Optional audit start (YYYY-MM-DD). Defaults to `weeks_back` weeks before today.
        end_date: Optional audit end (YYYY-MM-DD). Defaults to `weeks_forward` weeks after today.
        weeks_forward: Weeks ahead to audit when end_date is omitted. Defaults to 4.
        weeks_back: Completed weeks before today to include when start_date is omitted. Defaults to 1.
    """
    today_date = get_today_date()
    q_start = parse_date(start_date) or (today_date - timedelta(weeks=max(0, weeks_back)))
    q_end = parse_date(end_date) or (today_date + timedelta(weeks=weeks_forward))
    start_str, end_str = _iso(q_start), _iso(q_end)

    raw = await _gather_labeled({
        "workouts": _fetch_workouts(tool_context, start_str, end_str),
        "calendar notes": _fetch_notes(tool_context, start_str, end_str),
    })

    weeks = build_week_buckets(raw["workouts"], q_start, q_end)
    add_notes_to_weeks(weeks, raw["calendar notes"])
    return format_schedule_audit_summary(list(weeks.values()))


fetch_schedule_audit_data_tool = FunctionTool(fetch_schedule_audit_data)


# Nutrition & Fueling Context (for nutrition-planner skill) ---
async def fetch_nutrition_context(
    tool_context: ToolContext,
    days_forward: int = 3,
) -> str:
    """Fetches runner biometrics, upcoming training demands and the forecast (temperature,
    feels-like, humidity, wind) for customized sports nutrition and hydration guidance.

    Args:
        days_forward: Days ahead to plan for. Defaults to 3.
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()
    end_date = today_date + timedelta(days=days_forward)
    forecast_dates = [_iso(today_date + timedelta(days=i)) for i in range(days_forward + 1)]

    upcoming, weather_str = await asyncio.gather(
        _fetch_workouts(tool_context, _iso(today_date), _iso(end_date)),
        _fetch_weather_text(profile, forecast_dates),
    )

    return format_nutrition_context_summary(
        profile=profile,
        upcoming_workouts=upcoming,
        weather_forecast=weather_str,
        days_forward=days_forward,
    )


fetch_nutrition_context_tool = FunctionTool(fetch_nutrition_context)


# Workout & Calendar Note Creation (for workout-creator skill) ---
async def _find_existing_workouts(
    tool_context: ToolContext,
    target_iso: str,
    sport: str,
) -> list[dict]:
    """Returns the planned workouts of the same sport on the target date."""
    try:
        workouts_list = await _fetch_workouts(tool_context, target_iso, target_iso)
    except Exception as e:
        logger.warning("Failed checking existing workouts for %s: %s", target_iso, e)
        return []
    sport_lower = sport.strip().lower()
    return [
        w for w in workouts_list
        if not is_workout_completed(w) and (w.get("sport") or "").strip().lower() == sport_lower
    ]


# Per-action differences between the create and update MCP tools.
_CREATE_SPEC = {"tool": "tp_create_workout", "date_key": "date_str", "duration_cast": int,
                "verb": "create", "gerund": "creating", "past": "created"}
_UPDATE_SPEC = {"tool": "tp_update_workout", "date_key": "date", "duration_cast": float,
                "verb": "update", "gerund": "updating", "past": "updated"}


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
        logger.error("Failed to %s workout (%s): %s", spec["verb"], date_str, e)
        return f"Error: Failed to {spec['verb']} workout: {e}"

    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return f"Error {spec['gerund']} workout: {data.get('message', 'Unknown error')}"

    resolved_id = workout_id or data.get("id") or data.get("workout_id")
    return json.dumps({
        "success": True,
        "action": spec["past"],
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
    """Creates a new planned workout or updates an existing one in TrainingPeaks.

    - `workout_id` given: updates that workout.
    - `create=True`: always creates a new workout (use when ADDING a session to a day).
    - Otherwise: looks for planned workouts of the SAME sport on `date_str`; none -> creates,
      exactly one -> updates it, several -> returns the candidates so you can pass `workout_id`.
      Workouts of other sports on that day are never touched.

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
        create: If True, creates a new workout even if one of the same sport exists that day.
    """
    target_date = parse_date(date_str)
    target_iso = _iso(target_date) if target_date else date_str[:10]

    target_workout_id = workout_id
    if not target_workout_id and not create:
        existing = await _find_existing_workouts(tool_context, target_iso, sport)
        if len(existing) > 1:
            return json.dumps({
                "success": False,
                "action": "needs_workout_id",
                "message": (
                    f"Several planned {sport} workouts exist on {target_iso}. Ask the runner which one "
                    "to change and call again with workout_id, or pass create=True to add a new one."
                ),
                "candidates": [
                    {"workout_id": str(w.get("id") or ""), "title": w.get("title")} for w in existing
                ],
            })
        if existing:
            target_workout_id = str(existing[0].get("id") or "") or None

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
    """Creates a calendar note in TrainingPeaks (travel, illness, rest days, life stress)."""
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

    user_id = profile_user_id(profile)
    if not user_id:
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


async def get_weather(tool_context: ToolContext, dates: list[str], location: Optional[str] = None) -> str:
    """Weather (daily + hourly) for ISO dates/timestamps at the runner's home location,
    or at `location` (e.g. a travel or race destination). Forecasts reach 16 days ahead.

    Args:
        dates: ISO dates (YYYY-MM-DD) or timestamps (YYYY-MM-DDTHH:MM).
        location: Optional city name; defaults to the runner's home location.
    """
    profile = tool_context.state.get("user_profile") or {}
    geo = {"location": location, "lat": None, "lon": None} if location else _location_args(profile)
    if not geo:
        return "No location on file; ask the runner where they will be running."
    return await asyncio.to_thread(get_weather_for_dates, dates=dates, **geo)


get_weather_tool = FunctionTool(get_weather)


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
