"""Plan audit tool for the `plan-audit` skill."""

from datetime import timedelta
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date, monday_of, parse_date
from ...shared.long_run_facts import history_window, recent_long_runs
from ...shared.north_star_targets import baseline_window, recent_volume_baseline
from ...shared.parallel_fetch import gather_labeled
from ...shared.tp_payloads import coerce_mcp_payload
from ...shared.weekly_buckets import build_week_buckets
from .helpers.audit_summary_text import format_plan_audit_summary
from .helpers.calendar_notes_by_week import add_notes_to_weeks
from .helpers.long_run_annotations import (
    annotate_long_runs,
    annotate_volume,
    annotate_week_over_week,
    format_goal_context,
)
from .helpers.web_report import AUDIT_REPORT_STATE_KEY, audit_report_data


async def fetch_plan_audit_data(
    tool_context: ToolContext,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weeks_forward: int = 4,
    weeks_back: int = 1,
) -> str:
    """Per-ISO-week plan audit: volume, TSS, easy/quality split, cross-training, calendar notes,
    goal context and long runs and weekly volume vs target. Past weeks use completed values.

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
    start_str, end_str = iso_date(q_start), iso_date(q_end)
    # The ISO week before the first audited week: the reference for its week-over-week change.
    prior_start = monday_of(q_start) - timedelta(weeks=1)
    prior_end = q_start - timedelta(days=1)
    # Completed weeks before this one: the starting level of the weekly-volume path (same as the trend
    # report) and the long-run history. Only the days the audit window doesn't already cover are fetched.
    base_start = min(baseline_window(today_date)[0], history_window(today_date)[0])
    base_end = min(baseline_window(today_date)[1], prior_start - timedelta(days=1))

    async def baseline_workouts() -> list[dict]:
        return await tp_calls.fetch_workouts(tool_context, iso_date(base_start), iso_date(base_end)) \
            if base_start <= base_end else []

    raw = await gather_labeled({
        "workouts": tp_calls.fetch_workouts(tool_context, iso_date(prior_start), end_str),
        "baseline workouts": baseline_workouts(),
        "calendar notes": tp_calls.fetch_notes(tool_context, start_str, end_str),
        "fitness PMC": tp_calls.run_tp_tool(tool_context, "tp_get_fitness",
                                    start_date=iso_date(today_date - timedelta(days=7)), end_date=iso_date(today_date)),
    })

    if raw["workouts"] is None:
        # Never audit an empty list in place of data we could not load: the coach would report an
        # empty schedule. (gather_labeled has logged the TrainingPeaks error.)
        return (f"Error: Could not load the TrainingPeaks workouts for {start_str} to {end_str}, so the "
                "schedule cannot be audited. This is a data-loading failure: do NOT tell the runner the "
                "schedule is empty. Say the data could not be loaded and suggest trying again shortly.")
    all_workouts = raw["workouts"]
    weeks = build_week_buckets(all_workouts, q_start, q_end)
    # A window starting mid-week makes its first week partial: no week-over-week change for it.
    prior_km = None
    if q_start.weekday() == 0:
        prior_weeks = build_week_buckets(all_workouts, prior_start, prior_end)
        prior_km = sum(w["total_distance_km"] or 0.0 for w in prior_weeks.values())
    add_notes_to_weeks(weeks, raw["calendar notes"] or [])
    week_list = annotate_long_runs(list(weeks.values()), profile)
    annotate_week_over_week(week_list, prior_km)
    history_workouts = (raw["baseline workouts"] or []) + all_workouts
    baseline = recent_volume_baseline(history_workouts, today_date)
    annotate_volume(week_list, profile, baseline, today_date)
    tool_context.state[AUDIT_REPORT_STATE_KEY] = audit_report_data(q_start, q_end, week_list)
    daily = coerce_mcp_payload(raw["fitness PMC"]).get("daily_data") or [] if raw["fitness PMC"] else []
    ctl = next((d.get("ctl") for d in reversed(daily) if d.get("ctl") is not None), None)
    goal_context = format_goal_context(profile, today_date, ctl, recent_long_runs(history_workouts, today_date))
    summary = format_plan_audit_summary(week_list, goal_context=goal_context)
    if raw["calendar notes"] is None:
        summary += ("\n\n⚠️ Calendar notes unavailable (TrainingPeaks error): travel, illness or other "
                    "calendar notes for this window are not shown above.")
    return summary


fetch_plan_audit_data_tool = FunctionTool(fetch_plan_audit_data)
