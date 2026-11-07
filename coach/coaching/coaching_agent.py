from typing import Any

from google.adk import Agent, Context
from google.adk.workflow import node

from ...features.check_in_report.fetch_checkin_data_tool import fetch_checkin_data_tool
from ...features.nutrition_planner.fetch_nutrition_context_tool import (
    fetch_nutrition_context_tool,
)
from ...features.schedule_audit.fetch_schedule_audit_data_tool import (
    fetch_schedule_audit_data_tool,
)
from ...features.trend_analysis.fetch_trend_data_tool import fetch_trend_data_tool
from ...features.weather_lookup.get_weather_tool import get_weather_tool
from ...features.workout_analysis.analyze_workout_tool import analyze_workout_tool
from ...features.workout_analysis.no_workout_reply_callback import no_workout_reply
from ...features.workout_creator.apply_staged_changes_tool import apply_staged_changes_tool
from ...features.workout_creator.stage_workout_changes_tool import stage_workout_changes_tool
from ...features.workout_creator.write_confirmation_callback import write_confirmation_reply
from ..model_config import COACH_MODEL, build_model
from ..onboarding.request_new_goal_tool import request_new_goal_tool
from ..report_memory import keep_latest_reports_and_skills
from .instruction import build_coach_instruction
from .model_callbacks import apply_thinking_policy, strip_stale_thoughts
from .profile_context import ensure_profile_context
from .quick_actions import dispatch_quick_action
from .report_tool_guard import guard_report_tools, track_turn_calls
from .skill_toolset import skill_toolset

coaching_agent_tools = [
    skill_toolset,
    analyze_workout_tool,
    fetch_checkin_data_tool,
    fetch_trend_data_tool,
    fetch_schedule_audit_data_tool,
    fetch_nutrition_context_tool,
    stage_workout_changes_tool,
    apply_staged_changes_tool,
    request_new_goal_tool,
    get_weather_tool,
]

coaching_agent = Agent(
    model=build_model(COACH_MODEL),
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners with objective, data-driven feedback.",
    instruction=build_coach_instruction,
    tools=coaching_agent_tools,
    # Runner profile injected exactly once per model call (reloaded if missing); web quick actions
    # dispatch their skill + data tool without a routing LLM call; deterministic no-workout reply;
    # coded replies after staging / applying workout changes (no LLM call); LOW reasoning for a chat
    # approval or the post-staging message, MEDIUM for session edits, HIGH otherwise; reasoning of
    # completed turns is not replayed; only the latest report output and skill instructions are sent.
    before_model_callback=[
        ensure_profile_context,
        dispatch_quick_action,
        no_workout_reply,
        write_confirmation_reply,
        apply_thinking_policy,
        strip_stale_thoughts,
        keep_latest_reports_and_skills,
    ],
    # Report data tools render a report card: they only run as the turn's report, never as a data
    # lookup after another skill or tool in the same turn.
    after_model_callback=[track_turn_calls],
    before_tool_callback=[guard_report_tools],
    mode="chat",
)


@node(name="coaching_node", rerun_on_resume=True)
async def coaching_node(ctx: Context, node_input: Any = None) -> None:
    """Runs the coaching agent for active interactive running guidance."""
    await ctx.run_node(coaching_agent, node_input=node_input, raise_on_wait=True)
