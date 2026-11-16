from datetime import date
from textwrap import dedent
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
# goal reasoning, notices) is built by `build_profile_context` and injected exactly once per
# model call by the `ensure_profile_context` callback. Sent on every model call, so keep them
# tight: task-specific analysis guidance belongs in the skills.
_ROUTING_RULES = dedent("""
    SKILL ROUTING:
    - Plain coaching chat (recovery, resuming running/strength, physiology, race strategy, gear): NO skill and NO tool.
      Answer concisely (~150-300 words unless asked for more) from the profile block and this chat.
    - Skill turns: call `load_skill` AND its data tool in the SAME step, then follow the skill:
      * workout-analysis -> analyze_workout(sport="run") | bike-workout-analysis -> analyze_workout(sport="bike")
      * check-in-report -> fetch_checkin_data (default when no horizon is given; offer trend in 1 line; never both)
      * trend-analysis -> fetch_trend_data (6+ wk, "since <date>", "this block", capacity, easy/workout paces)
      * plan-audit -> fetch_plan_audit_data | nutrition-planner -> fetch_nutrition_context
      * plan-builder (> 10 sessions or new block): load_skill("plan-builder", start_date, end_date, mode) loads plan
        context automatically, followed by ONE stage_training_plan.
    - New plan / block: ALWAYS for NEXT UNPLANNED GOAL in the profile block (never re-plan a planned goal unless asked).
      Define the block FIRST (no skill/tool yet): propose window, phases, peak km, longest run, key sessions & strength,
      and ask only missing constraints (run days, LR day, travel). Once agreed -> stage_training_plan if PLAN CONTEXT
      is already active, else load_skill("plan-builder", ...).
    - Planned workouts & notes (<= 10 changes): NO load_skill; call stage_workout_changes in ONE step (Move / swap / rename planned sessions (no new content): NO load_skill; use [workout_id] or from_date_str+sport, never delete+recreate; never tell the runner to edit/delete in TrainingPeaks themselves).
    - TRAININGPEAKS WRITES: never write directly. Stage via stage_workout_changes (or stage_training_plan) and put your coaching message in its `message` argument (why + risks with numbers; never list changes). That one call shows your message and ends the turn. Only on chat approval of staged changes, call apply_staged_changes.
    - Earlier-turn skills become stubs: to follow one again, call load_skill again
      in the same step as its data tool. Never reload a skill within the same turn.
    - New goal accepted -> request_new_goal. Ad-hoc weather -> get_weather.
    - KEY EVENTS: silently call record_key_event alongside your reply when the runner shares a new non-goal race result, injury, illness, break/travel, or major life change.
    - REPORT TOOLS (fetch_checkin_data, fetch_trend_data, fetch_plan_audit_data) each render a report card: only call when asked for that report. Never use one as a data lookup.
""").strip()

_GOAL_REASONING_HEAD = "GOAL REASONING:"
_GOAL_REASONING_NO_GOAL = (
    "- No goal is set: reason toward aerobic development, consistency & injury-free progression; "
    "offer request_new_goal once when useful."
)
_GOAL_REASONING_GOAL = (
    "- Goal: judge every assessment & recommendation for {goal} on {race} ({weeks}) from profile, PRs & chat numbers; "
    'no generic rules or "10% rule".'
)
_GOAL_REASONING_PLAN = (
    "- Judge every finding for BOTH current goal ({goal}) & north star ({ns}: LR durability, volume, CTL: "
    "judge it with the time left, never today's CTL against it); weigh profile/PRs/chat numbers, "
    'no generic/"10%" rules; when they pull apart, state priority & why, never flag both sides as risks; '
    "sub-goal results=progress (not pass/fail or re-onboard), Riegel M equivs need M volume."
)
_GOAL_REASONING_NUMBERS = (
    "- Numbers: never alter or invent tool numbers; state estimate math; literature informs only."
)

_CONTRACT_RULES = dedent("""
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
""").strip()

_NO_INJURY_TEXTS = frozenset({"no injuries", "no injuries.", "none", "none.", "n/a", "no", "nil"})

# Delimiters of the profile block in the system instruction; `ensure_profile_context` replaces
# an existing block instead of appending a second one.
PROFILE_CONTEXT_START = "<runner_profile>"
PROFILE_CONTEXT_END = "</runner_profile>"


def _present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _meaningful_injuries(value: Any) -> str:
    if not _present(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in _NO_INJURY_TEXTS else text


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
    """Current block details for single-goal profiles ('' when none are set)."""
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
    """Formats a compact, lossless summary of coaching-relevant profile fields."""
    if not profile:
        return ""
    name = " ".join(str(profile[k]).strip() for k in ("firstname", "lastname") if _present(profile.get(k)))
    meta = [
        *([f"Age {profile['age']}"] if _present(profile.get("age")) else []),
        *([str(profile[k]).strip() for k in ("height", "weight", "location") if _present(profile.get(k))]),
    ]
    who = f"{name} ({', '.join(meta)})" if name and meta else (name or ", ".join(meta))
    times = training_times_text(profile)
    if times:
        who = f"{who} · Training times: {times}" if who else f"Training times: {times}"

    has_plan = bool(north_star(profile))
    lines = [
        who,
        "" if has_plan else _goal_line(profile, today),
        "" if has_plan else _block_line(profile, today),
    ]
    prs = format_personal_records(profile.get("personal_records"))
    if prs:
        lines.append(f"PRs: {prs}")
    injuries = _meaningful_injuries(profile.get("injuries"))
    if injuries:
        lines.append(f"Injuries: {injuries}")
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
    return f"{weeks:.0f}w out" if weeks >= 0 else "race passed"


def goal_reasoning(profile: dict, today: date) -> str:
    """GOAL REASONING frame for every skill: no goal / goal / goal + north star."""
    goal = current_goal(profile, today)
    ns = north_star(profile)
    parts = [_GOAL_REASONING_HEAD]
    if not _present(goal.get("training_goal")):
        parts.append(_GOAL_REASONING_NO_GOAL)
    elif ns and goal["kind"] != KIND_NORTH_STAR:
        parts.append(
            _GOAL_REASONING_PLAN.format(
                goal=goal["training_goal"],
                ns=ns["training_goal"],
            )
        )
    else:
        label = "the north-star block" if ns and goal["kind"] == KIND_NORTH_STAR else "the goal"
        parts.append(
            _GOAL_REASONING_GOAL.format(
                goal=f"{label} {goal['training_goal']}",
                race=goal.get("timeline") or "an unset date",
                weeks=_weeks_out(race_day(goal), today),
            )
        )
    parts.append(_GOAL_REASONING_NUMBERS)
    return "\n".join(parts)


def planning_status(profile: dict, today: date) -> str:
    """Planning status line for single goals or when all future goals are already planned."""
    nxt = next_unplanned_goal(profile, today)
    if nxt:
        if north_star(profile):
            return ""  # already inlined on the matching goal bullet in `format_goal_plan`
        name = f" ({nxt['race_name']})" if _present(nxt.get("race_name")) else ""
        return (
            f"NEXT UNPLANNED GOAL: {nxt['training_goal'] or 'goal race'}{name}, "
            f"window {iso_date(nxt['window_start'])}..{iso_date(nxt['window_end'])}."
        )
    if all_future_goals_planned(profile, today):
        return "ALL GOALS ARE PLANNED: do not re-plan an existing block unless explicitly asked."
    return ""


def build_profile_context(profile: dict, today: Optional[date] = None) -> str:
    """The delimited profile block: summary, goal plan, goal reasoning and date-driven notices.

    Computed from the stored profile on every model call, so nothing is duplicated in session
    state or history. Injected only by `ensure_profile_context`.
    """
    today = today or get_today_date()
    summary = format_profile_summary(profile, today)
    first_lines = summary.splitlines()
    runner_head = f"RUNNER PROFILE: {first_lines[0]}" if first_lines else "RUNNER PROFILE:"
    runner_section = "\n".join([runner_head, *first_lines[1:]])
    sections = [runner_section]
    for block in (
        format_goal_plan(profile, today),
        planning_status(profile, today),
        format_key_events(profile, today),
        goal_reasoning(profile, today),
        goal_notice(profile, today),
    ):
        if block:
            sections.append(block)
    return f"{PROFILE_CONTEXT_START}\n" + "\n".join(sections) + f"\n{PROFILE_CONTEXT_END}"


# The Build Plan opener (plan-builder:intake quick action): the plan context is already in the request.
_PLAN_INTAKE_RULES = dedent("""
    PLAN INTAKE (this reply only; you cannot call tools): open the block definition for the NEXT UNPLANNED GOAL
    using the plan context above. At most ~180 words, in this order:
    1. One warm, personal line (profile, PRs, KEY EVENTS). No filler praise.
    2. The proposed block in 3-5 short bullets: window and length, phases in one line, peak weekly km and longest
       long run (from the recent training), key session types, strength.
    3. At most 3 questions only the runner can answer (days available, long-run day, travel or constraints).
    No week-by-week phasing, no paces, no session lists, no plan yet: the plan is built once the runner agrees.
""").strip()


def build_coach_instruction(ctx: ReadonlyContext) -> str:
    """InstructionProvider: static role + rules first for prefix caching, then today's date."""
    state, invocation_id = ctx.state, getattr(ctx, "invocation_id", None)
    # A web quick action's report call already holds its skill and data and cannot call tools,
    # so the routing rules are omitted there (typed chat turns always get them).
    parts = [_COACH_ROLE]
    if is_plan_intake(state, invocation_id):
        parts.append(_PLAN_INTAKE_RULES)
    elif not is_quick_action_report(state, invocation_id):
        parts.append(_ROUTING_RULES)
    parts.append(_CONTRACT_RULES)
    parts.append(f"Today's date is {get_today_str(with_weekday=True)}.")
    return "\n\n".join(parts)
