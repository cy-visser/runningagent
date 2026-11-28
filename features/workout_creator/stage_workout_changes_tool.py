"""Tool that stages proposed workout / note changes (1 to 150+ items) for the "Update TrainingPeaks" button."""

import asyncio
import json
import logging
import uuid
from datetime import date
from typing import Any, Optional, Union

from google.adk.tools import FunctionTool, ToolContext
from opentelemetry import trace

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import get_today_date, iso_date, parse_date
from ...shared.session_codes.session_codes import code_sport, normalize as normalize_code
from ...shared.sports import RUN_SPORTS
from ...shared.tp_payloads import coerce_mcp_payload
from ...shared.ui_channel import reply
from ...shared.workout_builder import needs_builder
from ...shared.workout_upsert import run_throttled
from .helpers.compact_changes import expand_change_entries
from .helpers.staged_changes import (
    BUILDER_CHECK,
    BUILDER_COACH,
    KIND_EVENT,
    KIND_NOTE,
    KIND_WORKOUT,
    STAGED_CHANGES_STATE_KEY,
    change_label,
    compact_staged_line,
    finalize_builders,
    is_edit_only,
    resolve_changes,
    staged_dates,
)

logger = logging.getLogger(__name__)

_AMBIGUOUS_MESSAGE = (
    "Some changes were not staged: ask the runner which item to change or delete for each `ambiguous` entry and "
    "stage the full set again with its workout_id (a note: its exact title), or +create / create=true to add a session."
)
_NOT_FOUND_MESSAGE = (
    "Some changes were not staged: the `not_found` items do not exist in TrainingPeaks. Use the [workout_id] of the "
    "planned session from this conversation, or date_str + sport (or from_date_str + sport to move; note: date_str + "
    "title), and stage the full set again."
)
_REFUSED_MESSAGE = "Completed workouts are never deleted: tell the runner which `refused` entries stay."
_NEEDS_STRUCTURE_MESSAGE = (
    "Nothing was staged: every Run/Bike workout you create, or whose distance/duration you change, needs a session "
    "`code` (e.g. 'E 8', 'T 2x15\\' r2\\'', 'L 22 +6@M', 'RACE 15k @4:35 Name', 'B 60\\' Z2') or complete `structure` "
    "(when `current_structure` is given and only one step changes, copy untouched blocks verbatim). "
    'Fallback `structure` schema (only for custom WU/CD, ladders, or `current_structure` edits): '
    '{"steps":[step|{"type":"repetition","reps":N,"steps":[work,rest]}]} '
    '(primaryIntensityMetric: omit for run pace; "percentOfThresholdHr"|bike "percentOfFtp"); '
    'step={"name","intensityClass":"warmUp"|"active"|"rest"|"coolDown"|"other","distance_m"|"duration_seconds",'
    '"pace":"M:SS-M:SS"|"intensity_min"+"intensity_max"}. '
    "Ready items and `message` from this turn are kept automatically—re-send ONLY the `needs_structure` entries "
    "(omit `message` and distance_km/duration_minutes) and do not ask the runner."
)
# Rejected (needs_structure) staging attempts allowed in one turn before the app stops the retries.
MAX_NEEDS_STRUCTURE_ATTEMPTS = 3
MAX_STAGED_PREVIEW_LINES = 12
_ATTEMPTS_STATE_KEY = "temp:needs_structure_attempts"
_TP_CACHE_STATE_KEY = "temp:staging_tp_cache"
_READY_DRAFT_STATE_KEY = "temp:staging_ready_draft"


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


def _slot_key(item: dict) -> tuple:
    wid = str(item.get("workout_id") or "").strip()
    if wid:
        return ("wid", wid)
    day = str(item.get("date") or item.get("date_str") or "")[:10]
    kind = str(item.get("kind") or KIND_WORKOUT).strip().lower()
    if kind == KIND_NOTE:
        return ("note", day, str(item.get("title") or "").strip().lower())
    if kind == KIND_EVENT:
        return ("event", day, str(item.get("name") or item.get("title") or "").strip().lower())
    inferred = code_sport(item.get("code")) if item.get("code") else None
    sport = str(item.get("sport") or inferred or "run").strip().lower()
    from_day = str(item.get("from_date_str") or "")[:10]
    if from_day:
        return ("move", from_day, day, sport)
    return ("slot", day, sport)


async def _planned_workouts(tool_context: ToolContext, days: list[date], cache: dict) -> list[dict]:
    if not days:
        return []
    start_s, end_s = iso_date(min(days)), iso_date(max(days))
    if (
        isinstance(cache.get("workouts"), list)
        and str(cache.get("w_start") or "") <= start_s
        and str(cache.get("w_end") or "") >= end_s
    ):
        return cache["workouts"]
    try:
        workouts = await tp_calls.fetch_workouts_range(tool_context, min(days), max(days))
        cache.update({"workouts": workouts, "w_start": start_s, "w_end": end_s})
        return workouts
    except Exception as e:  # resolution falls back to creating; never block staging
        logger.warning("Planned workouts unavailable for staging: %s", e)
        return []


async def _planned_notes(tool_context: ToolContext, days: list[date], cache: dict) -> list[dict]:
    if not days:
        return []
    start_s, end_s = iso_date(min(days)), iso_date(max(days))
    if (
        isinstance(cache.get("notes"), list)
        and str(cache.get("n_start") or "") <= start_s
        and str(cache.get("n_end") or "") >= end_s
    ):
        return cache["notes"]
    try:
        notes = await tp_calls.fetch_notes(tool_context, min(days), max(days))
        cache.update({"notes": notes, "n_start": start_s, "n_end": end_s})
        return notes
    except Exception as e:  # the note delete is then reported back as not found
        logger.warning("Calendar notes unavailable for staging: %s", e)
        return []


async def _planned_events(tool_context: ToolContext, days: list[date], cache: dict) -> list[dict]:
    if not days:
        return []
    start_s, end_s = iso_date(min(days)), iso_date(max(days))
    if (
        isinstance(cache.get("events"), list)
        and str(cache.get("e_start") or "") <= start_s
        and str(cache.get("e_end") or "") >= end_s
    ):
        return cache["events"]
    try:
        events = await tp_calls.fetch_events(tool_context, min(days), max(days))
        cache.update({"events": events, "e_start": start_s, "e_end": end_s})
        return events
    except Exception as e:
        logger.warning("Calendar events unavailable for staging: %s", e)
        return []


async def _athlete_settings(tool_context: ToolContext, wanted: bool, cache: dict) -> Any:
    if not wanted:
        return None
    if cache.get("has_settings"):
        return cache.get("settings")
    try:
        settings = await tp_calls.run_tp_tool(tool_context, "tp_get_athlete_settings")
        cache.update({"has_settings": True, "settings": settings})
        return settings
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


async def _current_workouts(tool_context: ToolContext, workout_ids: list[str], cache: dict) -> dict[str, dict]:
    cached_details: dict[str, dict] = cache.setdefault("details", {})
    missing = [w for w in dict.fromkeys(workout_ids) if w not in cached_details]
    if missing:
        pairs = await run_throttled(missing, lambda w: _current_workout(tool_context, w))
        cached_details.update({w: d for w, d in pairs if d})
    return {w: cached_details[w] for w in dict.fromkeys(workout_ids) if w in cached_details}


def _preview_staged_lines(staged: list[dict]) -> list[str]:
    lines = [compact_staged_line(c) for c in staged[:MAX_STAGED_PREVIEW_LINES]]
    extra = len(staged) - MAX_STAGED_PREVIEW_LINES
    if extra > 0:
        lines.append(f"... +{extra} more staged on the runner's card")
    return lines


async def stage_workout_changes(
    tool_context: ToolContext, changes: list[Union[str, dict[str, Any]]], message: str = ""
) -> str:
    """Stages workout / note / race-event changes of any count (1 to 150+). `message`: coaching rationale (<= 35w if already discussed, else <= 80w + ⚠️/🔴 numeric risks; omit on plain move/rename). Map agreed recommendations directly to compact strings without re-auditing.
    Prefer compact 1-line strings in `changes` (`;` combines same-day doubles, `delete`, or `event`):
    - Workout: `"2027-01-05: P 4x1.2k @4:08-4:10 r2'"` | `"2026-12-30,2026-12-31: E 8 -strides"` (`+create` adds 2nd same-sport; `-strides` drops strides; `"2027-01-29: T 2x2k @4:25 r2'; delete strength"`).
    - Full week: `"2026-11-30 | Tue: I 6x400 @4:18 r90\\"; S 45' heavy-lower | Wed/Thu: E 6 | Sun: L 14"`.
    - Move / Delete / Note: `"2026-12-25 -> 2026-12-26: run"` | `"2027-01-29: delete strength"` (`delete id=<wid>`) | `"2026-12-19: note Holiday | Travel"`.
    - Race Event (TP Calendar Event): `"2026-10-31: event A RunningRoad 21.1k Amsterdam HM | goal=1:35:00 place=10 pr=true"` (intermediate races must be B or C, never A).
    - Codes: lengths 8|1.5k|10mi|400m|50'|90"|1h30, reps 6x1k, rec r2'|r90"|r200, slot am|mid|pm, run `@M:SS[-M:SS]` or `@5K|@10K|@HM|@M|@T|@E`. Run: E 8 (+strides), R 6, L 22 (+6@M|+4x4k@HM r1k [+2@E]), RACE/EVENT 15k @HM|@4:35 [Name] (no auto WU/CD); quality (15'WU+strides+10'CD): T 2x15' r2', I 6x1k r2', Rp 10x200 r200, M 12k, P 4x2k@HM r2', H 8x60" r90", REST. Other: B 60' Z2 (Z1-Z3) | B 4x8' @SS r4' (@SS|@T|@VO2), S 40' heavy-lower (full|core-hips|plyo|mobility), X 40' swim (walk|crosstrain).
    - Dict items supported for `[workout_id]` renames, events, or custom `structure` ladders/WU/CD (schema returned on retry)."""
    invocation = getattr(tool_context, "invocation_id", None)
    saved_cache = tool_context.state.get(_TP_CACHE_STATE_KEY)
    tp_cache: dict[str, Any] = (
        dict(saved_cache)
        if isinstance(saved_cache, dict) and saved_cache.get("invocation") == invocation
        else {"invocation": invocation, "details": {}}
    )
    tp_cache["details"] = dict(tp_cache.get("details") or {})

    saved_draft = tool_context.state.get(_READY_DRAFT_STATE_KEY)
    draft = saved_draft if isinstance(saved_draft, dict) and saved_draft.get("invocation") == invocation else None

    raw = expand_change_entries(changes)
    workout_raw = [c for c in raw if str(c.get("kind") or KIND_WORKOUT).lower() not in (KIND_NOTE, KIND_EVENT)]
    event_raw = [c for c in raw if str(c.get("kind") or "").lower() == KIND_EVENT]
    note_deletes = [c for c in raw if str(c.get("kind") or "").lower() == KIND_NOTE and c.get("delete")]
    days = staged_dates(workout_raw)
    event_days = staged_dates(event_raw)
    wants_settings = any(
        not c.get("delete")
        and normalize_code(c.get("code")).upper() != "REST"
        and (
            bool(c.get("structure"))
            or needs_builder(code_sport(c.get("code")) or c.get("sport"))
            or (not c.get("sport") and not c.get("code") and bool(c.get("from_date_str") or c.get("workout_id")))
        )
        for c in workout_raw
    )
    # Explicit ids are read with the calendar (throttled): a move to another date still knows the session it moves.
    explicit_ids = [
        str(c["workout_id"]).strip()
        for c in workout_raw
        if str(c.get("workout_id") or "").strip() and not c.get("code")
    ]
    workouts, settings_raw, details, notes, existing_events = await asyncio.gather(
        _planned_workouts(tool_context, days, tp_cache),
        _athlete_settings(tool_context, wants_settings, tp_cache),
        _current_workouts(tool_context, explicit_ids, tp_cache),
        _planned_notes(tool_context, staged_dates(note_deletes), tp_cache),
        _planned_events(tool_context, event_days, tp_cache),
    )

    profile = tool_context.state.get("user_profile") or {}
    staged, problems = resolve_changes(raw, workouts, details, notes, events=existing_events, profile=profile)
    # `BUILDER_CODE` builds deterministic workouts/strides directly from the code (zero per-workout tp_get_workout
    # calls, scaling cleanly to 150+ workouts); only custom `structure`, totals checks, or moves fetch details.
    to_check = [str(c["workout_id"]) for c in staged
                if c.get("workout_id") and str(c["workout_id"]) not in details
                and (c.get("builder") == BUILDER_CHECK
                     or (c.get("builder") == BUILDER_COACH
                         and str(c.get("sport") or "").lower() in RUN_SPORTS)
                     or (change_label(c) == "Moved" and needs_builder(c.get("sport"))))]
    if to_check:
        details = {**details, **await _current_workouts(tool_context, to_check, tp_cache)}
    staged, needs_structure, totals_notes = finalize_builders(
        staged, settings_raw, details, profile=profile, today=get_today_date()
    )

    if draft and draft.get("ready"):
        touched = {_slot_key(c) for c in (*staged, *needs_structure, *problems)}
        kept = [prev for prev in draft["ready"] if _slot_key(prev) not in touched]
        if kept:
            staged = sorted([*kept, *staged], key=lambda c: (c["date"], c["kind"]))
            kept_dates = {c["date"][:10] for c in kept}
            kept_notes = [n for n in (draft.get("totals_notes") or []) if n.get("date") in kept_dates]
            totals_notes = [*kept_notes, *totals_notes]
        if not message and draft.get("message"):
            message = draft["message"]
        all_days = [d for d in (parse_date(c.get("date")) for c in staged) if d]
        days = sorted({*days, *all_days})

    not_found = [p for p in problems if p.get("reason") in ("workout_not_found", "note_not_found", "event_not_found")]
    refused = [p for p in problems if p.get("reason") == "cannot_delete_completed"]
    ambiguous = [p for p in problems if p not in not_found and p not in refused]

    result: dict[str, Any] = {"staged": 0}
    if needs_structure:
        # Never stage a partial set the runner could apply: keep ready items in temp draft and re-stage only fixes.
        result.update({"needs_structure": needs_structure, "ready": len(staged), "message": _NEEDS_STRUCTURE_MESSAGE})
        if _rejected_attempts(tool_context) >= MAX_NEEDS_STRUCTURE_ATTEMPTS:
            result["give_up"] = True
            tool_context.state[_TP_CACHE_STATE_KEY] = None
            tool_context.state[_READY_DRAFT_STATE_KEY] = None
            reply(tool_context, builder_not_staged_text(needs_structure))  # stops the retries
        else:
            tool_context.state[_TP_CACHE_STATE_KEY] = tp_cache
            tool_context.state[_READY_DRAFT_STATE_KEY] = {
                "invocation": invocation,
                "ready": staged,
                "totals_notes": totals_notes,
                "message": message,
            }
    else:
        tool_context.state[_TP_CACHE_STATE_KEY] = None
        tool_context.state[_READY_DRAFT_STATE_KEY] = None
        if staged:
            staged_id = str(uuid.uuid4())
            tool_context.state[STAGED_CHANGES_STATE_KEY] = {"staged_id": staged_id, "changes": staged}
            result.update({
                "staged": len(staged),
                "staged_id": staged_id,
                "changes": _preview_staged_lines(staged),
                "message": "Staged. The runner sees the changes with an Update TrainingPeaks button.",
            })
            if totals_notes:
                result["totals_from_builder"] = totals_notes
            strides = [c["date"][:10] for c in staged[:MAX_STAGED_PREVIEW_LINES] if c.get("strides_added")]
            if strides:
                result["strides_added"] = strides
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
    all_window_days = sorted({*days, *event_days})
    if all_window_days:
        result["window"] = f"{iso_date(min(all_window_days))}..{iso_date(max(all_window_days))}"
    return json.dumps(result)


stage_workout_changes_tool = FunctionTool(stage_workout_changes)
