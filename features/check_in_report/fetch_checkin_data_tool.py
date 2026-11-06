import asyncio
from datetime import timedelta
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations import firestore
from ...integrations.trainingpeaks import tp_calls
from ...shared.athlete_settings import extract_hr_zones, extract_thresholds
from ...shared.dates import get_today_date, iso_date, parse_date
from ...shared.goal_distance import resolve_goal_distance
from ...shared.goal_plan import current_goal, goal_race_dates
from ...shared.health_metrics import HEALTH_BASELINE_DAYS, extract_health_metrics_dated
from ...shared.hr_pace_fit import LT_FIT_WEEKS
from ...shared.parallel_fetch import gather_labeled
from ...shared.runner_identity import profile_user_id
from ...shared.weekly_buckets import build_week_buckets
from ...shared.workout_status import partition_workouts_by_date
from .helpers.checkin_summary_text import compile_checkin_summary
from ...shared.goal_projection.goal_trajectory import summarize_fitness
from ...shared.goal_projection.health_flag import health_readiness, recent_hard_effort
from .helpers.lt_paces import checkin_lt_paces
from .helpers.north_star_progress import north_star_progress
from ...shared.goal_projection.projection_evidence import PROJECTION_WINDOW_DAYS
from ...shared.goal_projection.race_projection import build_goal_projection
from .helpers.run_weather import fetch_checkin_weather_map
from .helpers.web_report import CHECKIN_REPORT_STATE_KEY, checkin_report_data
from .helpers.weekly_totals import annotate_week_progression

PROJECTION_LOOKBACK_DAYS = 90


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

    start_str, end_str = iso_date(q_start), iso_date(q_end)
    recovery_end_str = iso_date(min(q_end, today_date))
    workouts_start = min(q_start, today_date - timedelta(days=PROJECTION_WINDOW_DAYS))
    metrics_start = min(q_start, today_date - timedelta(days=HEALTH_BASELINE_DAYS))
    history_start = min(q_start, today_date - timedelta(days=PROJECTION_LOOKBACK_DAYS))

    # Phase 1: gather calendar, notes, metrics, PMC and athlete thresholds.
    fetches = {
        "workouts": tp_calls.fetch_workouts(tool_context, iso_date(workouts_start), end_str),
        "calendar notes": tp_calls.fetch_notes(tool_context, start_str, end_str),
        "recovery metrics": tp_calls.run_tp_tool(
            tool_context, "tp_get_metrics", start_date=iso_date(metrics_start), end_date=recovery_end_str,
        ),
        "fitness PMC": tp_calls.run_tp_tool(
            tool_context, "tp_get_fitness", start_date=iso_date(history_start), end_date=recovery_end_str,
        ),
        # Athlete settings: LTHR / HR zones for LT1/LT2, thresholds for the goal projection.
        "athlete settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
    }
    user_id = profile_user_id(profile)
    if user_id:
        # Training log (laps + start_position) for LT1/LT2 fits and per-workout weather; no gap-fill here.
        fetches["training records"] = firestore.list_training_records(
            user_id, iso_date(min(q_start, today_date - timedelta(weeks=2 * LT_FIT_WEEKS))), iso_date(today_date)
        )
    raw = await gather_labeled(fetches)

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
    fitness_data = summarize_fitness(raw["fitness PMC"], profile, today_date, window_start=q_start)
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
        build_goal_projection(
            tool_context, goal_label, profile, all_workouts, fitness_data,
            raw.get("athlete settings"), dated_metrics, today_date,
            refresh_cache=refresh_analysis_cache,
        ),
        fetch_checkin_weather_map(profile, workouts_past, raw.get("training records")),
    )

    # LT1 (top of TP HR zone 2) / LT2 (LTHR) paces, same fit as the trend report.
    zones = extract_hr_zones(raw["athlete settings"])
    lt = checkin_lt_paces(
        raw.get("training records") or [], today_date,
        extract_thresholds(raw["athlete settings"]).get("lthr"),
        zones[1]["max"] if len(zones) >= 2 else None,
    )

    # The web report renders the metrics, projection drivers and charts from this payload; the
    # coach reasons over the same numbers in the summary below and writes only the judgement.
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
    ns_progress = north_star_progress(profile, race_projection, today_date)
    return f"{summary}\n\n{ns_progress}" if ns_progress else summary


fetch_checkin_data_tool = FunctionTool(fetch_checkin_data)
