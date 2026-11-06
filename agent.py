import asyncio
import logging
import os
from typing import Any, AsyncGenerator, Literal, Optional

from google.adk import Agent, Context, Event, Workflow
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.google_llm import Gemini
from google.adk.plugins.auto_tracing_plugin import AutoTracingPlugin
from google.adk.workflow import node
from google.genai import types
from pydantic import BaseModel, Field

from .callbacks import apply_thinking_policy, no_workout_reply, splice_tables
from .services.config import dev_runner_email, web_app_url
from .services.tp_credentials import has_tp_credential
from .steps import (
    PROFILE_EMAIL_CONFLICT,
    PROFILE_NO_NAME,
    activate_profile,
    create_profile_step,
    find_profile_by_email,
)
from .tools import (
    analyze_workout_tool,
    create_note_tool,
    create_workout_tool,
    fetch_checkin_data_tool,
    fetch_nutrition_context_tool,
    fetch_schedule_audit_data_tool,
    fetch_trend_data_tool,
    get_weather_tool,
    request_new_goal_tool,
    skill_toolset,
)
from .utils import (
    AUTH_EMAIL_STATE_KEY,
    email_from_user_id,
    final_race_passed,
    format_goal_plan,
    format_profile_summary,
    get_today_date,
    get_today_str,
    needs_onboarding,
    next_block,
    normalize_email,
    onboarding_prefill,
    sub_goals_missing_result,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Models
# ==============================================================================
COACH_MODEL = os.getenv("COACH_MODEL", "gemini-3.8-flash")
ONBOARDING_MODEL = os.getenv("ONBOARDING_MODEL", "gemini-3.1-flash-lite")

# Retry 429s at the model call so tool side effects are never replayed.
_MODEL_RETRY = types.HttpRetryOptions(attempts=3, initial_delay=2, exp_base=4, http_status_codes=[429])


def _model(name: str) -> Gemini:
    return Gemini(model=name, retry_options=_MODEL_RETRY)


# ==============================================================================
# Onboarding agent
# ==============================================================================
class SubGoalAnswer(BaseModel):
    goal: str = Field(description="Sub goal as '<target time> <distance>', e.g. 'Sub-21 5K'")
    race_name: Optional[str] = Field(None, description="Name of the race that finishes this block")
    start_date: str = Field(description="Training block start date as ISO (YYYY-MM-DD)")
    race_date: str = Field(description="Race date that finishes the block, as ISO (YYYY-MM-DD)")


class OnboardingAnswers(BaseModel):
    age: Optional[str] = Field(None, description="Age of the runner")
    height: Optional[str] = Field(None, description="Height of the runner")
    weight: Optional[str] = Field(None, description="Weight of the runner")
    location: Optional[str] = Field(None, description="Location of the runner")
    goal_type: Optional[Literal["single", "plan"]] = Field(
        None,
        description="'single' = a goal for one specific race; 'plan' = a north star with multiple sub goals",
    )
    training_goal: Optional[str] = Field(
        None,
        description=(
            "Single goal only. Goal as '<target time> <distance>' or 'Finish <distance>', "
            "e.g. 'Sub-3:30 Marathon', 'Sub-19:30 5K', 'Finish Half Marathon'"
        ),
    )
    timeline: Optional[str] = Field(None, description="Single goal only. Race date as an ISO date string (YYYY-MM-DD)")
    north_star_goal: Optional[str] = Field(None, description="Plan only. North star goal, e.g. 'Sub-3:15 Marathon'")
    north_star_race_name: Optional[str] = Field(None, description="Plan only. North star race, e.g. 'London Marathon 2028'")
    north_star_race_date: Optional[str] = Field(None, description="Plan only. North star race date (YYYY-MM-DD)")
    north_star_start_date: Optional[str] = Field(
        None,
        description="Plan only, optional. Start of the north-star training block (YYYY-MM-DD); "
        "empty = the day after the last sub-goal race",
    )
    sub_goals: list[SubGoalAnswer] = Field(
        default_factory=list,
        description="Plan only. Sub goals in order; each is a full training block finishing with a race",
    )
    recent_race_times: Optional[str] = Field(None, description="Recent race or time trial times")
    injuries: Optional[str] = Field(None, description="Past or present injuries")
    cross_training_strength: Optional[str] = Field(None, description="Cross-training or strength work")
    shoe_rotation: Optional[str] = Field(None, description="Current shoe rotation (e.g. shoes for easy runs, tempo runs, intervals, race days)")
    taper_weeks: Optional[float] = Field(
        None,
        description=(
            "Optional preferred pre-race taper length in weeks (e.g. 2 or 3) for the goal race "
            "(the north star race in a plan). Leave empty to use the distance default "
            "(marathon/ultra 3, half/10 mile 2, 5K/10K 1)."
        ),
    )


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
    4. Goal type. Ask first: "Do you want to set a goal for a specific race, or a north star with multiple sub goals?"
       - Single goal (`goal_type` = "single"):
         a. Training Goal: record it as "<target time> <distance>" or "Finish <distance>" (e.g. "Sub-3:30 Marathon", "Sub-19:30 5K", "Finish Half Marathon")
         b. Timeline: the goal/race date
       - Goal plan (`goal_type` = "plan"):
         a. North star: goal ("Sub-3:15 Marathon"), race name and race date
         b. Sub goals, in order. Each sub goal is a full training block: goal ("Sub-21 5K"), block start date,
            and the race (name and date) that finishes the block
         c. Optional: the start date of the north-star training block (default: the day after the last sub-goal race)
    5. Recent Race Times / Time Trials (most recent 5K, 10K or half marathon)
    6. Past and Present Injuries
    7. Cross-Training & Strength Work
    8. Current Shoe Rotation (easy, tempo, intervals, race day)
    9. Preferred Taper Length in weeks for the goal race (optional; if they have no preference leave it empty and the distance default is used)

    REQUIRED fields:
    - Single goal: `goal_type`, `training_goal` and `timeline`.
    - Goal plan: `goal_type`, `north_star_goal`, `north_star_race_date` and at least one sub goal with `goal`, `start_date` and `race_date`.
    The others are optional; collect them if missing but do not insist.

    CRITICAL RULES:
    - If the runner already has a profile (the data above contains their details), greet them warmly, acknowledge their previous goal (or goal plan), and ask for their new goal type and goal(s).
    - Ask only 1 to 2 questions at a time, wait for the answer, acknowledge it, then move on.
    - All dates MUST be ISO date strings (YYYY-MM-DD, e.g. '2026-11-01'); convert whatever date the runner gives you.
    - Never use LaTeX formatting or dollar signs ($...$); output all text, numbers and units as plain text.
    - As soon as the required fields are collected and the missing optional fields have been asked once, call `finish_task` with the collected information. Do not keep chatting.

    GOAL REALISM CHECK (Required):
    - Once you have the goal(s) and the recent race times, sanity-check the target against the time available.
      The stated goal drives every downstream fitness target and ramp-rate calculation, so an implausible goal
      silently corrupts all future coaching.
    - If the target is not physiologically plausible in the time remaining (for example, a large required
      improvement in race pace over only a few weeks, or a goal date too close to build the necessary aerobic base),
      say so directly and concretely: name the gap between their current fitness and the target, and propose a
      realistic alternative (a softer target time, or the same target with a later date).
    - For a goal plan, also check once that: the blocks are in date order and do not overlap; every block is long
      enough to train for its distance; all sub goals finish before the north-star block; and the sub-goal targets
      form a coherent progression toward the north star (equivalent performances, e.g. via Riegel).
    - Do not lecture and do not refuse. State the concern once, then record whatever goal(s) the runner confirms.
    """,
    output_schema=OnboardingAnswers,
    mode="task",
)

# ==============================================================================
# Coaching agent
# ==============================================================================
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

_COACH_ROLE = (
    "You are an expert running coach and exercise physiologist. Your coaching is analytical, direct, "
    "and grounded strictly in sports science and physiological data."
)

# Static coaching rules; `build_coach_instruction` adds the profile-based header and, for goal
# plans only, `_GOAL_PLAN_LENS`. Sent on every model call, so keep them tight: task-specific
# analysis guidance belongs in the skills.
_ROUTING_RULES = """
    SKILL ROUTING: in the SAME step, call `load_skill` AND the skill's data tool in parallel
    (e.g. load_skill("check-in-report") + fetch_checkin_data()), then follow the skill's protocol exactly
    on the returned data. Write tools (create_workout, create_note) only run when the skill's protocol
    says so.
    - Analyze a completed run         -> workout-analysis      -> analyze_workout
    - Analyze a completed ride        -> bike-workout-analysis -> analyze_workout
    - Check-in (last 2 weeks + next week: status, trajectory, next-week priorities)
                                      -> check-in-report       -> fetch_checkin_data
    - Trends (6+ weeks: progress, load capacity, pacing, training patterns)
                                      -> trend-analysis        -> fetch_trend_data
    - Review / audit the plan         -> schedule-audit        -> fetch_schedule_audit_data
    - Fueling / hydration             -> nutrition-planner     -> fetch_nutrition_context
    - Create/change workouts or notes -> workout-creator       -> fetch_schedule_audit_data, then create_workout / create_note
    Do not reload a skill whose instructions are already in this conversation; just call its data tool.
    New goal (the runner accepts setting one) -> request_new_goal. Ad-hoc weather -> get_weather.

    CHECK-IN vs TREND: route on the time horizon of the question.
    - Check-in: "checking in", "how was my week", "am I on track", "ready for next week".
    - Trend: "since <date>", "over the last months", "this block", "what works for me", "how much volume can
      I handle", "what pace should my easy runs be", "can I run my workouts faster", "compare with <period>".
    - No horizon ("How am I progressing?"): check-in, then end with one line offering the long-term trend.
    - Never call fetch_checkin_data and fetch_trend_data in the same turn.
"""

_GOAL_PLAN_LENS = """
    GOAL PLAN LENS:
    1. The current block's sub goal is a step toward the north star, never the end point. Judge results, workouts
       and plan changes on both levels: the sub goal, and what it means for the north star. Use the north-star
       equivalents and gaps provided; do not recompute them.
    2. Sub-goal race results are progress, never pass/fail and never a reason to reschedule. Report the trend of
       north-star equivalents across the completed blocks.
    3. Protect the north star: push back on block choices that erode the aerobic base the marathon needs
       (e.g. long runs below the long-run target the tools report, or a collapse in weekly volume). Use the
       tools' long-run target as the only long-run distance guidance. The north-star peak CTL range is shown
       as context.
    4. Riegel equivalents are optimistic for the marathon without marathon-specific volume; say so when you use them.
    5. A sub-goal race never ends the plan: never offer onboarding or a new goal because a sub goal finished.
"""

_CONTRACT_RULES = """
    CRITICAL COACHING CONTRACT (Non-Negotiable):
    1. You are a coach, not an assistant. Your job is to protect the runner's long-term progression, including
       from their own enthusiasm. Agreement is not a service you provide.
    2. Challenge before complying. If a request conflicts with the data (recent training load, TSB, HRV/RHR
       trend, ramp rate, injury history, taper timing), state the specific physiological objection WITH the
       supporting numbers BEFORE you act. Then ask the runner to confirm. If they confirm, carry out the
       request and note the risk you flagged. Never silently comply, and never flatly refuse.
    3. Disagree explicitly when the runner's self-assessment conflicts with their data. If they call a session
       "easy" and the telemetry shows Zone 4 heart rate with 8% Pa:Hr drift, say so plainly. Never validate a
       claim the data contradicts (e.g. easy runs in the gray zone, blown interval pacing, unmanaged drift).
    4. Hold your position. Do not reverse a data-backed judgement just because the runner pushes back. Change
       your assessment only when given NEW evidence (context you did not have, or a correction to the data).
       When there is no new evidence, say so: "The data still shows X."
    5. No filler praise. Never open with "Great question", "Awesome work" or similar. Lead with the assessment.
       Praise only specific, evidenced execution, and be equally specific about what went wrong.
    6. State uncertainty honestly. If data is missing, stale, or ambiguous, say so instead of producing a
       confident answer you cannot support.

    FORMATTING: clean standard Markdown. NEVER use LaTeX ($...$, $$...$$, \\rightarrow, \\text{...},
    subscripts like $P_a:HR$). Use text arrows ("4:37/km -> 4:32/km" or →) and plain metric names: Pa:Hr,
    Pw:Hr, NGP, TSS, CTL, ATL, TSB, HR, bpm, W.
"""


def final_race_notice(race_date: str) -> str:
    """Notice once the final goal race (single goal or north star) is in the past. Never forces onboarding."""
    return (
        f"GOAL RACE DONE: the runner's goal race ({race_date}) is in the past. If it has not been discussed in this "
        f"conversation yet: congratulate them, then load workout-analysis and run analyze_workout for {race_date}. "
        "After the race analysis (or if they decline it), offer to set up a new goal via `request_new_goal`. "
        "Keep offering it briefly at the end of your replies until they accept; never force it, and do not plan "
        "training for the finished goal."
    )


def sub_goal_result_notice(block: dict, following: Optional[dict]) -> str:
    """Notice for a finished sub-goal race without a saved result."""
    next_text = f" The next block is {following['training_goal']}." if following else ""
    return (
        f"SUB-GOAL RACE DONE: sub goal {block['training_goal']} was raced on {block['timeline']} and has no result "
        f"yet. Congratulate the runner, ask how the race went, and run analyze_workout for {block['timeline']} "
        "(this saves the result to the goal plan). If TrainingPeaks has no run on that date, ask the runner to "
        "upload or sync the race to TrainingPeaks, then analyze it. Frame the result as progress toward the north "
        f"star, not pass/fail.{next_text} Do not offer onboarding."
    )


def goal_notice(profile: dict, today: Any = None) -> str:
    """Date-driven goal notices for the coach (computed from the profile, never stored)."""
    finished = final_race_passed(profile, today)
    if finished:
        return final_race_notice(str(finished["timeline"]))
    missing = sub_goals_missing_result(profile, today)
    if missing:
        block = missing[-1]  # the most recent race first; older ones surface once it is saved
        return sub_goal_result_notice(block, next_block(profile, block))
    return ""


def build_coach_instruction(ctx: ReadonlyContext) -> str:
    """InstructionProvider: the coach instruction, derived from `user_profile` on every model call.

    State only holds the stored profile; the date, profile summary, goal plan and notices
    are computed here so nothing is duplicated in session state.
    """
    profile = ctx.state.get("user_profile") or {}
    today = get_today_date()
    sections = [
        _COACH_ROLE,
        f"Today's date is {get_today_str(with_weekday=True)}.",
        f"RUNNER PROFILE:\n{format_profile_summary(profile, today)}",
    ]
    goal_plan = format_goal_plan(profile, today)
    if goal_plan:
        sections.append(goal_plan)
    notice = goal_notice(profile, today)
    if notice:
        sections.append(notice)
    rules = _ROUTING_RULES + (_GOAL_PLAN_LENS if goal_plan else "") + _CONTRACT_RULES
    return "\n\n".join(sections) + "\n" + rules


coaching_agent = Agent(
    model=_model(COACH_MODEL),
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

# ==============================================================================
# Workflow nodes and router
# ==============================================================================
ROUTE_ONBOARDING = "ONBOARDING"
ROUTE_COACHING = "COACHING"
ROUTE_NOT_LINKED = "NOT_LINKED"
ROUTE_TP_NOT_CONNECTED = "TP_NOT_CONNECTED"
ROUTE_UNAVAILABLE = "PROFILE_UNAVAILABLE"

PROFILE_UNAVAILABLE_MESSAGE = (
    "I couldn't load your runner profile from Firestore just now, so I've paused rather than "
    "starting onboarding. Please send your message again in a moment."
)


def _caller_email(ctx: Context) -> Optional[str]:
    """Resolves the caller's email across Web (`user:auth_email`), GE (`user_id`), and local dev."""
    auth_email = normalize_email(ctx.state.get(AUTH_EMAIL_STATE_KEY))
    if auth_email:
        return auth_email
    session_uid = getattr(getattr(ctx, "session", None), "user_id", None)
    return email_from_user_id(session_uid) or dev_runner_email()


def _not_linked_message(email: Optional[str]) -> str:
    who = f" ({email})" if email else ""
    url = web_app_url()
    where = f"open the Running Coach web app ({url})" if url else "open the Running Coach web app"
    return (
        f"No runner profile is linked to your account{who} yet — "
        f"{where} to connect TrainingPeaks and set up your profile."
    )


def _tp_not_connected_message() -> str:
    url = web_app_url()
    where = f"in the Running Coach web app ({url})" if url else "in the Running Coach web app"
    return (
        f"Your runner profile doesn't have an active TrainingPeaks connection yet. "
        f"Please reconnect TrainingPeaks from your profile {where}, then message me again."
    )


@node(name="profile_router", rerun_on_resume=True)
async def profile_router(ctx: Context, node_input: Any = None) -> None:
    """Identifies the runner by email and routes. No TrainingPeaks call, no shared credential.

    Web turns set `user:auth_email` and always reload Firestore so profile edits apply immediately.
    Gemini Enterprise and evals reuse a session-cached `user_profile` when already present.
    """
    auth_email = normalize_email(ctx.state.get(AUTH_EMAIL_STATE_KEY))
    profile = None if auth_email else ctx.state.get("user_profile")
    if not profile:
        email = _caller_email(ctx)
        if not email:
            ctx.route = ROUTE_NOT_LINKED
            return
        try:
            found = await find_profile_by_email(email)
            connected = bool(found) and await has_tp_credential(found[0])
        except Exception:
            logger.exception("Failed to resolve the runner profile for %s", email)
            ctx.route = ROUTE_UNAVAILABLE
            return
        if not found:
            ctx.route = ROUTE_NOT_LINKED
            return
        if not connected:
            ctx.route = ROUTE_TP_NOT_CONNECTED
            return
        profile = await activate_profile(ctx, *found)

    if needs_onboarding(profile) or ctx.state.get("reonboard_requested"):
        ctx.state["temp_onboarding_data"] = onboarding_prefill(profile)
        ctx.route = ROUTE_ONBOARDING
        return

    ctx.route = ROUTE_COACHING


@node(name="not_linked_node", rerun_on_resume=True)
async def not_linked_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Directs an unlinked account to the web app to connect TrainingPeaks and create a profile."""
    yield Event(author="model", message=_not_linked_message(_caller_email(ctx)))


@node(name="tp_not_connected_node", rerun_on_resume=True)
async def tp_not_connected_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Directs a runner whose profile lacks an encrypted TrainingPeaks cookie to reconnect."""
    yield Event(author="model", message=_tp_not_connected_message())


@node(name="profile_unavailable_node", rerun_on_resume=True)
async def profile_unavailable_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Tells the runner we couldn't load their profile, instead of wrongly onboarding."""
    yield Event(author="model", message=PROFILE_UNAVAILABLE_MESSAGE)


@node(name="onboarding_node", rerun_on_resume=True)
async def onboarding_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Runs the onboarding agent, persists the runner profile to Firestore, and emits confirmation."""
    onboarding_answers = await ctx.run_node(onboarding_agent, node_input=node_input, raise_on_wait=True)
    if not onboarding_answers:
        return

    ctx.state["onboarding_answers"] = onboarding_answers
    status = await create_profile_step(ctx)
    if status == PROFILE_NO_NAME:
        yield Event(
            author="model",
            message="I couldn't save your profile because I don't know your name yet. Please reconnect TrainingPeaks in the web app and try again.",
        )
        return
    if status == PROFILE_EMAIL_CONFLICT:
        yield Event(
            author="model",
            message="I couldn't save your profile because another account is already linked to that runner ID. Please contact an administrator.",
        )
        return
    ctx.state["reonboard_requested"] = None

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
# Root workflow and app
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
                ROUTE_NOT_LINKED: not_linked_node,
                ROUTE_TP_NOT_CONNECTED: tp_not_connected_node,
                ROUTE_UNAVAILABLE: profile_unavailable_node,
            },
        ),
    ],
)

app = App(
    name="running_coach",
    root_agent=root_agent,
    plugins=[AutoTracingPlugin()],
    # Compact session history; a Workflow root needs an explicit summarizer model.
    events_compaction_config=EventsCompactionConfig(
        compaction_interval=10,
        overlap_size=2,
        summarizer=LlmEventSummarizer(llm=_model(ONBOARDING_MODEL)),
    ),
)

