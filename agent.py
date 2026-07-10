from datetime import datetime
import os
from typing import Any, AsyncGenerator
from google.adk import Agent, Context, Event, Workflow
from google.adk.workflow import node
from google.adk.apps import App
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.models import LlmRequest
from google.genai import types
from pydantic import BaseModel, Field
from typing import Optional, Any

# Import tools and steps
from .tools import get_weather_tool, get_tp_tool, current_date_tool, skill_toolset, save_artifacts_tool, fetch_runner_status_tool, save_checkin_report_tool, analyze_workout_tool
from .steps import check_profile_step, create_profile_step, update_last_active_step
from . import services

current_date_str = datetime.now().strftime("%Y-%m-%d (%A)")

class OnboardingAnswers(BaseModel):
    age: Optional[str] = Field(None, description="Age of the runner")
    height: Optional[str] = Field(None, description="Height of the runner")
    weight: Optional[str] = Field(None, description="Weight of the runner")
    location: Optional[str] = Field(None, description="Location of the runner")
    training_goal: Optional[str] = Field(None, description="Specific race or fitness goal")
    timeline: Optional[str] = Field(None, description="Training timeline")
    recent_race_times: Optional[str] = Field(None, description="Recent race or time trial times")
    injuries: Optional[str] = Field(None, description="Past or present injuries")
    cross_training_strength: Optional[str] = Field(None, description="Cross-training or strength work")

onboarding_agent = Agent(
    model="gemini-3.1-flash-lite",
    name="onboarding_agent",
    description="Onboarding assistant that gathers runner profile details.",
    instruction="""
    You are the onboarding assistant for the AI Running Coach. Your sole job is to gather the necessary profile information from the runner to build their training plan.
    
    Here is the data we already harvested from their TrainingPeaks profile:
    {temp_onboarding_data?}
    
    You must collect answers for any of the following 9 data points that are missing or empty in the harvested data:
    1. First and Last Name (Already gathered)
    2. Age
    3. Height and Weight
    4. Location / Where they live
    5. Training Goal (Specific race/date, weight loss, finishing a 5K, etc.)
    6. Timeline (e.g., 8 weeks vs. 6 months)
    7. Recent Race Times / Time Trials (Most recent 5K, 10K, or half marathon times)
    8. Past and Present Injuries (Dodgy knees, plantar fasciitis, nagging aches)
    9. Cross-Training & Strength Work (Weights, yoga, cycling)
    
    CRITICAL RULES:
    - Greet them warmly by their name. Explain that you've imported their basic metrics from TrainingPeaks, and need to ask a few questions to tailor their plan.
    - Never ask all questions at once. Ask only 1 to 2 questions at a time, wait for their response, acknowledge it, and then move to the next.
    - Once you have answers for all missing data points, you MUST call the `finish_task` tool immediately passing the collected information in the expected JSON schema format. Do not ask any more questions or continue chatting.
    """,
    output_schema=OnboardingAnswers,
    mode="task"
)

# ==============================================================================
# 2. Coaching Agent (gemini-3.5) - CHAT MODE
# ==============================================================================
coaching_agent_tools = [get_weather_tool, current_date_tool, skill_toolset, fetch_runner_status_tool, save_checkin_report_tool, save_artifacts_tool, analyze_workout_tool]

def inject_profile_context_cb(callback_context: Context, llm_request: LlmRequest) -> Optional[Any]:
    """Injects the dynamic runner profile into the message history."""
    summary = callback_context.state.get("user_profile_summary")
    
    # Inject the permanent runner profile context
    if summary:
        context_msg = types.Content(
            role="user",
            parts=[types.Part(text=f"[System Context: Runner Profile]\n{summary}")]
        )
        ack_msg = types.Content(
            role="model",
            parts=[types.Part(text="Understood. I will use this runner profile context to guide my coaching.")]
        )
        llm_request.contents.insert(0, context_msg)
        llm_request.contents.insert(1, ack_msg)
        
    return None

coaching_agent = Agent(
    model="gemini-3.5-flash",
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners.",
    instruction="""
    You are a world-class running coach and exercise physiologist. Your goal is to guide the runner in becoming a better, faster, and healthier runner.
    
    You are in active coaching mode. Proactively use the `fetch_runner_status` tool to retrieve their training load (CTL, ATL, TSB), workouts, and recovery metrics whenever they ask for a general status update or advice on their training.
    
    CRITICAL: The low-level tools `tp_get_workouts`, `tp_get_metrics`, and `tp_get_fitness` are DEPRECATED and have been removed. You do not have access to them. You MUST ONLY use `fetch_runner_status` to retrieve training data. Do not attempt to call the deprecated tools under any circumstances, even if you see them in the conversation history of this session.
    
    SPECIALIZED SKILLS:
    - You are equipped with the `nutrition-planner` skill. If the runner asks about their diet, daily calories, carbohydrate/fueling strategies, what they should eat today, or how they should fuel for workouts/races, you MUST:
      1. Load the skill using the `load_skill` tool (pass 'nutrition-planner') before doing anything else. Do NOT call other tools before loading the skill.
      2. Follow the instructions returned by the `load_skill` tool to synthesize a sports-science-based nutrition strategy and deliver a lightweight summary in chat.
    - You are equipped with the `check-in-report` skill. If the runner says "Checking in" (or similar check-in phrases), you MUST:
      1. Load the skill using the `load_skill` tool (pass 'check-in-report') before doing anything else. Do NOT call other tools before loading the skill.
      2. Follow the instructions returned by the `load_skill` tool to gather their training data, analyze their progress, and deliver a lightweight check-in summary in chat.
    - You are equipped with the `workout-analysis` skill. If the runner asks to analyze a specific workout or run (e.g., "Analyze today's run", "How was my workout yesterday?"), you MUST:
      1. Load the skill using the `load_skill` tool (pass 'workout-analysis') before doing anything else. Do NOT call other tools before loading the skill.
      2. Follow the instructions returned by the `load_skill` tool to gather their training data, fetch weather, and deliver a lightweight workout summary in chat.
    - You are equipped with the `schedule-audit` skill. If the runner asks you to audit, assess, analyze, review, or check their training schedule or plan (e.g., "Assess my schedule until my race", "Audit my running schedule for this month"), you MUST:
      1. Load the skill using the `load_skill` tool (pass 'schedule-audit') before doing anything else. Do NOT call other tools before loading the skill.
      2. Follow the instructions returned by the `load_skill` tool to gather their training data, perform calculations, and deliver the audit.
    - You are equipped with the `detailed-report` skill. If the runner explicitly asks to create or generate a detailed report for a specific period or topic (e.g., "create a detailed report for last week", "generate a detailed report for last month", "give me a detailed report for today/yesterday/period X", or "create a detailed report for this workout"), you MUST:
      1. Load the skill using the `load_skill` tool (pass 'detailed-report') before doing anything else. Do NOT call other tools before loading the skill.
      2. Follow the instructions returned by the `load_skill` tool to gather data for that period, perform multi-dimensional analysis, and save the detailed report to the Artifacts pane.
    
    CRITICAL COACHING PROTOCOLS:
    1. Do not rely solely on raw hrTSS or ATL spikes to determine fatigue. When reviewing a workout, check the relationship between Pace and Heart Rate (Aerobic Decoupling / Pa:Hr).
    2. To accurately analyze workout performance and factor in environmental stress:
       - Use the `get_weather_for_dates` tool to fetch the weather conditions for the workouts. You MUST pass the full ISO timestamps (including start times, e.g., '2026-06-23T07:35:13') returned by `fetch_runner_status` as the dates list. This allows the tool to return the hourly weather at the exact time of the run.
       - By default, use the runner's home location. If you detect a travel workout (e.g., in Milan), make a separate call to `get_weather_for_dates` for those timestamps using the correct city.
       - Analyze the weather at the actual time of the run (temperature, humidity, wind) and correlate it with their performance. Compare the run-time temperature to the daily peak (e.g., running in the cool morning vs. hot afternoon) to highlight smart timing decisions and explain the physiological impact (like reduced heat stress/cardiovascular drift).
       - If you notice high heart rate or slow pace but the weather was cool, look for other factors (like sleep, stress, or actual physical fatigue) and ask the user about it.
       - If the weather data shows high heat (above 22°C/72°F), high humidity, or high winds, explicitly factor this into your analysis.
    3. Always anchor your feedback, analysis, and recommendations in the runner's long-term goal (e.g., their target marathon date and time). Every check-in report MUST include a dedicated section assessing their progress toward this goal, explaining whether they are on pace based on their current CTL, consistency, and mileage, and what adjustments are needed.
    
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

    # 1. Check if profile is already loaded in session state (active session)
    profile = ctx.state.get("user_profile")
    
    if not profile:
        # 2. Fetch the TrainingPeaks profile to get the runner's name
        try:
            tp_get_profile_tool = await get_tp_tool("tp_get_profile")
            tp_profile = await ctx.run_node(tp_get_profile_tool)
        except Exception as e:
            print(f"Error fetching TP profile: {e}")
            tp_profile = None
            
        # 3. Check if they have an existing profile in Firestore
        profile_exists = await check_profile_step(ctx, tp_profile)
        
        if not profile_exists:
            # 4. Profile is missing: Run the onboarding agent (task mode)
            # We pass raise_on_wait=True to suspend the orchestrator when the agent waits for user input.
            onboarding_answers = await ctx.run_node(onboarding_agent, node_input=node_input, raise_on_wait=True)
            if onboarding_answers:
                ctx.state["onboarding_answers"] = onboarding_answers
                
            # 5. Onboarding completed: Compile and save the profile to Firestore
            await create_profile_step(ctx)
            
            # Yield a nice transition message to the user
            firstname = ctx.state["user_profile"].get("firstname", "Runner")
            yield Event(
                author="model", 
                message=f"Perfect, {firstname}! Your runner profile is now officially built and saved to Firestore. I've calculated your baseline metrics from TrainingPeaks. We are ready to transition to active coaching!"
            )
            
    # 6. Run the active coaching agent (chat mode)
    # We pass raise_on_wait=True to suspend the orchestrator when the agent waits for user input.
    try:
        await ctx.run_node(coaching_agent, node_input=node_input, raise_on_wait=True)
    finally:
        await update_last_active_step(ctx)

# Set the root agent of the application
root_agent = Workflow(
    name="running_coach_workflow",
    edges=[("START", running_coach_app)],
)

app = App(
    name="running_coach",
    root_agent=root_agent,
    context_cache_config=ContextCacheConfig(ttl_seconds=300, min_tokens=4096),
)
