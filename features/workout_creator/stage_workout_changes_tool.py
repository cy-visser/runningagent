"""Tool that stages proposed workout / note changes for the runner's "Update TrainingPeaks" button."""

import asyncio
import json
import logging
import uuid
from datetime import date
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import iso_date
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
from .helpers.workout_builder import needs_builder

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
# Rejected (needs_structure) staging attempts allowed in one turn before the app stops the retries.
MAX_NEEDS_STRUCTURE_ATTEMPTS = 3
_ATTEMPTS_STATE_KEY = "temp:needs_structure_attempts"


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


async def stage_workout_changes(tool_context: ToolContext, changes: list[dict[str, Any]]) -> str:
    """Stages workout and calendar-note changes; the runner applies them with the Update TrainingPeaks button.

    Nothing is written to TrainingPeaks. Call it in the SAME response as your recommendations,
    whenever you propose concrete plan changes or the runner asks to create, change or move
    workouts or notes. Stage the complete set: a new call replaces the previously staged set.

    Each change is an object:
    - Workout: date_str (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS), sport ('Run' default, 'Bike', 'Swim',
      'Strength', 'Walk', 'Crosstrain', 'Race'), title, duration_minutes, distance_km, tss_planned,
      description (warm-up, main set, cool-down, pacing cues), structure (the exact workout builder;
      required for Run/Bike creates and distance/duration changes), workout_id (the workout to change)
      or create=true (add a session to a day). Without either, it updates the single planned workout
      of the same sport on that date, or creates one if none. A move or rename needs only workout_id +
      date_str (+ title): the session keeps its title, builder and totals unless you change them.
      Strides are kept when you rewrite a run that has them, and added after the warm-up of tempo /
      threshold / interval runs (`strides_added`); strides=false only when the runner asks to drop them.
    - Note: kind='note', date_str, title, description.
    - Delete: delete=true with workout_id, or date_str + sport (+ title); a note: kind='note', date_str (+ title).
      To remove a session or note always stage a delete. Completed workouts are never deleted (`refused`).

    Returns the number staged, any `ambiguous` changes (several planned workouts of that sport on the
    date: ask the runner which one), any `not_found` workout_ids, and any `needs_structure` changes
    (nothing is staged: send the exact builder, starting from `current_structure` when given, and stage
    again without asking the runner).
    """
    raw = [c for c in (changes or []) if isinstance(c, dict)]
    workout_raw = [c for c in raw if str(c.get("kind") or KIND_WORKOUT).lower() != "note"]
    note_deletes = [c for c in raw if c not in workout_raw and c.get("delete")]
    days = staged_dates(workout_raw)
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
            # Explained already (or a plain move / rename): the coded line ends the turn.
            if is_edit_only(staged) or _wrote_text_this_turn(tool_context):
                reply(tool_context, staged_text(len(staged)))
            else:
                result["explain"] = True  # the next call writes the reasoning (model_callbacks)
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
