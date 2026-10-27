from datetime import date
from typing import Any, Optional

from .date_helpers import get_today_str, parse_date
from .goals import GOAL_TYPE_PLAN, GOAL_TYPE_SINGLE, KIND_NORTH_STAR, current_goal, north_star


def normalize_timeline(timeline: Optional[str]) -> Optional[str]:
    """Returns the goal date as ISO (YYYY-MM-DD) when parseable, else the raw value."""
    parsed = parse_date(timeline) if timeline else None
    return parsed.isoformat() if parsed else timeline


def get_user_id(firstname: Optional[str], lastname: Optional[str] = "") -> str:
    """Returns the canonical lowercase user_id for Firestore document keys."""
    fn = str(firstname or "").strip().lower()
    ln = str(lastname or "").strip().lower()
    return f"{fn}_{ln}"


def profile_user_id(profile: Optional[dict]) -> Optional[str]:
    """Returns the Firestore user_id for a profile, or None when it has no name."""
    profile = profile or {}
    user_id = get_user_id(profile.get("firstname"), profile.get("lastname"))
    return None if user_id == "_" else user_id


def parse_runner_name(raw_name: Optional[str]) -> tuple[str, str, str]:
    """Extracts (firstname, lastname, user_id) from a raw name string."""
    clean_name = str(raw_name or "").strip()
    if not clean_name:
        return ("", "", "_")
    parts = clean_name.split(maxsplit=1)
    firstname = parts[0]
    lastname = parts[1] if len(parts) > 1 else ""
    return firstname, lastname, get_user_id(firstname, lastname)


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


def format_profile_summary(profile: dict, today: Optional[date] = None) -> str:
    """Formats a slim, token-efficient markdown summary of the runner's profile."""
    if not profile:
        return ""
    return (
        f"Name: {profile.get('firstname')} {profile.get('lastname')} (Age: {profile.get('age')})\n"
        f"Location: {profile.get('location')}\n"
        f"Stats: Height: {profile.get('height')}, Weight: {profile.get('weight')}\n"
        f"{_goal_line(profile, today)}\n"
        f"Recent Races: {profile.get('recent_race_times')}\n"
        f"Injuries: {profile.get('injuries')}\n"
        f"Cross-Training: {profile.get('cross_training_strength')}\n"
        f"Shoe Rotation: {profile.get('shoe_rotation')}"
    )


# ADK user-scoped state (shared across all sessions of the signed-in ADK user):
# remembers which Firestore runner profile belongs to this user.
RUNNER_ID_STATE_KEY = "user:runner_id"


def sync_profile_to_state(ctx: Any, profile: dict) -> None:
    """Sets user_profile and the user-scoped runner id in state.

    Everything else the coach needs (date, summary, goal plan) is derived from the
    profile when the instruction is built, so it is not duplicated in state.
    """
    ctx.state["user_profile"] = profile
    user_id = profile_user_id(profile)
    if user_id and ctx.state.get(RUNNER_ID_STATE_KEY) != user_id:
        ctx.state[RUNNER_ID_STATE_KEY] = user_id


# Fields sourced from the runner's onboarding answers, falling back to data
# already harvested from the TrainingPeaks profile.
_MERGED_FIELDS = (
    "age",
    "height",
    "weight",
    "recent_race_times",
    "injuries",
    "cross_training_strength",
    "shoe_rotation",
)

# Profile fields pre-filled from an existing profile so (re-)onboarding can
# skip questions the runner has already answered.
_PREFILL_FIELDS = ("firstname", "lastname", "location", *_MERGED_FIELDS)

# Current goal fields shown to the onboarding agent on re-onboarding (and used by
# merge_profile_data to keep saved sub-goal results).
_GOAL_PREFILL_FIELDS = ("goal_type", "training_goal", "timeline", "north_star", "sub_goals")


def onboarding_prefill(profile: dict) -> dict:
    """Returns the temp_onboarding_data seed for re-onboarding an existing runner."""
    seed = {f: profile.get(f) for f in _PREFILL_FIELDS}
    seed.update({f: profile.get(f) for f in _GOAL_PREFILL_FIELDS if profile.get(f) is not None})
    return seed


def _sub_goal_key(sub_goal: dict) -> tuple:
    return (str(sub_goal.get("goal") or "").strip().lower(), normalize_timeline(sub_goal.get("race_date")))


def _plan_fields(answers: dict, previous_sub_goals: Any) -> dict:
    """north_star + sorted sub_goals from onboarding answers; saved results survive re-onboarding."""
    saved_results = {
        _sub_goal_key(s): s.get("result")
        for s in previous_sub_goals or [] if isinstance(s, dict) and s.get("result")
    }
    sub_goals = []
    for answer in answers.get("sub_goals") or []:
        if not isinstance(answer, dict):
            continue
        sub_goal = {
            "goal": answer.get("goal"),
            "race_name": answer.get("race_name"),
            "start_date": normalize_timeline(answer.get("start_date")),
            "race_date": normalize_timeline(answer.get("race_date")),
            "taper_weeks": answer.get("taper_weeks"),
        }
        sub_goal["result"] = saved_results.get(_sub_goal_key(sub_goal))
        sub_goals.append(sub_goal)
    sub_goals.sort(key=lambda s: parse_date(s["race_date"]) or date.max)
    return {
        "goal_type": GOAL_TYPE_PLAN,
        "north_star": {
            "goal": answers.get("north_star_goal"),
            "race_name": answers.get("north_star_race_name"),
            "start_date": normalize_timeline(answers.get("north_star_start_date")),
            "race_date": normalize_timeline(answers.get("north_star_race_date")),
            "taper_weeks": answers.get("taper_weeks"),
        },
        "sub_goals": sub_goals,
        "training_goal": None,
        "timeline": None,
        "taper_weeks": None,
    }


def merge_profile_data(
    answers: dict,
    temp_data: dict,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    location: Optional[str] = None,
) -> dict:
    """Consolidates onboarding answers with harvested temp data into a runner profile.

    The runner's name is only ever sourced from `temp_data` (harvested from the
    TrainingPeaks profile); the onboarding schema does not collect it.
    A goal plan (north star + sub goals) replaces training_goal/timeline; the
    active block is derived from it on read (see utils.goals.current_goal).
    """
    profile = {
        "firstname": temp_data.get("firstname") or "",
        "lastname": temp_data.get("lastname") or "",
        "location": location or answers.get("location") or temp_data.get("location") or "",
        "latitude": lat,
        "longitude": lon,
        "goal_type": GOAL_TYPE_SINGLE,
        "training_goal": answers.get("training_goal"),
        "timeline": normalize_timeline(answers.get("timeline")),
        # Optional taper override for this goal; None -> goal-distance default.
        "taper_weeks": answers.get("taper_weeks"),
        # Onboarding only runs for new profiles or a new goal, so this marks the
        # start of the current training block (used by the race projection).
        "goal_set_date": get_today_str(),
    }
    if answers.get("goal_type") == GOAL_TYPE_PLAN:
        profile.update(_plan_fields(answers, temp_data.get("sub_goals")))
    for field in _MERGED_FIELDS:
        profile[field] = answers.get(field) or temp_data.get(field)
    return profile
