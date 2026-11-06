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
from ...features.workout_creator.create_note_tool import create_note_tool
from ...features.workout_creator.create_workout_tool import create_workout_tool
from ..model_config import COACH_MODEL, build_model
from ..onboarding.request_new_goal_tool import request_new_goal_tool
from .instruction import build_coach_instruction
from .model_callbacks import apply_thinking_policy, splice_tables
from .skill_toolset import skill_toolset

coaching_agent_tools = [
    skill_toolset,
    analyze_workout_tool,
    fetch_checkin_data_tool,
    fetch_trend_data_tool,
    fetch_schedule_audit_data_tool,
    fetch_nutrition_context_tool,
    create_workout_tool,
    create_note_tool,
    request_new_goal_tool,
    get_weather_tool,
]

coaching_agent = Agent(
    model=build_model(COACH_MODEL),
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners with objective, data-driven feedback.",
    instruction=build_coach_instruction,
    tools=coaching_agent_tools,
    # Deterministic no-workout reply; full reasoning except on post-write confirmations;
    # check-in / trend tables spliced in verbatim.
    before_model_callback=[no_workout_reply, apply_thinking_policy],
    after_model_callback=splice_tables,
    mode="chat",
)


@node(name="coaching_node", rerun_on_resume=True)
async def coaching_node(ctx: Context, node_input: Any = None) -> None:
    """Runs the coaching agent for active interactive running guidance."""
    await ctx.run_node(coaching_agent, node_input=node_input, raise_on_wait=True)
