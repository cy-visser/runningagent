"""Plan context tool for the `plan-builder` skill: everything the coach needs to plan a block in one call."""

from datetime import timedelta

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date, monday_of, parse_date
from ...shared.goal_plan import current_goal, race_day
from ...shared.parallel_fetch import gather_labeled
from ...shared.tp_payloads import coerce_mcp_payload
from .helpers.pace_zones import resolve_zones
from .helpers.plan_context_text import (
    PLAN_CONTEXT_STATE_KEY,
    history_window,
    latest_fitness,
    plan_context_text,
)
from .helpers.plan_expand import MAX_WEEKS, MODES

DEFAULT_WEEKS = 12


async def fetch_plan_context(
    tool_context: ToolContext, start_date: str = "", end_date: str = "", mode: str = "new"
) -> str:
    """Plan context for building or overhauling a training plan: goal and constraints, the run pace /
    bike FTP zone table every session code resolves to, recent training (weekly km, long runs, CTL,
    strength and bike frequency) and the planned calendar of the window per ISO week.

    Args:
        start_date: YYYY-MM-DD, first day of the plan (default: next Monday).
        end_date: YYYY-MM-DD, last day (default: the current goal race, else 12 weeks).
        mode: "new" (a new plan / block; existing sessions are updated per day and sport) or "overhaul"
            (rewrite the window: planned Run / Strength / Bike sessions not in the plan are removed;
            sessions are listed with their [workout_id]).
    """
    profile = tool_context.state.get("user_profile") or {}
    today = get_today_date()
    start = parse_date(start_date) or (monday_of(today) + timedelta(weeks=1))
    race = race_day(current_goal(profile, start))
    end = parse_date(end_date) or (race if race and race > start else start + timedelta(weeks=DEFAULT_WEEKS, days=-1))
    end = min(end, monday_of(start) + timedelta(weeks=MAX_WEEKS, days=-1))
    mode = mode if mode in MODES else "new"
    tool_context.state[PLAN_CONTEXT_STATE_KEY] = {"start_date": iso_date(start), "end_date": iso_date(end), "mode": mode}

    h_start, h_end = history_window(today)
    raw = await gather_labeled({
        "settings": tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings"),
        "history": tp_calls.fetch_workouts(tool_context, iso_date(h_start), iso_date(h_end)),
        "workouts": tp_calls.fetch_workouts(tool_context, iso_date(monday_of(start)), iso_date(end)),
        "notes": tp_calls.fetch_notes(tool_context, iso_date(monday_of(start)), iso_date(end)),
        "fitness": tp_calls.run_tp_tool(tool_context, "tp_get_fitness", start_date=iso_date(today - timedelta(days=7)),
                                        end_date=iso_date(today)),
    })
    fitness = latest_fitness(coerce_mcp_payload(raw["fitness"]).get("daily_data")) if raw["fitness"] else None
    zones = resolve_zones(raw["settings"], profile, today)
    return plan_context_text(profile, start, end, mode, today, zones, raw["history"], raw["workouts"],
                             raw["notes"], fitness)


fetch_plan_context_tool = FunctionTool(fetch_plan_context)
