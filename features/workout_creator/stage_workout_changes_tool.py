"""Tool that stages proposed workout / note changes for the runner's "Update TrainingPeaks" button."""

import asyncio
import json
import logging
import uuid
from datetime import date, timedelta
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext
from opentelemetry import trace

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import iso_date, monday_of
from ...shared.sports import RUN_SPORTS
from ...shared.tp_payloads import coerce_mcp_payload
from ...shared.ui_channel import reply
from .helpers.staged_changes import (
    BUILDER_CHECK,
    BUILDER_COACH,
    KIND_WORKOUT,
    STAGED_CHANGES_STATE_KEY,
    finalize_builders,
    is_edit_only,
    resolve_changes,
    staged_dates,
)
from ...shared.workout_builder import needs_builder

logger = logging.getLogger(__name__)

_AMBIGUOUS_MESSAGE = (
    "Some changes were not staged: ask the runner which item to change or delete for each `ambiguous` entry and "
    "stage the full set again with its workout_id (a note: its exact title), or create=true to add a session."
)
_NOT_FOUND_MESSAGE = (
    "Some changes were not staged: the `not_found` items do not exist in TrainingPeaks. Use the [workout_id] of the "
    "planned session from this conversation, or date_str + sport (a note: date_str + title), and stage the full set "
    "again."
)
_REFUSED_MESSAGE = "Completed workouts are never deleted: tell the runner which `refused` entries stay."
_NEEDS_STRUCTURE_MESSAGE = (
    "Nothing was staged: every Run/Bike workout you create, or whose distance/duration you change, needs the exact "
    "workout builder. For each `needs_structure` entry send the complete `structure` (when `current_structure` is "
    "given, start from it and change only what the runner asked; keep everything else as is), then stage the full "
    "set again. Do not ask the runner."
)
# Above MAX_WORKOUT_CHANGES the change is a plan overhaul: plan-builder stages it in one compact call.
MAX_WORKOUT_CHANGES = 10
# Rejected (needs_structure) staging attempts allowed in one turn before the app stops the retries.
MAX_NEEDS_STRUCTURE_ATTEMPTS = 3
_ATTEMPTS_STATE_KEY = "temp:needs_structure_attempts"


def plan_builder_redirect(workout_changes: int, days: list[date]) -> Optional[dict]:
    """The redirect result when the set is too big for workout-creator (> MAX_WORKOUT_CHANGES workout changes),
    else None. Nothing is staged then."""
    if workout_changes <= MAX_WORKOUT_CHANGES:
        return None
    window = ""
    if days:
        start, end = monday_of(min(days)), monday_of(max(days)) + timedelta(days=6)
        window = f'start_date="{iso_date(start)}", end_date="{iso_date(end)}", '
    return {"staged": 0, "use_plan_builder": True, "message": (
        f"Nothing was staged: {workout_changes} workout changes is a plan overhaul "
        f"(workout-creator: <= {MAX_WORKOUT_CHANGES} workout changes). Use plan-builder: "
        f'call load_skill(skill_name="plan-builder", {window}mode="overhaul"), then '
        "stage the plan with ONE stage_training_plan call.")}


def staged_text(staged: int) -> str:
    noun = "change" if staged == 1 else "changes"
    return f"📋 {staged} {noun} staged. Review them below and press **Update TrainingPeaks** to apply."


def builder_not_staged_text(needs_structure: list[dict]) -> str:
    lines = ["⚠️ **Nothing was staged:** I could not write an exact workout builder for:"]
    lines += [f"- {n.get('date_str')} · {n.get('title')}: {n.get('why')}" for n in needs_structure]
    lines += ["", "Ask me again, ideally with the exact session (reps, lengths, target paces)."]
    return "\n".join(lines)


def _wrote_text_this_turn(tool_context: ToolContext) -> bool:
    """The coach already wrote visible text in this invocation (e.g. alongside this call)."""
    invocation = getattr(tool_context, "invocation_id", None)
    session = getattr(tool_context, "session", None)
    for event in reversed(getattr(session, "events", None) or []):
        if event.invocation_id != invocation:
            break
        if event.author == "user" or event.partial or not event.content:
            continue
        if any(p.text and p.text.strip() and not p.thought for p in event.content.parts or []):
            return True
    return False


def staged_reply(tool_context: ToolContext, message: str, staged: list[dict]) -> str:
    """The turn's closing reply: the coach's message (if not already written as text) + the coded line."""
    text = (message or "").strip()
    if _wrote_text_this_turn(tool_context):
        text = ""  # already shown above the table; never twice
    elif not text and not is_edit_only(staged):
        # Content changes without reasoning: still one call (no follow-up), but visible in traces.
        trace.get_current_span().set_attribute("coach.staged_without_message", True)
    line = staged_text(len(staged))
    return f"{text}\n\n{line}" if text else line


def _rejected_attempts(tool_context: ToolContext) -> int:
    """Counts needs_structure results in the current invocation (temp: state is not persisted)."""
    invocation = getattr(tool_context, "invocation_id", None)
    seen = tool_context.state.get(_ATTEMPTS_STATE_KEY) or {}
    count = (seen.get("count", 0) if seen.get("invocation") == invocation else 0) + 1
    tool_context.state[_ATTEMPTS_STATE_KEY] = {"invocation": invocation, "count": count}
    return count


async def _planned_workouts(tool_context: ToolContext, days: list[date]) -> list[dict]:
    if not days:
        return []
    try:
        return await tp_calls.fetch_workouts_range(tool_context, min(days), max(days))
    except Exception as e:  # resolution falls back to creating; never block staging
        logger.warning("Planned workouts unavailable for staging: %s", e)
        return []


async def _planned_notes(tool_context: ToolContext, days: list[date]) -> list[dict]:
    if not days:
        return []
    try:
        return await tp_calls.fetch_notes(tool_context, min(days), max(days))
    except Exception as e:  # the note delete is then reported back as not found
        logger.warning("Calendar notes unavailable for staging: %s", e)
        return []


async def _athlete_settings(tool_context: ToolContext, wanted: bool) -> Any:
    if not wanted:
        return None
    try:
        return await tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings")
    except Exception as e:  # pace targets then cannot be converted; those changes go back to the coach
        logger.warning("Athlete settings unavailable for staging: %s", e)
        return None


async def _current_workout(tool_context: ToolContext, workout_id: str) -> tuple[str, Optional[dict]]:
    try:
        data = coerce_mcp_payload(await tp_calls.run_tp_tool(tool_context, "tp_get_workout", workout_id=workout_id))
    except Exception as e:  # never write over a builder we could not read
        logger.warning("Workout %s unavailable for staging: %s", workout_id, e)
        return workout_id, None
    return workout_id, (data if isinstance(data, dict) and not data.get("isError") else None)


async def _current_workouts(tool_context: ToolContext, workout_ids: list[str]) -> dict[str, dict]:
    pairs = await asyncio.gather(*(_current_workout(tool_context, w) for w in dict.fromkeys(workout_ids)))
    return {w: d for w, d in pairs if d}


async def stage_workout_changes(
    tool_context: ToolContext, changes: list[dict[str, Any]], message: str = ""
) -> str:
    """Stages <= 10 workout/note changes for the Update TrainingPeaks button.

    `message`: 2-4 sentence coaching rationale + numeric risks (never list changes; shown above the table
    and ends the turn; omit for plain moves/renames). Replaces any prior staged set.
    Each item in `changes`:
    - Workout: `date_str` (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS), `sport` ('Run'|'Bike'|'Swim'|'Strength'|
      'Walk'|'Crosstrain'|'Race'), `title`, `duration_minutes`, `distance_km`, `tss_planned`, compact
      `description`, `structure` (required for Run/Bike creates and distance/duration edits), `workout_id`
      or `create=true` (move/rename needs only `workout_id` + `date_str` [+ `title`]; `strides=false` only
      when asked to drop strides).
    - Note: `kind='note'`, `date_str`, `title`, `description`.
    - Delete: `delete=true` + `workout_id` or `date_str` + `sport` (note: `kind='note'`, `date_str`, `title`).
    If `needs_structure` is returned, supply complete `structure` (preserving untouched blocks from
    `current_structure`) and re-stage without asking the runner.
    """
    raw = [c for c in (changes or []) if isinstance(c, dict)]
    workout_raw = [c for c in raw if str(c.get("kind") or KIND_WORKOUT).lower() != "note"]
    note_deletes = [c for c in raw if c not in workout_raw and c.get("delete")]
    days = staged_dates(workout_raw)
    redirect = plan_builder_redirect(len(workout_raw), days)
    if redirect:
        return json.dumps(redirect)
    wants_settings = any((needs_builder(c.get("sport")) or c.get("structure")) and not c.get("delete") for c in workout_raw)
    # Explicit ids are read with the calendar (one parallel round): a move to another date still
    # knows the session it moves, and the card shows its builder.
    explicit_ids = [str(c["workout_id"]).strip() for c in workout_raw if str(c.get("workout_id") or "").strip()]
    workouts, settings_raw, details, notes = await asyncio.gather(
        _planned_workouts(tool_context, days),
        _athlete_settings(tool_context, wants_settings),
        _current_workouts(tool_context, explicit_ids),
        _planned_notes(tool_context, staged_dates(note_deletes)),
    )

    staged, problems = resolve_changes(raw, workouts, details, notes)
    # The current builder is needed to keep a session's strides when the coach rewrites a run.
    to_check = [str(c["workout_id"]) for c in staged
                if c.get("workout_id") and str(c["workout_id"]) not in details
                and (c.get("builder") == BUILDER_CHECK
                     or (c.get("builder") == BUILDER_COACH and str(c.get("sport") or "").lower() in RUN_SPORTS))]
    if to_check:
        details = {**details, **await _current_workouts(tool_context, to_check)}
    staged, needs_structure, totals_notes = finalize_builders(staged, settings_raw, details)
    not_found = [p for p in problems if p.get("reason") in ("workout_not_found", "note_not_found")]
    refused = [p for p in problems if p.get("reason") == "cannot_delete_completed"]
    ambiguous = [p for p in problems if p not in not_found and p not in refused]

    result: dict[str, Any] = {"staged": 0}
    if needs_structure:
        # Never stage a partial set the runner could apply: the coach re-stages the full set.
        result.update({"needs_structure": needs_structure, "ready": len(staged), "message": _NEEDS_STRUCTURE_MESSAGE})
        if _rejected_attempts(tool_context) >= MAX_NEEDS_STRUCTURE_ATTEMPTS:
            result["give_up"] = True
            reply(tool_context, builder_not_staged_text(needs_structure))  # stops the retries
    elif staged:
        staged_id = str(uuid.uuid4())
        tool_context.state[STAGED_CHANGES_STATE_KEY] = {"staged_id": staged_id, "changes": staged}
        result.update({
            "staged": len(staged),
            "staged_id": staged_id,
            "changes": [
                {k: c.get(k) for k in ("kind", "action", "date", "sport", "title", "replaces_title", "replaces",
                                       "distance_km", "duration_minutes", "tss_planned", "structure_summary",
                                       "strides_added")
                 if c.get(k) is not None}
                for c in staged
            ],
            "message": "Staged. The runner sees the changes with an Update TrainingPeaks button.",
        })
        if totals_notes:
            result["totals_from_builder"] = totals_notes
        strides = [{"date": c["date"][:10], "title": c.get("title"), "strides": c["strides_added"]}
                   for c in staged if c.get("strides_added")]
        if strides:
            result["strides_added"] = strides  # kept from the current builder, or added after the warm-up
        if not problems:
            # One model call: the coach's message (unless already written as text) + the coded line end the turn.
            reply(tool_context, staged_reply(tool_context, message, staged))
    messages = [result["message"]] if needs_structure else []
    if ambiguous:
        result["ambiguous"] = ambiguous
        messages.append(_AMBIGUOUS_MESSAGE)
    if not_found:
        result["not_found"] = not_found
        messages.append(_NOT_FOUND_MESSAGE)
    if refused:
        result["refused"] = refused
        messages.append(_REFUSED_MESSAGE)
    if messages:
        result["message"] = " ".join(messages)
    if not staged and not problems and not needs_structure:
        result["message"] = "No changes given; nothing staged."
    if days:
        result["window"] = f"{iso_date(min(days))}..{iso_date(max(days))}"
    return json.dumps(result)


stage_workout_changes_tool = FunctionTool(stage_workout_changes)
