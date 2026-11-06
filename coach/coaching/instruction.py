from datetime import date
from typing import Any, Optional

from google.adk.agents.readonly_context import ReadonlyContext

from ...shared.dates import get_today_date, get_today_str
from ...shared.goal_plan import (
    KIND_NORTH_STAR,
    current_goal,
    final_race_passed,
    next_block,
    north_star,
    sub_goals_missing_result,
)
from .goal_plan_summary import format_goal_plan
from .quick_actions import is_quick_action_report

_COACH_ROLE = (
    "You are an expert running coach and exercise physiologist. Your coaching is analytical, direct, "
    "and grounded strictly in sports science and physiological data."
)

# Static coaching rules. Everything derived from the runner's profile (summary, goal plan,
# `_GOAL_PLAN_LENS`, notices) is built by `build_profile_context` and injected exactly once per
# model call by the `ensure_profile_context` callback. Sent on every model call, so keep them
# tight: task-specific analysis guidance belongs in the skills.
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
    - Create/change workouts or notes -> workout-creator       -> create_workout / create_note (writes immediately; reports load warnings)
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


# Delimiters of the profile block in the system instruction; `ensure_profile_context` replaces
# an existing block instead of appending a second one.
PROFILE_CONTEXT_START = "<runner_profile>"
PROFILE_CONTEXT_END = "</runner_profile>"


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _goal_line(profile: dict, today: Optional[date]) -> str:
    """Goal line: the single goal, or the current block plus the north star for a plan."""
    goal = current_goal(profile, today)
    ns = north_star(profile)
    if not ns:
        return f"Goal: {goal['training_goal']} (Timeline: {goal['timeline']})"
    if goal["kind"] == KIND_NORTH_STAR:
        return f"Goal: North star {ns['training_goal']} (Race: {ns['timeline']}); final block"
    return (
        f"Goal: Current block {goal['training_goal']} (Race: {goal['timeline']}) -> "
        f"North star {ns['training_goal']} (Race: {ns['timeline']})"
    )


def _block_line(profile: dict, today: Optional[date]) -> str:
    """Current block details: race name, start date and taper override ('' when none are set)."""
    goal = current_goal(profile, today)
    parts = []
    if _present(goal.get("race_name")):
        parts.append(f"Race: {goal['race_name']}")
    if _present(goal.get("goal_set_date")):
        parts.append(f"Block start: {goal['goal_set_date']}")
    if _present(goal.get("taper_weeks")):
        parts.append(f"Taper override: {goal['taper_weeks']} weeks")
    return f"Current Block: {', '.join(parts)}" if parts else ""


def format_profile_summary(profile: dict, today: Optional[date] = None) -> str:
    """Formats a token-efficient summary of every coaching-relevant profile field.

    Empty fields are omitted. Identity plumbing (email, coordinates, onboarding flags) is left out.
    """
    if not profile:
        return ""
    name = " ".join(str(profile[k]).strip() for k in ("firstname", "lastname") if _present(profile.get(k)))
    age = f" (Age: {profile['age']})" if _present(profile.get("age")) else ""
    stats = ", ".join(
        f"{label}: {profile[key]}" for label, key in (("Height", "height"), ("Weight", "weight"))
        if _present(profile.get(key))
    )
    lines = [
        f"Name: {name}{age}" if name or age else "",
        f"Location: {profile['location']}" if _present(profile.get("location")) else "",
        f"Stats: {stats}" if stats else "",
        _goal_line(profile, today),
        _block_line(profile, today),
    ]
    for label, key in (
        ("Recent Races", "recent_race_times"),
        ("Injuries", "injuries"),
        ("Cross-Training", "cross_training_strength"),
        ("Shoe Rotation", "shoe_rotation"),
    ):
        if _present(profile.get(key)):
            lines.append(f"{label}: {profile[key]}")
    return "\n".join(line for line in lines if line)


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


def build_profile_context(profile: dict, today: Optional[date] = None) -> str:
    """The delimited profile block: summary, goal plan (+ lens) and date-driven notices.

    Computed from the stored profile on every model call, so nothing is duplicated in session
    state or history. Injected only by `ensure_profile_context`.
    """
    today = today or get_today_date()
    sections = [f"RUNNER PROFILE:\n{format_profile_summary(profile, today)}"]
    goal_plan = format_goal_plan(profile, today)
    if goal_plan:
        sections.extend([goal_plan, _GOAL_PLAN_LENS.strip("\n")])
    notice = goal_notice(profile, today)
    if notice:
        sections.append(notice)
    return f"{PROFILE_CONTEXT_START}\n" + "\n\n".join(sections) + f"\n{PROFILE_CONTEXT_END}"


def build_coach_instruction(ctx: ReadonlyContext) -> str:
    """InstructionProvider: role, date and rules. The profile block is added by `ensure_profile_context`."""
    sections = [_COACH_ROLE, f"Today's date is {get_today_str(with_weekday=True)}."]
    # A web quick action's report call already holds its skill and data and cannot call tools,
    # so the routing rules are omitted there (typed chat turns always get them).
    routing = "" if is_quick_action_report(ctx.state, getattr(ctx, "invocation_id", None)) else _ROUTING_RULES
    return "\n\n".join(sections) + "\n" + routing + _CONTRACT_RULES
