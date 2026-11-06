"""Schedule audit tool for the `schedule-audit` skill."""

from datetime import timedelta
from typing import Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date, parse_date
from ...shared.parallel_fetch import gather_labeled
from ...shared.tp_payloads import coerce_mcp_payload
from ...shared.weekly_buckets import build_week_buckets
from .helpers.audit_summary_text import format_schedule_audit_summary
from .helpers.calendar_notes_by_week import add_notes_to_weeks
from .helpers.long_run_annotations import annotate_long_runs, format_goal_context
from .helpers.web_report import AUDIT_REPORT_STATE_KEY, audit_report_data


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
    start_str, end_str = iso_date(q_start), iso_date(q_end)

    raw = await gather_labeled({
        "workouts": tp_calls.fetch_workouts(tool_context, start_str, end_str),
        "calendar notes": tp_calls.fetch_notes(tool_context, start_str, end_str),
        "fitness PMC": tp_calls.run_tp_tool(tool_context, "tp_get_fitness",
                                    start_date=iso_date(today_date - timedelta(days=7)), end_date=iso_date(today_date)),
    })

    weeks = build_week_buckets(raw["workouts"], q_start, q_end)
    add_notes_to_weeks(weeks, raw["calendar notes"])
    week_list = annotate_long_runs(list(weeks.values()), profile)
    tool_context.state[AUDIT_REPORT_STATE_KEY] = audit_report_data(q_start, q_end, week_list)
    daily = coerce_mcp_payload(raw["fitness PMC"]).get("daily_data") or [] if raw["fitness PMC"] else []
    ctl = next((d.get("ctl") for d in reversed(daily) if d.get("ctl") is not None), None)
    return format_schedule_audit_summary(week_list, goal_context=format_goal_context(profile, today_date, ctl))


fetch_schedule_audit_data_tool = FunctionTool(fetch_schedule_audit_data)
