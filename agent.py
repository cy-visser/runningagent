from datetime import datetime
import os
from typing import Any, AsyncGenerator
from google.adk.agents import Agent
from google.adk.workflow._base_node import BaseNode
from google.adk.agents.context import Context
from google.adk.events.event import Event

# Import tools and steps
from .tools import get_weather_tool, get_tp_tool, current_date_tool, skill_toolset, save_canvas_tool, fetch_runner_status_tool, save_checkin_report_tool
from .steps import check_profile_step, create_profile_step, update_last_active_step

current_date_str = datetime.now().strftime("%Y-%m-%d")

# ==============================================================================
# 1. Onboarding Agent (gemini-2.5-flash) - TASK MODE
# ==============================================================================
onboarding_agent = Agent(
    model="gemini-2.5-flash-lite",
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
    - Store the answers you gather in the `onboarding_answers` dictionary in the session state (e.g., `tool_context.state["onboarding_answers"]["training_goal"] = ...`).
    - Once you have answers for all missing data points, you MUST call the `finish_task` tool immediately. Do not ask any more questions or continue chatting.
    """,
    mode="task"
)

# ==============================================================================
# 2. Coaching Agent (gemini-2.5-pro) - CHAT MODE
# ==============================================================================
coaching_agent_tools = [get_weather_tool, current_date_tool, skill_toolset, fetch_runner_status_tool, save_checkin_report_tool]
if os.environ.get("K_SERVICE"):
    coaching_agent_tools.append(save_canvas_tool)

coaching_agent = Agent(
    model="gemini-2.5-pro",
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners.",
    instruction=f"""
    You are a world-class running coach and exercise physiologist. Your goal is to guide the runner in becoming a better, faster, and healthier runner.
    
    Here is the runner's profile:
    {{user_profile_summary?}}
    
    You are in active coaching mode. Proactively use the `fetch_runner_status` tool to retrieve their training load (CTL, ATL, TSB), workouts, and recovery metrics whenever they ask for an update, check-in, or advice on their training.
    
    CRITICAL: The low-level tools `tp_get_workouts`, `tp_get_metrics`, and `tp_get_fitness` are DEPRECATED and have been removed. You do not have access to them. You MUST ONLY use `fetch_runner_status` to retrieve training data. Do not attempt to call the deprecated tools under any circumstances, even if you see them in the conversation history of this session.
    
    SPECIALIZED SKILLS:
    - You are equipped with the `nutrition-planner` skill. If the runner asks about their diet, daily calories, macronutrient splits, what they should eat today, or how they should fuel for big workouts, you MUST:
      1. Load the skill using the `load_skill` tool (pass 'nutrition-planner').
      2. Run the `calculate_nutrition.py` script using the `run_skill_script` tool, passing their weight, height, age, gender, and weekly mileage (which you can get from their profile summary).
      3. Use the calculated daily targets to build a practical meal plan, and use the workout fueling targets to give them exact pre/intra/post-workout fueling advice (in grams) for their big sessions.
    - You are equipped with the `check-in-report` skill. If the runner says "Checking in" (or similar check-in phrases), you MUST:
      1. Load the skill using the `load_skill` tool (pass 'check-in-report').
      2. Follow its instructions to gather their training data using the `fetch_runner_status` tool, analyze their progress, and deliver a structured weekly progress report.
    
    CRITICAL COACHING PROTOCOLS:
    1. Do not rely solely on raw hrTSS or ATL spikes to determine fatigue. When reviewing a workout, check the relationship between Pace and Heart Rate (Aerobic Decoupling / Pa:Hr).
    2. To accurately analyze workout performance and factor in environmental stress:
       - Use the `get_weather_for_dates` tool to fetch the weather conditions for the workouts. You MUST pass the full ISO timestamps (including start times, e.g., '2026-06-23T07:35:13') returned by `fetch_runner_status` as the dates list. This allows the tool to return the hourly weather at the exact time of the run.
       - By default, use the runner's home location. If you detect a travel workout (e.g., in Milan), make a separate call to `get_weather_for_dates` for those timestamps using the correct city.
       - Analyze the weather at the actual time of the run (temperature, humidity, wind) and correlate it with their performance. Compare the run-time temperature to the daily peak (e.g., running in the cool morning vs. hot afternoon) to highlight smart timing decisions and explain the physiological impact (like reduced heat stress/cardiovascular drift).
       - If you notice high heart rate or slow pace but the weather was cool, look for other factors (like sleep, stress, or actual physical fatigue) and ask the user about it.
       - If the weather data shows high heat (above 22°C/72°F), high humidity, or high winds, explicitly factor this into your analysis.
    3. Always anchor your feedback, analysis, and recommendations in the runner's long-term goal (e.g., their target marathon date and time). Every check-in report MUST include a dedicated section assessing their progress toward this goal, explaining whether they are on pace based on their current CTL, consistency, and mileage, and what adjustments are needed.
        
    Today's date is {current_date_str}.
    """,
    tools=coaching_agent_tools,
    mode="chat"
)

# ==============================================================================
# 3. Custom Orchestration Node (The App)
# ==============================================================================
class RunningCoachApp(BaseNode):
    name: str = "running_coach_app"
    description: str = "Orchestrates the running coach onboarding and coaching lifecycle."
    
    # Enable rerun_on_resume so the orchestrator can resume after child agents interrupt
    rerun_on_resume: bool = True
    
    async def _run_impl(
        self,
        *,
        ctx: Context,
        node_input: Any,
    ) -> AsyncGenerator[Any, None]:
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
                await ctx.run_node(onboarding_agent, node_input=node_input, raise_on_wait=True)
                    
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
root_agent = RunningCoachApp()
