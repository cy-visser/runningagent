import asyncio
from datetime import datetime
import os
from typing import Any, AsyncGenerator, Optional
from google.adk import Agent, Context, Event, Workflow
from google.adk.workflow import node
from google.adk.apps import App
from google.adk.plugins.auto_tracing_plugin import AutoTracingPlugin
from google.adk.models import LlmRequest
from google.genai import types
from pydantic import BaseModel, Field

# Import tools and steps
from .tools import (
    get_weather_tool,
    skill_toolset,
    analyze_workout_tool,
    fetch_checkin_data_tool,
    fetch_schedule_audit_data_tool,
    fetch_nutrition_context_tool,
    create_workout_tool,
    create_note_tool,
    save_checkin_report_tool,
    request_new_goal_tool,
    get_tp_tool,
)
from .steps import check_profile_step, create_profile_step, check_timeline_expiration
from . import services

current_date_str = datetime.now().strftime("%Y-%m-%d (%A)")

async def run_node_with_retry(
    ctx: Context,
    node_or_agent: Any,
    node_input: Any = None,
    raise_on_wait: bool = False,
    max_retries: int = 3,
    initial_delay: float = 2.0
) -> Any:
    """Wraps ctx.run_node with exponential backoff on 429 / RateLimit errors."""
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return await ctx.run_node(node_or_agent, node_input=node_input, raise_on_wait=raise_on_wait)
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "RateLimit" in err_str) and attempt < max_retries:
                print(f"DEBUG: 429 Rate Limit encountered. Retrying in {delay}s (Attempt {attempt}/{max_retries})...")
                await asyncio.sleep(delay)
                delay *= 4.0
            else:
                raise e

class OnboardingAnswers(BaseModel):
    age: Optional[str] = Field(None, description="Age of the runner")
    height: Optional[str] = Field(None, description="Height of the runner")
    weight: Optional[str] = Field(None, description="Weight of the runner")
    location: Optional[str] = Field(None, description="Location of the runner")
    training_goal: Optional[str] = Field(None, description="Specific race or fitness goal")
    timeline: Optional[str] = Field(None, description="Training timeline (ISO format YYYY-MM-DD)")
    recent_race_times: Optional[str] = Field(None, description="Recent race or time trial times")
    injuries: Optional[str] = Field(None, description="Past or present injuries")
    cross_training_strength: Optional[str] = Field(None, description="Cross-training or strength work")
    shoe_rotation: Optional[str] = Field(None, description="Current shoe rotation (e.g. shoes for easy runs, tempo runs, intervals, race days)")

onboarding_agent = Agent(
    model="gemini-3.1-flash-lite",
    name="onboarding_agent",
    description="Onboarding assistant that gathers runner profile details.",
    instruction="""
    You are the onboarding assistant for the AI Running Coach. Your sole job is to gather the necessary profile information from the runner to build or update their training plan.
    
    Here is the data we already harvested or loaded from their profile:
    {temp_onboarding_data?}
    
    You must collect answers for any missing fields or updated preferences:
    1. First and Last Name (Already gathered)
    2. Age
    3. Height and Weight
    4. Location / Where they live
    5. Training Goal (Specific race/date, weight loss, finishing a 5K, etc.)
    6. Timeline (Target goal/race date MUST be provided as an ISO date string in YYYY-MM-DD format, e.g., '2026-11-01')
    7. Recent Race Times / Time Trials (Most recent 5K, 10K, or half marathon times)
    8. Past and Present Injuries (Dodgy knees, plantar fasciitis, nagging aches)
    9. Cross-Training & Strength Work (Weights, yoga, cycling)
    10. Current Shoe Rotation (Shoes used for easy runs, tempo runs, intervals, race days)
    
    CRITICAL RULES:
    - If updating an existing runner's goal, greet them warmly, acknowledge their previous goal completion, and ask for their updated training goal and target race date (timeline strictly in YYYY-MM-DD format).
    - Never ask all questions at once. Ask only 1 to 2 questions at a time, wait for their response, acknowledge it, and then move to the next.
    - Never use LaTeX formatting or dollar signs ($...$); output all text, numbers, and units in clean standard text.
    - Ensure the `timeline` field is formatted strictly as an ISO date string (YYYY-MM-DD).
    - Once you have answers for the goal and required missing fields, you MUST call the `finish_task` tool immediately passing the collected information in the expected JSON schema format. Do not ask any more questions or continue chatting.
    """,
    output_schema=OnboardingAnswers,
    mode="task"
)

# ==============================================================================
# 2. Coaching Agent (gemini-3.5) - CHAT MODE
# ==============================================================================
coaching_agent_tools = [
    skill_toolset,
    analyze_workout_tool,
    fetch_checkin_data_tool,
    fetch_schedule_audit_data_tool,
    fetch_nutrition_context_tool,
    create_workout_tool,
    create_note_tool,
    save_checkin_report_tool,
    request_new_goal_tool,
    get_weather_tool,
]

def inject_profile_context_cb(callback_context: Context, llm_request: LlmRequest) -> Optional[Any]:
    """Injects the dynamic runner profile into the message history if not already present."""
    summary = callback_context.state.get("user_profile_summary")
    
    # Inject the permanent runner profile context
    if summary:
        # Check if profile context was already prepended to avoid duplicate injection
        for content in llm_request.contents:
            if content.parts and any("[System Context: Runner Profile]" in str(part.text or "") for part in content.parts):
                return None

        extra_ctx = ""
        expired_date = callback_context.state.get("expired_timeline_date")
        if expired_date:
            extra_ctx = f"\n\n[CRITICAL NOTICE: Today's date ({datetime.now().strftime('%Y-%m-%d')}) is PAST the runner's target timeline date ({expired_date})! You MUST immediately and warmly inform the runner that their goal date has passed and ask if they want to (1) analyze their workout/race on {expired_date} or (2) set up a new training goal via the request_new_goal tool.]"

        context_msg = types.Content(
            role="user",
            parts=[types.Part(text=f"[System Context: Runner Profile]\n{summary}{extra_ctx}")]
        )
        ack_msg = types.Content(
            role="model",
            parts=[types.Part(text="Understood. I will use this runner profile context to guide my coaching.")]
        )
        llm_request.contents.insert(0, context_msg)
        llm_request.contents.insert(1, ack_msg)
        
    return None

coaching_agent = Agent(
    model="gemini-3.7-flash",
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners.",
    instruction="""
    You are a world-class running coach and exercise physiologist. Your goal is to guide the runner in becoming a better, faster, and healthier runner.
    
    You are in active coaching mode. Proactively use the dedicated skill facades to fetch complete context in a single call:
    - To analyze a completed run or ride: use `analyze_workout` (bundles telemetry, laps, recovery, and weather).
    - For weekly check-ins or progress reports: use `fetch_checkin_data` (bundles 14-day history, PMC trends, recovery, and weather).
    - To audit or review the training schedule: use `fetch_schedule_audit_data` (bundles 4-week volume, planned TSS, easy/hard split, and travel notes).
    - For nutrition and fueling strategy: use `fetch_nutrition_context` (bundles runner biometrics, upcoming 3-day demands, and climate).
    - To schedule runs or calendar notes: use `create_workout` or `create_note`.
    
    COACHING DIRECTIVES:
    1. Aerobic Decoupling: Do not rely solely on raw hrTSS or ATL spikes; evaluate pace vs. HR relationship (Pa:Hr) or power vs. HR (Pw:Hr).
    2. Environmental & Weather: Correlate run-time weather (temp, humidity, heat stress >22°C/72°F, wind) with performance.
    3. Goal Alignment: Anchor all feedback and pacing advice in the runner's target goal timeline and volume progression.
    4. Formatting & Style: Never use LaTeX math syntax, dollar-sign delimiters ($...$ or $$...$$), or LaTeX commands (e.g. \\text{...}, \\rightarrow). Output all numbers, units, transitions, and progressions in clean plain text and standard Markdown.
    
    EXPIRED TIMELINE PROTOCOL:
    - If notified that the runner's goal timeline date has passed:
      1. Warmly inform the runner that their target goal date has passed.
      2. Ask whether they want to analyze their race on the goal date or set up a new training goal via `request_new_goal`.
    
    Today's date is {current_date_str?}.
    """,
    tools=coaching_agent_tools,
    before_model_callback=inject_profile_context_cb,
    mode="chat"
)

# ==============================================================================
# 3. Workflow
# ==============================================================================
@node(name="running_coach_app", rerun_on_resume=True)
async def running_coach_app(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    # Set dynamic date in state so it is resolved correctly in the coaching instructions
    ctx.state["current_date_str"] = datetime.now().strftime("%Y-%m-%d (%A)")

    # Step 1: Check if profile exists (if new user, or re-onboarding requested, run onboarding_agent)
    profile = ctx.state.get("user_profile")
    if not profile:
        try:
            tp_get_profile_tool = await get_tp_tool("tp_get_profile")
            tp_profile = await run_node_with_retry(ctx, tp_get_profile_tool)
        except Exception as e:
            print(f"Error fetching TP profile: {e}")
            tp_profile = None
            
        await check_profile_step(ctx, tp_profile)
        profile = ctx.state.get("user_profile")

    if not profile or ctx.state.get("reonboard_requested"):
        onboarding_answers = await run_node_with_retry(ctx, onboarding_agent, node_input=node_input, raise_on_wait=True)
        if onboarding_answers:
            ctx.state["onboarding_answers"] = onboarding_answers
            await create_profile_step(ctx)
            ctx.state["reonboard_requested"] = None
            ctx.state["expired_timeline_date"] = None
            firstname = ctx.state["user_profile"].get("firstname", "Runner")
            yield Event(
                author="model", 
                message=f"Awesome, {firstname}! Your runner profile and goal are updated in Firestore. We are ready for active coaching!"
            )
        return

    # Step 2: Check timeline vs current date 
    is_expired, expired_date = check_timeline_expiration(profile)
    if is_expired:
        ctx.state["expired_timeline_date"] = expired_date
    else:
        ctx.state["expired_timeline_date"] = None

    # Step 3 Run coaching agent 
    await run_node_with_retry(ctx, coaching_agent, node_input=node_input, raise_on_wait=True)

# Set the root agent of the application
root_agent = Workflow(
    name="running_coach_workflow",
    edges=[("START", running_coach_app)],
)

app = App(
    name="running_coach",
    root_agent=root_agent,
    plugins=[AutoTracingPlugin()],
)
