"""Tool that turns the coach's session-code plan into exact sessions, diffs them with the calendar and stages them."""

import json
import logging
import uuid
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext
from opentelemetry import trace

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date
from ...shared.goal_plan import current_goal
from ...shared.parallel_fetch import gather_labeled
from ...shared.training_times import default_session_times
from ...shared.ui_channel import reply
from .helpers.pace_zones import resolve_zones
from .helpers.plan_context_text import PLAN_CONTEXT_STATE_KEY
from .helpers.plan_diff import diff_week
from .helpers.plan_expand import expand_plan, merge_weeks, normalize_plan, plan_window
from .helpers.plan_summary_text import (
    CALENDAR_UNAVAILABLE_TEXT,
    ERRORS_MESSAGE,
    give_up_text,
    staged_reply,
    week_line,
)
from .helpers.web_payload import STAGED_PLAN_STATE_KEY, staged_plan_payload, week_payload

logger = logging.getLogger(__name__)

# Rejected (errors) staging attempts allowed in one turn before the app stops the retries.
MAX_PLAN_ATTEMPTS = 2
_ATTEMPTS_STATE_KEY = "temp:plan_attempts"
MAX_ERRORS_SHOWN = 20


def _rejected_attempts(tool_context: ToolContext) -> int:
    """Counts rejected plans in the current invocation (temp: state is not persisted)."""
    invocation = getattr(tool_context, "invocation_id", None)
    seen = tool_context.state.get(_ATTEMPTS_STATE_KEY) or {}
    count = (seen.get("count", 0) if seen.get("invocation") == invocation else 0) + 1
    tool_context.state[_ATTEMPTS_STATE_KEY] = {"invocation": invocation, "count": count}
    return count


def _wrote_text_this_turn(tool_context: ToolContext) -> bool:
    """The coach already wrote visible text in this invocation (then the message is not shown twice)."""
    invocation = getattr(tool_context, "invocation_id", None)
    for event in reversed(getattr(getattr(tool_context, "session", None), "events", None) or []):
        if event.invocation_id != invocation:
            break
        if event.author == "user" or event.partial or not event.content:
            continue
        if any(p.text and p.text.strip() and not p.thought for p in event.content.parts or []):
            return True
    return False


def _title(spec: dict, profile: dict, weeks: int) -> str:
    if spec.get("title"):
        return spec["title"]
    goal = current_goal(profile, plan_window(spec)[1]).get("training_goal")
    return f"{goal} · {weeks} weeks" if goal else f"Training plan · {weeks} weeks"


def _rejected(tool_context: ToolContext, errors: list[dict]) -> str:
    result: dict[str, Any] = {"staged": 0, "errors": errors[:MAX_ERRORS_SHOWN], "message": ERRORS_MESSAGE}
    if len(errors) > MAX_ERRORS_SHOWN:
        result["more_errors"] = len(errors) - MAX_ERRORS_SHOWN
    if _rejected_attempts(tool_context) >= MAX_PLAN_ATTEMPTS:
        result["give_up"] = True
        reply(tool_context, give_up_text(errors))  # stops the retries
    return json.dumps(result)


async def stage_training_plan(
    tool_context: ToolContext, plan: dict[str, Any], message: str = "", base_staged_id: str = ""
) -> str:
    """Stages a training plan written in session codes; the runner applies it week by week with the
    Apply to TrainingPeaks button. Nothing is written to TrainingPeaks.

    `plan`: {"start_date": "YYYY-MM-DD" (week 1 = its ISO week), "mode": "new" | "overhaul",
    "title": optional, "weeks": [{"week": 1, "phase": "base", "focus": "...", "days": {"Mon": "E 8",
    "Tue": ["T 2x15' r2'", "S 30' core-hips"], "Fri": "REST", ...}}]}, in the plan-builder skill's
    session-code language. The app builds every session (builders, paces, strides, totals) and diffs
    it with the calendar per day and sport.
    `message`: your coaching message (3-6 sentences on the plan's logic, strength / bike setup, peak,
    taper and risks; never list sessions). It is shown as your reply and ends the turn.
    `base_staged_id`: to change a staged plan, send only the changed weeks with the staged_id.

    Returns one line per week, or `errors` (nothing staged: fix the codes and stage again).
    """
    state = tool_context.state
    profile = state.get("user_profile") or {}
    today = get_today_date()
    context = state.get(PLAN_CONTEXT_STATE_KEY) or {}
    base: Optional[dict] = None
    if base_staged_id:
        base = state.get(STAGED_PLAN_STATE_KEY)
        if not isinstance(base, dict) or base.get("staged_id") != base_staged_id:
            return json.dumps({"staged": 0, "message": (
                "base_staged_id is not the current staged plan: stage the full plan without base_staged_id.")})
        defaults = {"start_date": base["spec"]["start_date"], "mode": base["spec"]["mode"]}
    else:
        defaults = {"start_date": context.get("start_date"), "mode": context.get("mode")}
    spec, errors = normalize_plan(plan, defaults)
    if base and not errors:
        spec = merge_weeks(base["spec"], spec)
    if not errors and not spec["weeks"]:
        errors.append({"week": None, "day": None, "code": None, "why": "the plan has no weeks"})
    if errors:
        return _rejected(tool_context, errors)
    if not base:
        # A plan edit keeps the times it was staged with (merge_weeks keeps the base spec's keys).
        spec["times"] = default_session_times(profile)

    start, end = plan_window(spec)
    fetches: dict[str, Any] = {"workouts": tp_calls.fetch_workouts(tool_context, iso_date(start), iso_date(end))}
    if not base:
        fetches["settings"] = tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings")
    raw = await gather_labeled(fetches)
    if raw["workouts"] is None:
        # Never diff against a calendar we could not read: that would create duplicates.
        reply(tool_context, CALENDAR_UNAVAILABLE_TEXT)
        return json.dumps({"staged": 0, "message": "The calendar could not be read; the runner was told to retry."})
    # A plan edit keeps the zones it was staged with, so unchanged weeks expand identically.
    zones = base["zones"] if base else resolve_zones(raw.get("settings"), profile, today)

    weeks, errors = expand_plan(spec, zones, today)
    if errors:
        return _rejected(tool_context, errors)

    payload_weeks = [week_payload(w, diff_week(w, raw["workouts"], spec["mode"])) for w in weeks]
    staged_id = str(uuid.uuid4())
    staged = staged_plan_payload(staged_id, spec, zones, payload_weeks, _title(spec, profile, len(weeks)))
    state[STAGED_PLAN_STATE_KEY] = staged

    wrote_text = _wrote_text_this_turn(tool_context)
    text = "" if wrote_text else (message or "").strip()
    if not text and not wrote_text:
        trace.get_current_span().set_attribute("coach.staged_without_message", True)
    reply(tool_context, staged_reply(text, staged["totals"]))  # one call: message + coded line end the turn
    totals = staged["totals"]
    return json.dumps({
        "staged_id": staged_id,
        "total_weeks": totals["weeks"],
        "sessions": totals["sessions"],
        "counts": {k: totals[k] for k in ("create", "update", "delete", "keep")},
        "weeks": [week_line(w) for w in payload_weeks],
        "message": "Staged. The runner sees the plan card with Apply to TrainingPeaks; the turn has ended.",
    })


stage_training_plan_tool = FunctionTool(stage_training_plan)
