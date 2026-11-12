from typing import Any

from google.adk import Agent, Context
from google.adk.workflow import node

from ...features.check_in_report.fetch_checkin_data_tool import fetch_checkin_data_tool
from ...features.nutrition_planner.fetch_nutrition_context_tool import (
    fetch_nutrition_context_tool,
)
from ...features.plan_builder.apply_training_plan_tool import apply_training_plan_tool
from ...features.plan_builder.fetch_plan_context_tool import fetch_plan_context_tool
from ...features.plan_builder.stage_training_plan_tool import stage_training_plan_tool
from ...features.plan_audit.fetch_plan_audit_data_tool import (
    fetch_plan_audit_data_tool,
)
from ...features.trend_analysis.fetch_trend_data_tool import fetch_trend_data_tool
from ...features.weather_lookup.get_weather_tool import get_weather_tool
from ...features.workout_analysis.analyze_workout_tool import analyze_workout_tool
from ...features.workout_creator.apply_staged_changes_tool import apply_staged_changes_tool
from ...features.workout_creator.stage_workout_changes_tool import stage_workout_changes_tool
from ..model_config import build_coach_model
from ..onboarding.request_new_goal_tool import request_new_goal_tool
from ..report_memory import keep_latest_reports_and_skills
from .instruction import build_coach_instruction
from .model_callbacks import (
    after_coach_model,
    apply_thinking_policy,
    hide_internal_tools,
    strip_stale_thoughts,
)
from .profile_context import ensure_profile_context
from .record_key_event_tool import record_key_event_tool
from .quick_actions import dispatch_quick_action
from .report_tool_guard import guard_report_tools
from .skill_toolset import skill_toolset

coaching_agent_tools = [
    skill_toolset,
    analyze_workout_tool,
    fetch_checkin_data_tool,
    fetch_trend_data_tool,
    fetch_plan_audit_data_tool,
    fetch_nutrition_context_tool,
    stage_workout_changes_tool,
    apply_staged_changes_tool,
    fetch_plan_context_tool,
    stage_training_plan_tool,
    apply_training_plan_tool,
    request_new_goal_tool,
    record_key_event_tool,
    get_weather_tool,
]

coaching_agent = Agent(
    model=build_coach_model(),
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners with objective, data-driven feedback.",
    instruction=build_coach_instruction,
    tools=coaching_agent_tools,
    # Runner profile once per call; quick actions without a routing LLM call; per-call thinking; hide
    # internal plan-builder tools from LLM declarations; drop signatures of completed turns; keep only
    # the latest reports, skills and staged set.
    before_model_callback=[
        ensure_profile_context,
        dispatch_quick_action,
        apply_thinking_policy,
        hide_internal_tools,
        strip_stale_thoughts,
        keep_latest_reports_and_skills,
    ],
    # Single composed after-model callback: drops calls on tools-off report turns, auto-appends
    # fetch_plan_context when plan-builder is loaded, and records turn calls for guard_report_tools.
    after_model_callback=[after_coach_model],
    before_tool_callback=[guard_report_tools],
    mode="chat",
)


@node(name="coaching_node", rerun_on_resume=True)
async def coaching_node(ctx: Context, node_input: Any = None) -> None:
    """Runs the coaching agent for active interactive running guidance."""
    await ctx.run_node(coaching_agent, node_input=node_input, raise_on_wait=True)
