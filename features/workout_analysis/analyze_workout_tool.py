import asyncio
from datetime import timedelta
import logging
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.athlete_settings import extract_thresholds, sport_thresholds
from ...shared.dates import get_today_date, iso_date, parse_date
from ...shared.health_metrics import (
    extract_health_metrics,
    extract_health_metrics_dated,
    format_recovery_metrics,
)
from ...shared.parallel_fetch import gather_labeled, result_or_none
from ...shared.runner_weather import fetch_weather_text
from ...shared.tp_payloads import coerce_mcp_payload, parse_mcp_response
from ...shared.training_log.record_writer import record_workout
from ...shared.training_log.telemetry_file import load_analysis_file
from ...shared.workout_status import is_workout_completed
from ...shared.workout_structure import (
    align_laps,
    flatten_structure,
    has_structure,
    session_decoupling,
)
from .helpers.planned_vs_executed import format_structured_execution
from .helpers.session_notes_and_feedback import format_athlete_feedback, planned_notes
from .helpers.session_selection import (
    format_no_workout,
    format_other_sessions,
    select_primary_workout,
)
from .helpers.sub_goal_race_result import goal_plan_context
from .helpers.workout_summary_text import format_workout_analysis

logger = logging.getLogger(__name__)

RECOVERY_LOOKBACK_DAYS = 7
NO_WORKOUT_LOOKBACK_DAYS = 7


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
    target_iso = iso_date(target_date)
    sport_hint = sport
    sport, title, start = "Workout", "", None
    other_sessions: list[dict] = []

    # Resolve the workout from the date (including a 7-day lookback to cite the latest completed session if today has none).
    if not workout_id:
        try:
            recent = await tp_calls.fetch_workouts(
                tool_context, iso_date(target_date - timedelta(days=NO_WORKOUT_LOOKBACK_DAYS)), target_iso
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

        meta_payload = result_or_none(meta_raw, "workout details")
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

        series, start_pos = await asyncio.to_thread(load_analysis_file, data.get("data_file"))

        # Thresholds, recovery and PMC are always fetched: the training-log record needs them
        # regardless of what this reply displays.
        extras: dict[str, Any] = {
            "athlete settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
            "recovery metrics": tp_calls.run_tp_tool(
                tool_context, "tp_get_metrics",
                start_date=iso_date(workout_date - timedelta(days=RECOVERY_LOOKBACK_DAYS)),
                end_date=iso_date(workout_date),
            ),
            "fitness PMC": tp_calls.run_tp_tool(
                tool_context, "tp_get_fitness", start_date=iso_date(workout_date), end_date=iso_date(workout_date),
            ),
        }
        if include_weather:
            extras["weather"] = fetch_weather_text(
                profile, [str(start)], position=start_pos, utc=start_is_utc,
            )
        extra = await gather_labeled(extras)

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
        notes = planned_notes(meta)
        if notes:
            sections.append(f"**Planned session notes:** {notes}")
        feedback = format_athlete_feedback(meta)
        if feedback:
            sections.append(f"**Athlete feedback:** {feedback}")
        if include_recovery and extra.get("recovery metrics"):
            rec_formatted = format_recovery_metrics(extract_health_metrics(extra["recovery metrics"]))
            if rec_formatted:
                sections.append(
                    f"**Recovery context ({RECOVERY_LOOKBACK_DAYS} days to {iso_date(workout_date)}):**\n{rec_formatted}"
                )
        if extra.get("weather"):
            sections.append(f"**Environmental & Weather Context:**\n{extra['weather']}")
        goal_context = await goal_plan_context(
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


analyze_workout_tool = FunctionTool(analyze_workout)
