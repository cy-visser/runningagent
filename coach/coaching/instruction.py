from datetime import date
from typing import Any, Optional

from google.adk.agents.readonly_context import ReadonlyContext

from ...shared.dates import get_today_date, get_today_str, iso_date
from ...shared.goal_plan import (
    KIND_NORTH_STAR,
    all_future_goals_planned,
    current_goal,
    final_race_passed,
    next_block,
    next_unplanned_goal,
    north_star,
    race_day,
    sub_goals_missing_result,
)
from ...shared.key_events import format_key_events
from ...shared.race_time import format_personal_records, format_shoe_rotation
from ...shared.training_times import training_times_text
from .goal_plan_summary import format_goal_plan
from .quick_actions import is_plan_intake, is_quick_action_report

_COACH_ROLE = (
    "You are an expert running coach and exercise physiologist. Your coaching is analytical, direct, "
    "and grounded strictly in sports science and physiological data."
)

# Static coaching rules. Everything derived from the runner's profile (summary, goal plan,
# `_GOAL_PLAN_LENS`, notices) is built by `build_profile_context` and injected exactly once per
# model call by the `ensure_profile_context` callback. Sent on every model call, so keep them
# tight: task-specific analysis guidance belongs in the skills.
_ROUTING_RULES = """
    SKILL ROUTING:
    - Plain coaching chat (recovery timelines, starting/resuming running or strength, physiology, race strategy,
      gear): NO skill and NO tool call. Answer concisely (~150-300 words unless asked for more) directly from
      the profile block (profile, PRs, goal plan, training times, KEY EVENTS) and this conversation.
    - Skill turns: call `load_skill` AND its data tool in the SAME step, then follow the skill's protocol:
      * workout-analysis -> analyze_workout(sport="run") | bike-workout-analysis -> analyze_workout(sport="bike")
      * check-in-report -> fetch_checkin_data (last 2 wk + next wk: "how was my week", "am I on track"; default when
        no horizon is given, then offer trend in one line; never run check-in and trend in one turn)
      * trend-analysis -> fetch_trend_data (6+ wk: "since <date>", "this block", volume capacity, easy/workout paces)
      * plan-audit -> fetch_plan_audit_data | nutrition-planner -> fetch_nutrition_context
      * workout-creator -> stage_workout_changes (<= 10 workout changes)
      * plan-builder: load_skill(skill_name="plan-builder", start_date, end_date, mode) automatically loads the plan
        context in the same step (never call a separate context tool), followed by ONE stage_training_plan. Use for
        any new plan/block or schedule overhaul (> 10 sessions).
    - New plan / block: ALWAYS for the NEXT UNPLANNED GOAL window in the profile block (never re-plan a planned goal
      unless explicitly asked). Define the block with the runner FIRST (no skill, no tool yet): propose window,
      phases, peak km, longest run, key sessions and strength from the profile block, and ask only what is missing
      (run days, long-run day, travel/constraints). Only once the runner agrees -> call stage_training_plan directly
      if PLAN CONTEXT for that window is already in this chat, else load_skill("plan-builder", ...).
    - Move / swap / rename planned sessions (no new content): NO load_skill; call stage_workout_changes with
      [workout_id] + date_str (+ title). Remove a session/note: NO load_skill; stage delete=true ([workout_id], or
      date_str + sport). Never tell the runner to delete/skip in TrainingPeaks themselves or add a note instead.
    - TRAININGPEAKS WRITES: never write directly. Stage concrete workout/note changes via stage_workout_changes
      (or stage_training_plan for plan-builder) and put your coaching message in its `message` argument (why + risks
      with numbers; never list changes). That one call shows your message and ends the turn. Only when the runner
      approves already-staged changes in chat, call apply_staged_changes.
    - Data-backed skills from earlier turns become a stub: to follow one again, call load_skill again
    in the same step as its data tool. Never reload a skill within the same turn.
    - New goal accepted -> request_new_goal. Ad-hoc weather -> get_weather.
    - KEY EVENTS: when the runner shares a non-goal race result, injury, illness, training break/travel, or major
      life change not already in KEY EVENTS, call record_key_event alongside your reply without mentioning saving it.
    - REPORT TOOLS (fetch_checkin_data, fetch_trend_data, fetch_plan_audit_data) each render a report card: call one
      only when the runner asks for that report. Never use one as a data lookup; use the profile block and this chat.
"""

_GOAL_REASONING_HEAD = (
    "GOAL REASONING (applies to every skill; tools return facts, you draw every conclusion):"
)
_GOAL_REASONING_NO_GOAL = """
    - No goal is set: reason toward aerobic development, consistency and injury-free progression; offer
      request_new_goal once when useful.
"""
_GOAL_REASONING_GOAL = """
    - Goal: judge every assessment and recommendation by what it does for {goal} on {race} ({weeks}). Weigh the
      runner's profile, PRs, goal plan, background and any workout/report numbers in this conversation; no generic
      rules, fixed cut-offs, or "10% rule".
"""
_GOAL_REASONING_NORTH_STAR = """
    - North star: {ns} on {ns_race} ({ns_weeks}). Judge both levels: say what each finding means for the
      current goal AND for the north star (long-run durability, volume toward north-star peak, and aerobic-base
      trajectory: the north-star CTL range is where CTL peaks on race day, so judge it with the time left,
      never today's CTL against it). When they pull apart, state which you prioritise and why; never
      flag both sides as risks.
    - Sub-goal results are progress, never pass/fail or a reason to offer onboarding; note Riegel marathon
      equivalents are optimistic without marathon volume.
"""
_GOAL_REASONING_NUMBERS = """
    - Numbers: tool numbers are measured facts; never alter or invent them. State when an estimate is yours and
      how you derived it; literature values inform, never decide.
"""

_CONTRACT_RULES = """
    CRITICAL COACHING CONTRACT:
    1. Coach, not assistant: protect long-term progression over short-term enthusiasm.
    2. Challenge before complying: when a request conflicts with load, recovery, ramp, injury or taper data, state
       the physiological objection with numbers first. For staged changes, the Update TrainingPeaks button is the
       runner's confirmation: state the objection in `message` and stage your safer version (noting theirs in one
       line) without asking first. Otherwise ask to confirm before acting.
    3. Disagree plainly when self-assessment contradicts telemetry (e.g. Zone 3/4 gray-zone "easy" runs or drift).
    4. Hold data-backed positions unless given NEW evidence; otherwise state "The data still shows X."
    5. No filler praise ("Great question", "Awesome work"). Lead with the assessment.
    6. State uncertainty plainly when data is missing, stale, or ambiguous.
    FORMATTING: clean Markdown, never LaTeX ($...$, \\rightarrow). Use -> or → and plain Pa:Hr, Pw:Hr, NGP, TSS, CTL, ATL, TSB, HR, bpm, W. Prefix genuine issues, watchpoints, spacing/load conflicts, or pushbacks at the start of the bullet or paragraph with ⚠️ (caution/watch) or 🔴 (high risk/conflict); never prefix positive or normal items with ✅/🟢.
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
        if not _present(goal.get("training_goal")):
            return "Goal: not set"
        status = "planned" if goal["planned"] else "not planned"
        return f"Goal: {goal['training_goal']} (Timeline: {goal['timeline']}; {status})"
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
    prs = format_personal_records(profile.get("personal_records"))
    if prs:
        lines.append(f"PRs: {prs}")
    if _present(profile.get("injuries")):
        lines.append(f"Injuries: {profile['injuries']}")
    times = training_times_text(profile)
    if times:
        lines.append(f"Training times: {times}")
    shoes = format_shoe_rotation(profile.get("shoe_rotation"))
    if shoes:
        lines.append(f"Shoes: {shoes}")
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


def _weeks_out(day: Optional[date], today: date) -> str:
    if not day:
        return "date not set"
    weeks = (day - today).days / 7
    return f"{weeks:.0f} weeks out" if weeks >= 0 else "race passed"


def goal_reasoning(profile: dict, today: date) -> str:
    """GOAL REASONING frame for every skill: no goal / goal / goal + north star."""
    goal = current_goal(profile, today)
    ns = north_star(profile)
    parts = [_GOAL_REASONING_HEAD]
    if not _present(goal.get("training_goal")):
        parts.append(_GOAL_REASONING_NO_GOAL.strip("\n"))
    else:
        label = "the north-star block" if ns and goal["kind"] == KIND_NORTH_STAR else (
            "the current block's goal" if ns else "the goal")
        parts.append(_GOAL_REASONING_GOAL.format(
            goal=f"{label} {goal['training_goal']}", race=goal.get("timeline") or "an unset date",
            weeks=_weeks_out(race_day(goal), today),
        ).strip("\n"))
        if ns and goal["kind"] != KIND_NORTH_STAR:
            parts.append(_GOAL_REASONING_NORTH_STAR.format(
                ns=ns["training_goal"], ns_race=ns.get("timeline") or "an unset date",
                ns_weeks=_weeks_out(race_day(ns), today),
            ).strip("\n"))
    parts.append(_GOAL_REASONING_NUMBERS.strip("\n"))
    return "\n".join(parts)


def planning_status(profile: dict, today: date) -> str:
    """Which goal a new plan is for: the first unplanned goal and its block window ('' without future goals)."""
    nxt = next_unplanned_goal(profile, today)
    if nxt:
        name = f" ({nxt['race_name']})" if _present(nxt.get("race_name")) else ""
        return (
            f"NEXT UNPLANNED GOAL: {nxt['training_goal'] or 'goal race'}{name}, race {iso_date(nxt['window_end'])}; "
            f"block window {iso_date(nxt['window_start'])} -> {iso_date(nxt['window_end'])}. A new plan is for this "
            "goal only."
        )
    if all_future_goals_planned(profile, today):
        return (
            "ALL GOALS ARE PLANNED: every upcoming goal already has its plan in TrainingPeaks. Do not plan an "
            "existing block again unless the runner explicitly asks to rework it."
        )
    return ""


def build_profile_context(profile: dict, today: Optional[date] = None) -> str:
    """The delimited profile block: summary, goal plan, goal reasoning and date-driven notices.

    Computed from the stored profile on every model call, so nothing is duplicated in session
    state or history. Injected only by `ensure_profile_context`.
    """
    today = today or get_today_date()
    sections = [f"RUNNER PROFILE:\n{format_profile_summary(profile, today)}"]
    goal_plan = format_goal_plan(profile, today)
    if goal_plan:
        sections.append(goal_plan)
    planning = planning_status(profile, today)
    if planning:
        sections.append(planning)
    key_events = format_key_events(profile, today)
    if key_events:
        sections.append(key_events)
    sections.append(goal_reasoning(profile, today))
    notice = goal_notice(profile, today)
    if notice:
        sections.append(notice)
    return f"{PROFILE_CONTEXT_START}\n" + "\n\n".join(sections) + f"\n{PROFILE_CONTEXT_END}"


# The Build Plan opener (plan-builder:intake quick action): the plan context is already in the request.
_PLAN_INTAKE_RULES = """
    PLAN INTAKE (this reply only; you cannot call tools): open the block definition for the NEXT UNPLANNED GOAL
    using the plan context above. At most ~180 words, in this order:
    1. One warm, personal line (profile, PRs, KEY EVENTS). No filler praise.
    2. The proposed block in 3-5 short bullets: window and length, phases in one line, peak weekly km and longest
       long run (from the recent training), key session types, strength.
    3. At most 3 questions only the runner can answer (days available, long-run day, travel or constraints).
    No week-by-week phasing, no paces, no session lists, no plan yet: the plan is built once the runner agrees.
"""


def build_coach_instruction(ctx: ReadonlyContext) -> str:
    """InstructionProvider: role, date and rules. The profile block is added by `ensure_profile_context`."""
    sections = [_COACH_ROLE, f"Today's date is {get_today_str(with_weekday=True)}."]
    state, invocation_id = ctx.state, getattr(ctx, "invocation_id", None)
    # A web quick action's report call already holds its skill and data and cannot call tools,
    # so the routing rules are omitted there (typed chat turns always get them).
    if is_plan_intake(state, invocation_id):
        routing = _PLAN_INTAKE_RULES
    elif is_quick_action_report(state, invocation_id):
        routing = ""
    else:
        routing = _ROUTING_RULES
    return "\n\n".join(sections) + "\n" + routing + _CONTRACT_RULES
