import asyncio
import logging
import os
from typing import Any, AsyncGenerator, Optional

from google.adk import Agent, Context, Event, Workflow
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.google_llm import Gemini
from google.adk.plugins.auto_tracing_plugin import AutoTracingPlugin
from google.adk.workflow import node
from google.genai import types
from pydantic import BaseModel, Field

from .services.tp_mcp import get_tp_tool
from .steps import (
    PROFILE_TP_UNAVAILABLE,
    check_profile_step,
    check_timeline_expiration,
    create_profile_step,
    load_profile_by_id,
)
from .tools import (
    analyze_workout_tool,
    create_note_tool,
    create_workout_tool,
    fetch_checkin_data_tool,
    fetch_nutrition_context_tool,
    fetch_schedule_audit_data_tool,
    get_weather_tool,
    request_new_goal_tool,
    save_checkin_report_tool,
    skill_toolset,
)
from .utils import RUNNER_ID_STATE_KEY, format_profile_summary, get_today_str, onboarding_prefill

logger = logging.getLogger(__name__)

try:  # Optional: only present when google-api-core is installed.
    from google.api_core.exceptions import ResourceExhausted, TooManyRequests

    _RATE_LIMIT_EXCEPTIONS: tuple[type[Exception], ...] = (ResourceExhausted, TooManyRequests)
except ImportError:  # pragma: no cover - depends on the transport in use
    _RATE_LIMIT_EXCEPTIONS = ()


def _is_rate_limit_error(error: Exception) -> bool:
    """Identifies HTTP 429 / quota-exhaustion errors worth retrying.

    Prefers typed exceptions and structured status codes; the message check is a
    deliberately narrow fallback so unrelated errors that merely contain '429'
    (e.g. a workout ID) do not trigger a retry storm.
    """
    if _RATE_LIMIT_EXCEPTIONS and isinstance(error, _RATE_LIMIT_EXCEPTIONS):
        return True
    if getattr(error, "code", None) == 429 or getattr(error, "status_code", None) == 429:
        return True
    if "RESOURCE_EXHAUSTED" in str(getattr(error, "status", "")).upper():
        return True
    message = str(error)
    return "RESOURCE_EXHAUSTED" in message or "429 " in message or "Too Many Requests" in message


async def run_node_with_retry(
    ctx: Context,
    node_or_agent: Any,
    node_input: Any = None,
    raise_on_wait: bool = False,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 4.0,
) -> Any:
    """Wraps ctx.run_node with exponential backoff on rate-limit errors.

    Only used for idempotent nodes (the TrainingPeaks profile lookup). LLM agents
    retry at the model call instead (see `_model`), so a 429 never replays tool
    calls such as `create_workout`.
    """
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            return await ctx.run_node(node_or_agent, node_input=node_input, raise_on_wait=raise_on_wait)
        except Exception as e:
            if not _is_rate_limit_error(e) or attempt >= max_retries:
                raise
            logger.warning(
                "Rate limited; retrying in %.1fs (attempt %d/%d)", delay, attempt, max_retries
            )
            await asyncio.sleep(delay)
            delay *= backoff_factor
    raise ValueError("max_retries must be >= 1")


# ==============================================================================
# Models (override with COACH_MODEL / ONBOARDING_MODEL env vars)
# ==============================================================================
COACH_MODEL = os.getenv("COACH_MODEL", "gemini-3.8-flash")
ONBOARDING_MODEL = os.getenv("ONBOARDING_MODEL", "gemini-3.1-flash-lite")

# Retry 429s at the model call (same schedule as run_node_with_retry).
_MODEL_RETRY = types.HttpRetryOptions(attempts=3, initial_delay=2, exp_base=4, http_status_codes=[429])


def _model(name: str) -> Gemini:
    return Gemini(model=name, retry_options=_MODEL_RETRY)


# ==============================================================================
# 1. Onboarding Agent - TASK MODE
# ==============================================================================
class OnboardingAnswers(BaseModel):
    age: Optional[str] = Field(None, description="Age of the runner")
    height: Optional[str] = Field(None, description="Height of the runner")
    weight: Optional[str] = Field(None, description="Weight of the runner")
    location: Optional[str] = Field(None, description="Location of the runner")
    training_goal: Optional[str] = Field(
        None,
        description=(
            "Goal as '<target time> <distance>' or 'Finish <distance>', "
            "e.g. 'Sub-3:30 Marathon', 'Sub-19:30 5K', 'Finish Half Marathon'"
        ),
    )
    timeline: Optional[str] = Field(None, description="Goal/race date as an ISO date string (YYYY-MM-DD)")
    recent_race_times: Optional[str] = Field(None, description="Recent race or time trial times")
    injuries: Optional[str] = Field(None, description="Past or present injuries")
    cross_training_strength: Optional[str] = Field(None, description="Cross-training or strength work")
    shoe_rotation: Optional[str] = Field(None, description="Current shoe rotation (e.g. shoes for easy runs, tempo runs, intervals, race days)")


onboarding_agent = Agent(
    model=_model(ONBOARDING_MODEL),
    name="onboarding_agent",
    description="Onboarding assistant that gathers runner profile details.",
    instruction="""
    You are the onboarding assistant for the AI Running Coach. Your sole job is to gather the profile information needed to build or update the runner's training plan.

    Data we already have (from TrainingPeaks or their existing profile):
    {temp_onboarding_data?}

    Fields to collect (skip any that already have a value above unless the runner wants to change it):
    1. Age
    2. Height and Weight
    3. Location / Where they live
    4. Training Goal: record it as "<target time> <distance>" or "Finish <distance>" (e.g. "Sub-3:30 Marathon", "Sub-19:30 5K", "Finish Half Marathon")
    5. Timeline: the goal/race date
    6. Recent Race Times / Time Trials (most recent 5K, 10K or half marathon)
    7. Past and Present Injuries
    8. Cross-Training & Strength Work
    9. Current Shoe Rotation (easy, tempo, intervals, race day)

    REQUIRED fields: `training_goal` and `timeline`. The others are optional; collect them if missing but do not insist.

    CRITICAL RULES:
    - If the runner already has a profile (the data above contains their details), greet them warmly, acknowledge their previous goal, and ask for their new training goal and race date.
    - Ask only 1 to 2 questions at a time, wait for the answer, acknowledge it, then move on.
    - `timeline` MUST be an ISO date string (YYYY-MM-DD, e.g. '2026-11-01'); convert whatever date the runner gives you.
    - Never use LaTeX formatting or dollar signs ($...$); output all text, numbers and units as plain text.
    - As soon as the required fields are collected and the missing optional fields have been asked once, call `finish_task` with the collected information. Do not keep chatting.

    GOAL REALISM CHECK (Required):
    - Once you have both the training goal and the recent race times, sanity-check the target against the time available.
      The stated goal drives every downstream fitness target and ramp-rate calculation, so an implausible goal
      silently corrupts all future coaching.
    - If the target is not physiologically plausible in the time remaining (for example, a large required
      improvement in race pace over only a few weeks, or a goal date too close to build the necessary aerobic base),
      say so directly and concretely: name the gap between their current fitness and the target, and propose a
      realistic alternative (a softer target time, or the same target with a later date).
    - Do not lecture and do not refuse. State the concern once, then record whatever goal the runner confirms.
    """,
    output_schema=OnboardingAnswers,
    mode="task",
)

# ==============================================================================
# 2. Coaching Agent - CHAT MODE
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

coaching_agent = Agent(
    model=_model(COACH_MODEL),
    name="coaching_agent",
    description="Expert running coach and physiologist that analyzes workouts and guides runners with objective, data-driven feedback.",
    instruction="""
    You are an expert running coach and exercise physiologist. Your coaching is analytical, direct, and grounded strictly in sports science and physiological data.
    
    Today's date is {current_date_str?}.

    RUNNER PROFILE:
    {user_profile_summary?}
    {expired_timeline_notice?}

    SKILL ROUTING: load the skill first, then follow its protocol exactly.
    - Analyze a completed run         -> workout-analysis      -> analyze_workout
    - Analyze a completed ride        -> bike-workout-analysis -> analyze_workout
    - Weekly check-in / progress      -> check-in-report       -> fetch_checkin_data (+ save_checkin_report)
    - Review / audit the plan         -> schedule-audit        -> fetch_schedule_audit_data
    - Fueling / hydration             -> nutrition-planner     -> fetch_nutrition_context
    - Create/change workouts or notes -> workout-creator       -> create_workout / create_note
    Do not reload a skill whose instructions are already in this conversation.
    New goal, or the goal date has passed -> request_new_goal. Ad-hoc weather -> get_weather.
    
    CRITICAL COACHING CONTRACT (Non-Negotiable):
    1. You are a coach, not an assistant. Your job is to protect the runner's long-term progression, including
       from their own enthusiasm. Agreement is not a service you provide.
    2. Challenge before complying. If a request conflicts with the data (recent training load, TSB, HRV/RHR
       trend, ramp rate, injury history, taper timing), state the specific physiological objection WITH the
       supporting numbers BEFORE you act. Then ask the runner to confirm. If they confirm, carry out the
       request and note the risk you flagged. Never silently comply, and never flatly refuse.
    3. Disagree explicitly when the runner's self-assessment conflicts with their data. If they call a session
       "easy" and the telemetry shows Zone 4 heart rate with 8% Pa:Hr drift, say so plainly. Never validate a
       claim the data contradicts.
    4. Hold your position. Do not reverse a data-backed judgement just because the runner pushes back. Change
       your assessment only when given NEW evidence (context you did not have, or a correction to the data).
       When there is no new evidence, say so: "The data still shows X."
    5. No filler praise. Never open with "Great question", "Awesome work" or similar. Lead with the assessment.
       Praise only specific, evidenced execution, and be equally specific about what went wrong.
    6. State uncertainty honestly. If data is missing, stale, or ambiguous, say so instead of producing a
       confident answer you cannot support.
    
    COACHING & REASONING PRINCIPLES:
    1. Objective, Data-Driven Appraisal: Provide honest, constructive feedback based on the metrics. Highlight genuine execution strengths and clearly identify flaws, breakdowns, or lack of discipline (e.g. running easy runs in the 'gray zone', blowing up interval pacing, or unmanaged cardiac drift) without empty cheerleading.
    2. Contextual Physiological Synthesis:
       - Aerobic Decoupling & Drift: Evaluate pace/power vs. heart rate (Pa:Hr / Pw:Hr) contextually. Differentiate between expected cardiovascular drift from environmental heat/humidity/hills versus true aerobic fatigue or poor pacing discipline.
       - Terrain & Grade (NGP): Compare Normalized Graded Pace against raw pace to accurately assess physiological effort on elevation changes.
       - Recovery & Readiness Context: Cross-reference workout execution against morning recovery indicators (HRV baseline, Resting Heart Rate, sleep duration) to identify fatigue accumulation or overreaching.
    3. Plain-Text & Markdown Formatting (No LaTeX):
       - Present all output in clean standard Markdown.
       - NEVER use LaTeX math mode, dollar-sign delimiters ($...$ or $$...$$), or LaTeX commands (e.g. \\rightarrow, \\to, \\text{...}, or math subscripts like $P_a:HR$).
       - For lap progressions and transitions, use standard text arrows (-> or →) or plain text words (e.g. "4:37/km -> 4:32/km" or "4:37/km to 4:32/km").
       - Format metric abbreviations in standard plain text: Pa:Hr (or Pace:HR decoupling), Pw:Hr, NGP, TSS, CTL, ATL, TSB, HR, bpm, W.
    """,
    tools=coaching_agent_tools,
    mode="chat",
)

# ==============================================================================
# 3. Workflow Nodes & Router
# ==============================================================================
ROUTE_ONBOARDING = "ONBOARDING"
ROUTE_COACHING = "COACHING"
ROUTE_UNAVAILABLE = "TP_UNAVAILABLE"

TP_UNAVAILABLE_MESSAGE = (
    "I couldn't reach TrainingPeaks to identify you just now, so I've paused rather than "
    "starting onboarding. Please send your message again in a moment."
)


async def _resolve_profile(ctx: Context) -> tuple[Optional[dict], bool]:
    """Resolves the runner's profile. Returns (profile, unavailable).

    Order: session state -> user-scoped `user:runner_id` (Firestore only, no
    TrainingPeaks call) -> TrainingPeaks identity lookup (first-ever session).
    `unavailable=True` means the runner couldn't be identified and must NOT be
    sent to onboarding.
    """
    profile = ctx.state.get("user_profile")
    if profile:
        return profile, False

    # Known runner: `user:` state is shared by all sessions of this ADK user_id.
    runner_id = ctx.state.get(RUNNER_ID_STATE_KEY)
    if runner_id:
        try:
            profile = await load_profile_by_id(ctx, runner_id)
        except Exception:
            logger.exception("Failed to load Firestore profile for %s", runner_id)
            return None, True
        if profile:
            return profile, False
        logger.warning("Stale %s=%r; falling back to TrainingPeaks.", RUNNER_ID_STATE_KEY, runner_id)
        ctx.state[RUNNER_ID_STATE_KEY] = None

    # First-ever session for this ADK user: identify via TrainingPeaks.
    try:
        tp_get_profile_tool = await get_tp_tool("tp_get_profile")
        tp_profile = await run_node_with_retry(ctx, tp_get_profile_tool)
    except Exception:
        logger.exception("Failed to fetch the TrainingPeaks profile")
        return None, True

    status = await check_profile_step(ctx, tp_profile)
    if status == PROFILE_TP_UNAVAILABLE:
        return None, True
    return ctx.state.get("user_profile"), False


def expired_timeline_notice(expired_date: str) -> str:
    """Instruction text shown to the coach once the runner's goal date has passed."""
    return (
        f"GOAL DATE PASSED: the runner's goal date ({expired_date}) is in the past. Before anything else, "
        f"warmly tell them and ask whether they want to (1) analyze their race/workout on {expired_date} "
        "or (2) set up a new training goal via `request_new_goal`."
    )


@node(name="profile_router", rerun_on_resume=True)
async def profile_router(ctx: Context, node_input: Any = None) -> None:
    """Dynamic runner state evaluation routing to onboarding or coaching."""
    ctx.state["current_date_str"] = get_today_str(with_weekday=True)

    profile, unavailable = await _resolve_profile(ctx)
    if unavailable:
        ctx.route = ROUTE_UNAVAILABLE
        return

    if not profile or ctx.state.get("reonboard_requested"):
        # Re-onboarding an existing runner: seed their known details (incl. name)
        # so create_profile_step can save, even if the profile came from state.
        if profile and not ctx.state.get("temp_onboarding_data"):
            ctx.state["temp_onboarding_data"] = onboarding_prefill(profile)
        ctx.route = ROUTE_ONBOARDING
        return

    # Keep the instruction's profile summary in sync with the stored profile.
    summary = format_profile_summary(profile)
    if ctx.state.get("user_profile_summary") != summary:
        ctx.state["user_profile_summary"] = summary

    is_expired, expired_date = check_timeline_expiration(profile)
    ctx.state["expired_timeline_date"] = expired_date if is_expired else None
    ctx.state["expired_timeline_notice"] = expired_timeline_notice(expired_date) if is_expired else ""

    ctx.route = ROUTE_COACHING


@node(name="tp_unavailable_node", rerun_on_resume=True)
async def tp_unavailable_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Tells the runner we couldn't identify them, instead of wrongly onboarding."""
    yield Event(author="model", message=TP_UNAVAILABLE_MESSAGE)


@node(name="onboarding_node", rerun_on_resume=True)
async def onboarding_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Runs the onboarding agent, persists the runner profile to Firestore, and emits confirmation."""
    onboarding_answers = await ctx.run_node(onboarding_agent, node_input=node_input, raise_on_wait=True)
    if not onboarding_answers:
        return

    ctx.state["onboarding_answers"] = onboarding_answers
    if not await create_profile_step(ctx):
        yield Event(
            author="model",
            message="I couldn't save your profile because I don't know your name yet. Please try again in a moment.",
        )
        return
    ctx.state["reonboard_requested"] = None
    ctx.state["expired_timeline_date"] = None
    ctx.state["expired_timeline_notice"] = ""

    firstname = (ctx.state.get("user_profile") or {}).get("firstname", "Runner")
    yield Event(
        author="model",
        message=f"Awesome, {firstname}! Your runner profile and goal are updated in Firestore. We are ready for active coaching!",
    )


@node(name="coaching_node", rerun_on_resume=True)
async def coaching_node(ctx: Context, node_input: Any = None) -> None:
    """Runs the coaching agent for active interactive running guidance."""
    await ctx.run_node(coaching_agent, node_input=node_input, raise_on_wait=True)


# ==============================================================================
# 4. Root Workflow & Application
# ==============================================================================
root_agent = Workflow(
    name="running_coach_workflow",
    edges=[
        ("START", profile_router),
        (
            profile_router,
            {
                ROUTE_ONBOARDING: onboarding_node,
                ROUTE_COACHING: coaching_node,
                ROUTE_UNAVAILABLE: tp_unavailable_node,
            },
        ),
    ],
)

app = App(
    name="running_coach",
    root_agent=root_agent,
    plugins=[AutoTracingPlugin()],
    # Sessions auto-resume, so compact history instead of growing it forever. The root is a
    # Workflow (not an LlmAgent), so the summarizer model must be given explicitly.
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=10,
        overlap_size=2,
        summarizer=LlmEventSummarizer(llm=_model(ONBOARDING_MODEL)),
    ),
)
