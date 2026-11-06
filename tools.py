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

from .integrations import firestore, open_meteo, package_paths
from .integrations.trainingpeaks import tp_calls
from .utils import (
    ANALYSIS_SCHEMA_VERSION,
    AUDIT_REPORT_STATE_KEY,
    CHECKIN_REPORT_STATE_KEY,
    PROJECTION_WINDOW_DAYS,
    TREND_REPORT_STATE_KEY,
    audit_report_data,
    checkin_report_data,
    coerce_mcp_payload,
    compile_checkin_summary,
    current_goal,
    evaluate_goal_trajectory,
    extract_health_metrics,
    extract_health_metrics_dated,
    extract_thresholds,
    format_goal_plan,
    format_nutrition_context_summary,
    format_projection_vs_north_star,
    format_recovery_metrics,
    format_workout_goal_context,
    format_schedule_audit_summary,
    format_other_sessions,
    format_workout_analysis,
    get_today_date,
    is_plan,
    is_workout_completed,
    race_duration_s,
    race_result_update,
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
    trend_report_data,
)
from .utils import completed_runs as completed_goal_runs
from .utils.classification import NON_TRAINING_SPORTS, RUN_SPORTS
from .utils.date_helpers import ISO_DATE_FMT
from .utils.load_capacity import (
    add_load_ratio,
    capacity_outlook,
    format_levels_table,
    format_outlook,
    ratio_vs_next_hrv,
    volume_levels,
)
from .utils.long_run import annotate_long_runs, format_goal_context, format_trend_long_run_target
from .utils.pacing import analyse_pacing, extract_hr_zones, format_pacing_details, format_pacing_tables
from .utils.goals import goal_race_dates
from .utils.race_readiness import (
    HEALTH_BASELINE_DAYS,
    health_readiness,
    is_complete_summary,
    recent_hard_effort,
)
from .utils.status_summary import format_fitness_pmc
from .utils.training_log import WorkoutBundle, build_training_record, workout_context
from .utils.trends import (
    LT_FIT_WEEKS,
    checkin_lt_paces,
    format_patterns,
    format_progress_table,
    format_weekly_table,
    key_run_label,
    progress_summary,
    training_patterns,
    weekly_rows,
)
from .utils.weekly import add_notes_to_weeks, annotate_week_progression, build_week_buckets
from .callbacks import CHECKIN_TABLES_STATE_KEY, TREND_TABLES_STATE_KEY
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
# Skills toolset
# ==============================================================================
SKILL_DIRS = (
    ("nutrition_planner", "nutrition-planner"),
    ("check_in_report", "check-in-report"),
    ("trend_analysis", "trend-analysis"),
    ("workout_analysis", "workout-analysis"),
    ("workout_analysis", "bike-workout-analysis"),
    ("schedule_audit", "schedule-audit"),
    ("workout_creator", "workout-creator"),
)

# Routing (when to load which skill, parallel data call, write-tool rules) lives in the coach
# instruction's SKILL ROUTING section; this line only introduces the catalog.
_SKILL_INSTRUCTION = "Available skills (load with `load_skill` per SKILL ROUTING; follow the loaded protocol exactly):"


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
    skills=[load_skill_from_dir(os.path.join(package_paths.PACKAGE_DIR, "features", feat, name)) for feat, name in SKILL_DIRS],
)


# ==============================================================================
# Shared helpers
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


def _geo_for_position(profile: dict, position: Optional[dict] = None) -> Optional[dict[str, Any]]:
    """Returns geo kwargs preferring GPS start coordinates when available, else profile home."""
    if isinstance(position, dict):
        lat, lon = position.get("lat"), position.get("lon")
        if type(lat) in (int, float) and type(lon) in (int, float):
            return {"location": f"{lat:.2f}, {lon:.2f}", "lat": float(lat), "lon": float(lon)}
    return _location_args(profile)


async def _fetch_weather_map(
    profile: dict,
    timestamps: list[str],
    *,
    position: Optional[dict] = None,
    utc: bool = False,
) -> dict[str, str]:
    """Returns {timestamp: conditions} for the given timestamps, or {} when unavailable."""
    geo = _geo_for_position(profile, position)
    if not geo or not timestamps:
        return {}
    return await asyncio.to_thread(open_meteo.get_weather_conditions, dates=timestamps, utc=utc, **geo)


async def _fetch_weather_text(
    profile: dict,
    dates: list[str],
    *,
    position: Optional[dict] = None,
    utc: bool = False,
) -> str:
    """Returns a formatted weather narrative for the given dates, or '' when unavailable."""
    geo = _geo_for_position(profile, position)
    if not geo or not dates:
        return ""
    conditions = await asyncio.to_thread(open_meteo.get_weather_conditions, dates=dates, utc=utc, **geo)
    label = geo["location"] if position else profile.get("location", "")
    return open_meteo.format_weather_conditions(label, conditions)


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
# Skill facades
# ==============================================================================

# Workout analysis ---
RECOVERY_LOOKBACK_DAYS = 7
NO_WORKOUT_LOOKBACK_DAYS = 7
PLANNED_NOTES_MAX_CHARS = 800
_SERIES_KEYS = ("time", "HeartRate", "Speed", "Power", "Distance")


def _extract_start_position(points: list) -> Optional[dict]:
    """First valid GPS fix from tp_analyze_workout telemetry points, or None."""
    for p in points:
        if not isinstance(p, dict):
            continue
        lat, lon = p.get("PositionLat"), p.get("PositionLong")
        if type(lat) in (int, float) and type(lon) in (int, float):
            if (-90.0 <= lat <= 90.0) and (-180.0 <= lon <= 180.0) and not (lat == 0.0 and lon == 0.0):
                return {"lat": round(float(lat), 5), "lon": round(float(lon), 5)}
    return None


def _load_analysis_file(path: Any) -> tuple[Optional[list[dict]], Optional[dict]]:
    """Reads the time series and first GPS fix tp_analyze_workout saved to `data_file`."""
    if not path:
        return None, None
    try:
        with open(str(path), encoding="utf-8") as f:
            points = json.load(f).get("data") or []
    except (OSError, ValueError, AttributeError) as e:
        logger.info("Time series unavailable (%s): %s", path, e)
        return None, None
    series = [{k: p[k] for k in _SERIES_KEYS if k in p} for p in points if isinstance(p, dict)]
    return (series or None), _extract_start_position(points)


def _load_series(path: Any) -> Optional[list[dict]]:
    return _load_analysis_file(path)[0]


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
    """Physiological, telemetry, recovery and weather analysis of one completed workout.

    Args:
        workout_id: Workout to analyze; omit to use the completed workout on date_str.
        date_str: YYYY-MM-DD or 'today' (default).
        sport: Optional 'run' or 'bike' to prefer when resolving by date.
        include_weather: Hourly weather at the start time (default True).
        include_recovery: Morning HRV, sleep and RHR (default True).
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

    from .utils.workouts import format_no_workout
    # Resolve the workout from the date (including a 7-day lookback to cite the latest completed session if today has none).
    if not workout_id:
        try:
            recent = await tp_calls.fetch_workouts(
                tool_context, _iso(target_date - timedelta(days=NO_WORKOUT_LOOKBACK_DAYS)), target_iso
            )
        except Exception as e:
            logger.error("Failed to look up workout for %s: %s", target_iso, e)
            return f"Error: Failed to find workout for {target_iso}: {e}"

        workouts_list = [
            w for w in recent if parse_date(w.get("date") or w.get("start_time")) == target_date
        ]
        completed = [w for w in workouts_list if is_workout_completed(w)]
        if not completed:
            return format_no_workout(target_iso, workouts_list, recent)

        # Pick the day's key session and list the others.
        target_workout, other_sessions = select_primary_workout(completed, sport_hint)
        workout_id = str(target_workout.get("id") or "")
        sport = target_workout.get("sport") or sport
        title = target_workout.get("title") or sport
        start = target_workout.get("start_time") or target_workout.get("date")

    if not workout_id:
        return "Error: No workout ID could be determined."

    try:
        # Workout details and telemetry.
        meta_raw, analysis_raw = await asyncio.gather(
            tp_calls.run_tp_tool(tool_context, "tp_get_workout", workout_id=workout_id),
            tp_calls.run_tp_tool(tool_context, "tp_analyze_workout", workout_id=workout_id),
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
        start_is_utc = bool(data.get("startTimestamp"))
        start = data.get("startTimestamp") or start or meta.get("date") or target_iso
        workout_date = parse_date(meta.get("date") or start) or target_date
        sport = meta.get("sport") or sport
        title = meta.get("title") or title or sport

        structured = meta.get("structured_workout")
        is_structured = has_structure(structured)

        series, start_pos = await asyncio.to_thread(_load_analysis_file, data.get("data_file"))

        # Thresholds, recovery and PMC are always fetched: the training-log record needs them
        # regardless of what this reply displays.
        extras: dict[str, Any] = {
            "athlete settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
            "recovery metrics": tp_calls.run_tp_tool(
                tool_context, "tp_get_metrics",
                start_date=_iso(workout_date - timedelta(days=RECOVERY_LOOKBACK_DAYS)),
                end_date=_iso(workout_date),
            ),
            "fitness PMC": tp_calls.run_tp_tool(
                tool_context, "tp_get_fitness", start_date=_iso(workout_date), end_date=_iso(workout_date),
            ),
        }
        if include_weather:
            extras["weather"] = _fetch_weather_text(
                profile, [str(start)], position=start_pos, utc=start_is_utc,
            )
        extra = await _gather_labeled(extras)

        # Planned vs executed: align laps to the structured steps.
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
        if include_recovery and extra.get("recovery metrics"):
            rec_formatted = format_recovery_metrics(extract_health_metrics(extra["recovery metrics"]))
            if rec_formatted:
                sections.append(
                    f"**Recovery context ({RECOVERY_LOOKBACK_DAYS} days to {_iso(workout_date)}):**\n{rec_formatted}"
                )
        if extra.get("weather"):
            sections.append(f"**Environmental & Weather Context:**\n{extra['weather']}")
        goal_context = await _goal_plan_context(
            tool_context, profile, workout_date, workout_id, sport, meta, data
        )
        if goal_context:
            sections.append(goal_context)
        await record_workout(
            profile, meta, data, series,
            thresholds=extract_thresholds(extra.get("athlete settings")),
            daily_pmc=(coerce_mcp_payload(extra["fitness PMC"]).get("daily_data") if extra.get("fitness PMC") else None),
            dated_metrics=(extract_health_metrics_dated(extra["recovery metrics"])
                           if extra.get("recovery metrics") else None),
            start=str(start),
            start_position=start_pos,
            start_is_utc=start_is_utc,
        )
        return "\n\n".join(sections)
    except Exception as e:
        logger.error("analyze_workout failed for %s: %s", workout_id, e)
        return f"Error: Failed to analyze workout {workout_id}: {e}"


async def _goal_plan_context(
    tool_context: ToolContext, profile: dict, workout_date: Any, workout_id: str, sport: Any,
    meta: dict, data: dict,
) -> str:
    """Goal-plan line for a workout analysis; saves the result when this is a sub-goal race.

    The result logic lives in utils.goals (pure); this only persists the returned update.
    """
    if not is_plan(profile):
        return ""
    duration_s = race_duration_s(meta, data)
    update = race_result_update(profile, workout_date, duration_s, workout_id, sport=sport)
    saved = False
    if update:
        user_id = profile_user_id(profile)
        try:
            if not user_id:
                raise ValueError("no runner name in profile")
            await firestore.update_user_profile(user_id, update)
            tool_context.state["user_profile"] = {**profile, **update}
            saved = True
        except Exception as e:
            logger.error("Failed to save sub-goal race result for %s: %s", user_id, e)
    return format_workout_goal_context(profile, workout_date, duration_s, saved)


analyze_workout_tool = FunctionTool(analyze_workout)


# Check-in report ---
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
        "trajectory_info": evaluate_goal_trajectory(
            current_goal(profile, parse_date(today_date)), bounds["ctl_end"], today_date, daily_pmc=history
        ),
    }


async def _cache_read(user_id: Optional[str], workout_id: str) -> Optional[dict]:
    """Returns a valid cached workout summary, or None (cache miss / unavailable)."""
    if not user_id or not workout_id:
        return None
    try:
        cached = await firestore.get_cached_workout_analysis(user_id, workout_id)
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
        await firestore.save_workout_analysis(user_id, workout_id, summary)
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
        *(tp_calls.run_tp_tool(tool_context, "tp_analyze_workout", workout_id=ids[i]) for i in misses),
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
    goal = current_goal(profile, today_date)
    projection = project_race(
        goal_label=goal_label,
        goal_minutes=parse_target_time_minutes(goal["training_goal"]),
        runs=runs,
        summaries=summaries,
        thresholds=extract_thresholds(settings_raw),
        daily_pmc=fitness_data.get("history"),
        fitness=fitness_data,
        trajectory_info=fitness_data.get("trajectory_info"),
        dated_metrics=dated_metrics,
        today=today_date,
        block_start=goal["goal_set_date"],
        race_dates=goal_race_dates(profile),
    )
    return {"goal_label": goal_label, "projection": projection}


async def fetch_checkin_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    refresh_analysis_cache: bool = False,
) -> str:
    """Check-in data, last 14 days + next 7: workouts, weekly totals, recovery, PMC, goal-race
    projection and calendar notes.

    Args:
        start_date: YYYY-MM-DD; default 14 days ago.
        end_date: YYYY-MM-DD; default 7 days ahead.
        refresh_analysis_cache: Re-analyse key workouts instead of using cached summaries.
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."

    today_date = get_today_date()
    q_start = parse_date(start_date) or (today_date - timedelta(days=14))
    q_end = parse_date(end_date) or (today_date + timedelta(days=7))
    goal_label = resolve_goal_distance(current_goal(profile, today_date)["training_goal"])

    start_str, end_str = _iso(q_start), _iso(q_end)
    recovery_end_str = _iso(min(q_end, today_date))
    workouts_start = min(q_start, today_date - timedelta(days=PROJECTION_WINDOW_DAYS))
    metrics_start = min(q_start, today_date - timedelta(days=HEALTH_BASELINE_DAYS))
    history_start = min(q_start, today_date - timedelta(days=PROJECTION_LOOKBACK_DAYS))

    # Phase 1: gather calendar, notes, metrics, PMC and athlete thresholds.
    fetches = {
        "workouts": tp_calls.fetch_workouts(tool_context, _iso(workouts_start), end_str),
        "calendar notes": tp_calls.fetch_notes(tool_context, start_str, end_str),
        "recovery metrics": tp_calls.run_tp_tool(
            tool_context, "tp_get_metrics", start_date=_iso(metrics_start), end_date=recovery_end_str,
        ),
        "fitness PMC": tp_calls.run_tp_tool(
            tool_context, "tp_get_fitness", start_date=_iso(history_start), end_date=recovery_end_str,
        ),
        # Athlete settings: LTHR / HR zones for LT1/LT2, thresholds for the goal projection.
        "athlete settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
    }
    user_id = profile_user_id(profile)
    if user_id:
        # Training log (laps + start_position) for LT1/LT2 fits and per-workout weather; no gap-fill here.
        fetches["training records"] = firestore.list_training_records(
            user_id, _iso(min(q_start, today_date - timedelta(weeks=2 * LT_FIT_WEEKS))), _iso(today_date)
        )
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
    window_end = min(q_end, today_date)
    # Weekly totals cover whole ISO weeks: a window starting mid-week would otherwise clip the first
    # week (undercounted km, wrongly flagged). Workouts are fetched from >= workouts_start, so the
    # Monday is only used when its workouts are actually loaded.
    week_start = q_start - timedelta(days=q_start.weekday())
    if week_start < workouts_start:
        week_start = q_start
    weekly_source, _ = partition_workouts_by_date(
        [w for w in all_workouts
         if (parse_date(w.get("date") or w.get("start_time")) or q_start) >= week_start],
        today_date,
    )
    weekly_totals = annotate_week_progression(
        list(build_week_buckets(weekly_source, week_start, window_end).values()), week_start, window_end
    )
    fit = fitness_data or {}
    recent_effort = recent_hard_effort(all_workouts, today_date, fit.get("history"), goal_race_dates(profile))
    recovery_baseline = health_readiness(
        dated_metrics, today_date, None, fit.get("tsb_end"), fit.get("atl_end"), fit.get("ctl_end"),
        recent_effort,
    )["detail"] if dated_metrics else None

    # Phase 2: project the goal race (cache-first analyses) while fetching run-time weather.
    race_projection, weather_map = await asyncio.gather(
        _build_goal_projection(
            tool_context, goal_label, profile, all_workouts, fitness_data,
            raw.get("athlete settings"), dated_metrics, today_date,
            refresh_cache=refresh_analysis_cache,
        ),
        _fetch_checkin_weather_map(profile, workouts_past, raw.get("training records")),
    )

    # LT1 (top of TP HR zone 2) / LT2 (LTHR) paces, same fit as the trend report.
    zones = extract_hr_zones(raw["athlete settings"])
    lt = checkin_lt_paces(
        raw.get("training records") or [], today_date,
        extract_thresholds(raw["athlete settings"]).get("lthr"),
        zones[1]["max"] if len(zones) >= 2 else None,
    )

    # Rendered once: the model reasons over it here, and the report gets it spliced in verbatim.
    if fitness_data is not None:
        tool_context.state[CHECKIN_TABLES_STATE_KEY] = format_fitness_pmc(fitness_data, race_projection, lt)
    tool_context.state[CHECKIN_REPORT_STATE_KEY] = checkin_report_data(
        q_start, q_end, fitness_data, race_projection, weekly_totals, dated_metrics, lt_paces=lt,
    )

    summary = compile_checkin_summary(
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
        recovery_baseline=recovery_baseline,
        lt_paces=lt,
    )
    north_star_progress = _north_star_progress(profile, race_projection, today_date)
    return f"{summary}\n\n{north_star_progress}" if north_star_progress else summary


def _north_star_progress(profile: dict, race_projection: Optional[dict], today_date: Any) -> str:
    """'North Star Progress' check-in section (goal plans only; reads saved results, never fills them)."""
    plan = format_goal_plan(profile, today_date)
    if not plan:
        return ""
    lines = ["### North Star Progress", plan]
    projection_line = format_projection_vs_north_star(profile, race_projection, today_date)
    if projection_line:
        lines.append(projection_line)
    return "\n".join(lines)


fetch_checkin_data_tool = FunctionTool(fetch_checkin_data)


# Schedule audit ---
async def fetch_schedule_audit_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weeks_forward: int = 4,
    weeks_back: int = 1,
) -> str:
    """Per-ISO-week schedule audit: volume, TSS, easy/quality split, cross-training, calendar notes,
    goal context and long runs vs target. Past weeks use completed values.

    Args:
        start_date: YYYY-MM-DD; default weeks_back weeks ago.
        end_date: YYYY-MM-DD; default weeks_forward weeks ahead.
        weeks_forward: Weeks ahead when end_date is omitted (default 4).
        weeks_back: Completed weeks to include when start_date is omitted (default 1).
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()
    q_start = parse_date(start_date) or (today_date - timedelta(weeks=max(0, weeks_back)))
    q_end = parse_date(end_date) or (today_date + timedelta(weeks=weeks_forward))
    start_str, end_str = _iso(q_start), _iso(q_end)

    raw = await _gather_labeled({
        "workouts": tp_calls.fetch_workouts(tool_context, start_str, end_str),
        "calendar notes": tp_calls.fetch_notes(tool_context, start_str, end_str),
        "fitness PMC": tp_calls.run_tp_tool(tool_context, "tp_get_fitness",
                                    start_date=_iso(today_date - timedelta(days=7)), end_date=_iso(today_date)),
    })

    weeks = build_week_buckets(raw["workouts"], q_start, q_end)
    add_notes_to_weeks(weeks, raw["calendar notes"])
    week_list = annotate_long_runs(list(weeks.values()), profile)
    tool_context.state[AUDIT_REPORT_STATE_KEY] = audit_report_data(q_start, q_end, week_list)
    daily = coerce_mcp_payload(raw["fitness PMC"]).get("daily_data") or [] if raw["fitness PMC"] else []
    ctl = next((d.get("ctl") for d in reversed(daily) if d.get("ctl") is not None), None)
    return format_schedule_audit_summary(week_list, goal_context=format_goal_context(profile, today_date, ctl))


fetch_schedule_audit_data_tool = FunctionTool(fetch_schedule_audit_data)


# Nutrition context ---
async def fetch_nutrition_context(
    tool_context: ToolContext,
    days_forward: int = 3,
) -> str:
    """Runner biometrics, upcoming training and the weather forecast for fueling and hydration guidance.

    Args:
        days_forward: Days ahead to plan (default 3).
    """
    profile = tool_context.state.get("user_profile") or {}
    today_date = get_today_date()
    end_date = today_date + timedelta(days=days_forward)
    forecast_dates = [_iso(today_date + timedelta(days=i)) for i in range(days_forward + 1)]

    upcoming, weather_str = await asyncio.gather(
        tp_calls.fetch_workouts(tool_context, _iso(today_date), _iso(end_date)),
        _fetch_weather_text(profile, forecast_dates),
    )

    return format_nutrition_context_summary(
        profile=profile,
        goal=current_goal(profile, today_date),
        upcoming_workouts=upcoming,
        weather_forecast=weather_str,
        days_forward=days_forward,
    )


fetch_nutrition_context_tool = FunctionTool(fetch_nutrition_context)


# Workout and note creation ---
async def _find_existing_workouts(
    tool_context: ToolContext,
    target_iso: str,
    sport: str,
) -> list[dict]:
    """Returns the planned workouts of the same sport on the target date."""
    try:
        workouts_list = await tp_calls.fetch_workouts(tool_context, target_iso, target_iso)
    except Exception as e:
        logger.warning("Failed checking existing workouts for %s: %s", target_iso, e)
        return []
    sport_lower = sport.strip().lower()
    return [
        w for w in workouts_list
        if not is_workout_completed(w) and (w.get("sport") or "").strip().lower() == sport_lower
    ]


# Per-action differences between the create and update MCP tools.
_CREATE_SPEC = {"tool": "tp_create_workout", "date_key": "date", "duration_cast": int,
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
        result = await tp_calls.run_tp_tool(tool_context, spec["tool"], **node_input)
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
        date_str: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.
        sport: 'Run' (default), 'Bike', 'Swim', 'Strength', 'Walk', 'Crosstrain' or 'Race'.
        title: e.g. 'Threshold Intervals: 5x1km'.
        duration_minutes: Planned duration.
        distance_km: Planned distance.
        tss_planned: Planned TSS.
        description: Coaching instructions (warm-up, main set, cool-down, pacing cues).
        structure: Interval structure (dict or JSON string).
        workout_id: Workout to update.
        create: Always create a new workout.
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
        result = await tp_calls.run_tp_tool(tool_context, "tp_create_note", **node_input)
    except Exception as e:
        logger.error("Failed to create calendar note on %s: %s", date, e)
        return f"Error: Failed to create calendar note: {e}"

    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return f"Error creating note: {data.get('message', 'Unknown error')}"
    return json.dumps(data) if data else "Success: Calendar note created."


create_note_tool = FunctionTool(create_note)


# ==============================================================================
# Training log (written by analyze_workout and the trend facade's gap-fill)
# ==============================================================================
GAPFILL_CONCURRENCY = 2         # TP's analysis API rate-limits (429) bursts


async def _fetch_checkin_weather_map(
    profile: dict,
    workouts_past: list[dict],
    training_records: Optional[list[dict]],
) -> dict[str, str]:
    """Run-time weather keyed by workout start_time, grouped by recorded GPS start position."""
    pos_by_id: dict[str, dict] = {}
    for rec in training_records or []:
        if not isinstance(rec, dict):
            continue
        pos = rec.get("start_position")
        if isinstance(pos, dict) and type(pos.get("lat")) in (int, float) and type(pos.get("lon")) in (int, float):
            pos_by_id[str(rec.get("workout_id"))] = pos

    buckets: dict[Optional[tuple[float, float]], list[str]] = {}
    for w in workouts_past:
        ts = w.get("start_time")
        if not ts:
            continue
        pos = pos_by_id.get(str(w.get("id")))
        key = (round(float(pos["lat"]), 2), round(float(pos["lon"]), 2)) if pos else None
        buckets.setdefault(key, []).append(str(ts))

    if not buckets:
        return {}
    maps = await asyncio.gather(*(
        _fetch_weather_map(
            profile, timestamps,
            position=({"lat": key[0], "lon": key[1]} if key else None),
        )
        for key, timestamps in buckets.items()
    ))
    merged: dict[str, str] = {}
    for m in maps:
        if isinstance(m, dict):
            merged.update(m)
    return merged


def _weather_at(
    profile: dict,
    start: str,
    *,
    position: Optional[dict] = None,
    utc: bool = False,
) -> Optional[dict]:
    """Structured conditions at the run's start (blocking: geocoding + HTTP; call in a thread)."""
    lat = position.get("lat") if isinstance(position, dict) else None
    lon = position.get("lon") if isinstance(position, dict) else None
    if type(lat) not in (int, float) or type(lon) not in (int, float):
        lat, lon = profile.get("latitude"), profile.get("longitude")
        if (lat is None or lon is None) and profile.get("location"):
            lat, lon = open_meteo.geocode_location(profile["location"]) or (None, None)
    return open_meteo.get_conditions_at(lat, lon, start, utc=utc) if lat is not None and lon is not None else None


async def record_workout(
    profile: dict, meta: dict, analysis: Optional[dict], series: Optional[list[dict]], *,
    thresholds: dict, daily_pmc: Optional[list[dict]], dated_metrics: Optional[dict], start: Optional[str],
    start_position: Optional[dict] = None, start_is_utc: bool = False,
) -> Optional[dict]:
    """Builds and saves the training-log record for one workout. Best effort: never raises.

    The single write path for the training log; analyze_workout and gap-fill both call it.
    """
    try:
        user_id = profile_user_id(profile)
        if not user_id or not meta:
            return None
        weather = None
        if start and str(meta.get("sport") or "").lower() in RUN_SPORTS:
            weather = await asyncio.to_thread(
                _weather_at, profile, start, position=start_position, utc=start_is_utc,
            )
        bundle = WorkoutBundle(
            meta=meta, analysis=analysis, series=series, thresholds=thresholds, weather=weather,
            context=workout_context(parse_date(meta.get("date")), daily_pmc, dated_metrics),
            start_position=start_position,
        )
        record = build_training_record(bundle, datetime.now())
        if record:
            await firestore.save_training_record(user_id, record["workout_id"], record)
        return record
    except Exception as e:
        logger.warning("Training-log record failed for workout %s: %s", (meta or {}).get("id"), e)
        return None


async def _gapfill_one(
    tool_context: ToolContext, sem: asyncio.Semaphore, profile: dict, workout: dict, **context: Any
) -> Optional[dict]:
    """Fetches one unrecorded workout from TP and records it via record_workout."""
    async with sem:
        wid = str(workout.get("id"))
        is_run = str(workout.get("sport") or "").lower() in RUN_SPORTS
        fetches = {"meta": tp_calls.run_tp_tool(tool_context, "tp_get_workout", workout_id=wid)}
        if is_run:
            fetches["analysis"] = tp_calls.run_tp_tool(tool_context, "tp_analyze_workout", workout_id=wid)
        raw = await _gather_labeled(fetches)
        meta = coerce_mcp_payload(raw["meta"]) if raw["meta"] else {}
        analysis = coerce_mcp_payload(raw["analysis"]) if raw.get("analysis") else None
        if meta.get("isError") or (analysis or {}).get("isError"):
            return None
        series, start_pos = (
            await asyncio.to_thread(_load_analysis_file, analysis.get("data_file"))
            if analysis else (None, None)
        )
        start_is_utc = bool((analysis or {}).get("startTimestamp"))
        start = (analysis or {}).get("startTimestamp") or workout.get("start_time")
        return await record_workout(
            profile, meta, analysis, series,
            start=start, start_position=start_pos, start_is_utc=start_is_utc, **context,
        )


# ==============================================================================
# Trend analysis facade
# ==============================================================================
TREND_MIN_WEEKS, TREND_MAX_WEEKS = 6, 52


async def fetch_trend_data(tool_context: ToolContext, weeks: int = 26) -> str:
    """Long-horizon training-log trends: progress, weekly load capacity, pacing and training patterns.

    Args:
        weeks: Weeks to analyse (6-52, default 26).
    """
    profile = tool_context.state.get("user_profile")
    if not profile:
        return "Error: User profile not found in state."
    user_id = profile_user_id(profile)
    if not user_id:
        return "Error: Name not found in profile."

    weeks = max(TREND_MIN_WEEKS, min(TREND_MAX_WEEKS, int(weeks or 26)))
    today = get_today_date()
    start = today - timedelta(weeks=weeks)
    start = start - timedelta(days=start.weekday())          # whole ISO weeks
    health_start = start - timedelta(days=HEALTH_BASELINE_DAYS)

    raw = await _gather_labeled({
        "workouts": tp_calls.fetch_workouts_range(tool_context, start, today),
        "records": firestore.list_training_records(user_id, _iso(start), _iso(today)),
        "fitness PMC": tp_calls.run_tp_tool(tool_context, "tp_get_fitness", start_date=_iso(start), end_date=_iso(today)),
        "health": tp_calls.fetch_metrics_range(tool_context, health_start, today),
        "athlete settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
    })
    if raw["records"] is None:
        return "Error: Could not read the training log from Firestore; try again later."
    records = raw["records"]
    daily_pmc = coerce_mcp_payload(raw["fitness PMC"]).get("daily_data") or [] if raw["fitness PMC"] else []
    dated_metrics = raw["health"] or {}
    thresholds = extract_thresholds(raw["athlete settings"])

    # Gap-fill: completed workouts without a record go through the same write path as analyze_workout.
    known = {r.get("workout_id") for r in records}
    missing = sorted((
        w for w in raw["workouts"] or []
        if is_workout_completed(w) and (w.get("sport") or "") not in NON_TRAINING_SPORTS
        and str(w.get("id")) not in known
    ), key=lambda w: str(w.get("date") or ""), reverse=True)    # newest first: recent weeks matter most
    sem = asyncio.Semaphore(GAPFILL_CONCURRENCY)
    filled = await asyncio.gather(*(
        _gapfill_one(tool_context, sem, profile, w, thresholds=thresholds,
                     daily_pmc=daily_pmc, dated_metrics=dated_metrics)
        for w in missing
    ))
    new = [r for r in filled if r]
    records = sorted(records + new, key=lambda r: (r.get("date") or "", r.get("workout_id") or ""))
    unrecorded = [str(w.get("date") or "") for w, r in zip(missing, filled) if not r]

    goal_label = resolve_goal_distance(current_goal(profile, today)["training_goal"])
    zones = extract_hr_zones(raw["athlete settings"])
    lthr = thresholds.get("lthr")
    lt1_hr = zones[1]["max"] if len(zones) >= 2 else None          # LT1 = top of TP HR zone 2
    rows = add_load_ratio(weekly_rows(records, daily_pmc, dated_metrics, start, today, unrecorded,
                                      goal_label=goal_label, lthr=lthr, lt1_hr=lt1_hr))
    progress = progress_summary(rows, goal_label)
    levels = volume_levels(rows)
    outlook = capacity_outlook(rows, levels)
    rho, n_pairs = ratio_vs_next_hrv(rows)
    pacing = analyse_pacing(records, thresholds, zones, today)
    patterns = training_patterns(rows)

    progress_table = format_progress_table(progress)
    if progress_table and (pacing.get("lthr_check") or {}).get("status") == "unconfirmed":
        progress_table += ("\n\n_Pace @ LT2 relies on a TrainingPeaks LTHR that the data has not confirmed "
                           "(see the LTHR check)._")
    tables = "\n\n".join(t for t in (
        progress_table, format_levels_table(levels), format_pacing_tables(pacing)
    ) if t)
    tool_context.state[TREND_TABLES_STATE_KEY] = tables
    tool_context.state[TREND_REPORT_STATE_KEY] = trend_report_data(
        start, today, rows, progress, levels, outlook, key_run_label=key_run_label(goal_label)
    )

    runs = sum(1 for r in records if str(r.get("sport") or "").lower() in RUN_SPORTS)
    with_laps = sum(1 for r in records if r.get("laps"))
    comments = [c for r in rows for c in r["comments"]]
    easy = pacing.get("easy")
    easy_pace_s = (easy["fast_s"] + easy["slow_s"]) / 2 if easy else None
    long_run_line = format_trend_long_run_target(profile, today, rows, easy_pace_s)
    capacity = format_outlook(outlook, rho, n_pairs) + (f"\n\n{long_run_line}" if long_run_line else "")
    sections = [
        f"## Trend data: {_iso(start)} to {_iso(today)} ({weeks} weeks)",
        f"Coverage: {len(records)} workouts in the training log ({runs} runs, {with_laps} with lap data); "
        f"{len(new)} added by gap-fill now, {len(unrecorded)} could not be recorded now (no data, still syncing, "
        "or a TrainingPeaks error such as a rate limit; retried on the next call). Weeks with unrecorded "
        "workouts are marked and excluded from progress, capacity and pattern conclusions.",
        tables,
        "### Weekly rows\n" + format_weekly_table(rows),
        "### Load capacity\n" + capacity,
        "### Pacing\n" + format_pacing_details(pacing),
        "### Training patterns\n" + format_patterns(patterns),
    ]
    if comments:
        sections.append("### Athlete comments (raw)\n" + "\n".join(f"- {c}" for c in comments))
    return "\n\n".join(sections)


fetch_trend_data_tool = FunctionTool(fetch_trend_data)



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
    return await asyncio.to_thread(open_meteo.get_weather_for_dates, dates=dates, **geo)


get_weather_tool = FunctionTool(get_weather)
