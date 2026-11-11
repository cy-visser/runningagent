from typing import Any, AsyncGenerator, Literal, Optional

from google.adk import Agent, Context, Event
from google.adk.workflow import node
from pydantic import BaseModel, Field

from ..model_config import ONBOARDING_MODEL, build_model
from .profile_creation import (
    PROFILE_EMAIL_CONFLICT,
    PROFILE_NO_NAME,
    create_profile_step,
)


class SubGoalAnswer(BaseModel):
    goal: str = Field(description="Sub goal as '<target time> <distance>', e.g. 'Sub-21 5K'")
    race_name: Optional[str] = Field(None, description="Name of the race that finishes this block")
    start_date: str = Field(description="Training block start date as ISO (YYYY-MM-DD)")
    race_date: str = Field(description="Race date that finishes the block, as ISO (YYYY-MM-DD)")


class PersonalRecordAnswer(BaseModel):
    time: str = Field(description="PR time as MM:SS or H:MM:SS, e.g. '19:45' or '1:27:48'")
    date: Optional[str] = Field(None, description="Date the PR was set, as ISO (YYYY-MM-DD), if known")


class PersonalRecordsAnswer(BaseModel):
    five_k: Optional[PersonalRecordAnswer] = Field(None, description="5K personal record")
    ten_k: Optional[PersonalRecordAnswer] = Field(None, description="10K personal record")
    ten_mile: Optional[PersonalRecordAnswer] = Field(None, description="10 mile personal record")
    half_marathon: Optional[PersonalRecordAnswer] = Field(None, description="Half marathon personal record")
    marathon: Optional[PersonalRecordAnswer] = Field(None, description="Marathon personal record")


class ShoeRotationAnswer(BaseModel):
    easy: Optional[str] = Field(None, description="Shoe for easy runs")
    tempo: Optional[str] = Field(None, description="Shoe for tempo/threshold runs")
    interval: Optional[str] = Field(None, description="Shoe for intervals")
    long_run: Optional[str] = Field(None, description="Shoe for long runs")
    race: Optional[str] = Field(None, description="Race-day shoe")


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
    timeline: Optional[str] = Field(
        None, description="Single goal only. Race date as an ISO date string (YYYY-MM-DD)"
    )
    north_star_goal: Optional[str] = Field(
        None, description="Plan only. North star goal, e.g. 'Sub-3:15 Marathon'"
    )
    north_star_race_name: Optional[str] = Field(
        None, description="Plan only. North star race, e.g. 'London Marathon 2028'"
    )
    north_star_race_date: Optional[str] = Field(
        None, description="Plan only. North star race date (YYYY-MM-DD)"
    )
    north_star_start_date: Optional[str] = Field(
        None,
        description="Plan only, optional. Start of the north-star training block (YYYY-MM-DD); "
        "empty = the day after the last sub-goal race",
    )
    sub_goals: list[SubGoalAnswer] = Field(
        default_factory=list,
        description="Plan only. Sub goals in order; each is a full training block finishing with a race",
    )
    personal_records: Optional[PersonalRecordsAnswer] = Field(
        None, description="Personal records per distance (5K, 10K, 10 mile, half marathon, marathon)"
    )
    injuries: Optional[str] = Field(None, description="Past or present injuries")
    run_time_of_day: Optional[Literal["morning", "afternoon", "evening"]] = Field(
        None, description="Part of the day the runner prefers to run"
    )
    strength_time_of_day: Optional[Literal["morning", "afternoon", "evening"]] = Field(
        None, description="Part of the day the runner prefers to do strength training"
    )
    shoe_rotation: Optional[ShoeRotationAnswer] = Field(
        None, description="Shoe per run type (easy, tempo/threshold, interval, long run, race)"
    )
    taper_weeks: Optional[float] = Field(
        None,
        description=(
            "Optional preferred pre-race taper length in weeks (e.g. 2 or 3) for the goal race "
            "(the north star race in a plan). Leave empty to use the distance default "
            "(marathon/ultra 3, half/10 mile 2, 5K/10K 1)."
        ),
    )


onboarding_agent = Agent(
    model=build_model(ONBOARDING_MODEL),
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
    5. Personal Records: time (and date, if known) for 5K, 10K, 10 mile, half marathon and marathon. Only the distances they have raced.
    6. Past and Present Injuries
    7. Training Times: when they prefer to run and when to do strength training, each as morning, afternoon or evening
       (e.g. run in the morning, strength in the evening). On a day with both, the plan follows this order.
    8. Shoe Rotation: which shoe for easy runs, tempo/threshold, intervals, long runs and races (any may be empty)
    9. Preferred Taper Length in weeks for the goal race (optional; if they have no preference leave it empty and the distance default is used)

    REQUIRED fields:
    - Single goal: `goal_type`, `training_goal` and `timeline`.
    - Goal plan: `goal_type`, `north_star_goal`, `north_star_race_date` and at least one sub goal with `goal`, `start_date` and `race_date`.
    - Always: `run_time_of_day` and `strength_time_of_day` (morning, afternoon or evening).
    The others are optional; collect them if missing but do not insist.

    CRITICAL RULES:
    - If the runner already has a profile (the data above contains their details), greet them warmly, acknowledge their previous goal (or goal plan), and ask for their new goal type and goal(s).
    - Ask only 1 to 2 questions at a time, wait for the answer, acknowledge it, then move on.
    - All dates MUST be ISO date strings (YYYY-MM-DD, e.g. '2026-11-01'); convert whatever date the runner gives you.
    - Never use LaTeX formatting or dollar signs ($...$); output all text, numbers and units as plain text.
    - As soon as the required fields are collected and the missing optional fields have been asked once, call `finish_task` with the collected information. Do not keep chatting.

    GOAL REALISM CHECK (Required):
    - Once you have the goal(s) and the personal records (weigh recent PRs more than old ones), sanity-check the target against the time available.
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


@node(name="onboarding_node", rerun_on_resume=True)
async def onboarding_node(ctx: Context, node_input: Any = None) -> AsyncGenerator[Any, None]:
    """Runs the onboarding agent, persists the runner profile to Firestore, and emits confirmation."""
    onboarding_answers = await ctx.run_node(
        onboarding_agent, node_input=node_input, raise_on_wait=True
    )
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
