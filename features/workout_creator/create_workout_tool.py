"""Tool for creating or updating a planned TrainingPeaks workout."""

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...integrations.trainingpeaks import tp_calls
from ...shared.dates import iso_date, parse_date
from .helpers.preflight import NOTE_WINDOW_DAYS, applies_to, preflight_risks, preflight_window
from .helpers.workout_upsert import find_existing_workouts, write_workout

logger = logging.getLogger(__name__)


async def _preflight(
    tool_context: ToolContext, target, sport: str, title: str, distance_km, duration_minutes,
    tss_planned, replaced_workout_id: Optional[str],
) -> Optional[dict]:
    """Deterministic risk check of the proposed session; None when the data can't be loaded."""
    start, end = preflight_window(target)
    notes_start, notes_end = target - timedelta(days=NOTE_WINDOW_DAYS), target + timedelta(days=NOTE_WINDOW_DAYS)
    try:
        workouts, notes = await asyncio.gather(
            tp_calls.fetch_workouts(tool_context, iso_date(start), iso_date(end)),
            tp_calls.fetch_notes(tool_context, iso_date(notes_start), iso_date(notes_end)),
        )
    except Exception as e:  # never block a write on a failed check
        logger.warning("Pre-flight check unavailable for %s: %s", iso_date(target), e)
        return None
    return preflight_risks(
        target=target, sport=sport, title=title, distance_km=distance_km,
        duration_minutes=duration_minutes, tss_planned=tss_planned, workouts=workouts, notes=notes,
        profile=tool_context.state.get("user_profile") or {}, replaced_workout_id=replaced_workout_id,
    )


async def create_workout(
    tool_context: ToolContext,
    date_str: str,
    sport: str = "Run",
    title: str = "Planned Run",
    duration_minutes: Optional[int | float] = None,
    distance_km: Optional[float] = None,
    tss_planned: Optional[float] = None,
    description: Optional[str] = None,
    structure: Optional[Any] = None,
    workout_id: Optional[str] = None,
    create: bool = False,
) -> str:
    """Creates a new planned workout or updates an existing one in TrainingPeaks.

    - `workout_id` given: updates that workout.
    - `create=True`: always creates a new workout (use when ADDING a session to a day).
    - Otherwise: looks for planned workouts of the SAME sport on `date_str`; none -> creates,
      exactly one -> updates it, several -> returns the candidates so you can pass `workout_id`.
      Workouts of other sports on that day are never touched.
    - Always writes. Run/race sessions also get a load check; risks the change introduces or
      worsens are returned as `warnings` alongside the write result (never blocking). When the
      change adds running km, `week` carries the volume facts (km vs prior week, `volume_change_pct`)
      for your own judgement of the ramp: there is no coded % limit.

    Args:
        date_str: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS.
        sport: 'Run' (default), 'Bike', 'Swim', 'Strength', 'Walk', 'Crosstrain' or 'Race'.
        title: e.g. 'Threshold Intervals: 5x1km'.
        duration_minutes: Planned duration.
        distance_km: Planned distance.
        tss_planned: Planned TSS.
        description: Coaching instructions (warm-up, main set, cool-down, pacing cues).
        structure: Interval structure (dict or JSON string).
        workout_id: Workout to update.
        create: Always create a new workout.
    """
    target_date = parse_date(date_str)
    target_iso = iso_date(target_date) if target_date else date_str[:10]

    target_workout_id = workout_id
    if not target_workout_id and not create:
        existing = await find_existing_workouts(tool_context, target_iso, sport)
        if len(existing) > 1:
            return json.dumps({
                "success": False,
                "action": "needs_workout_id",
                "message": (
                    f"Several planned {sport} workouts exist on {target_iso}. Ask the runner which one "
                    "to change and call again with workout_id, or pass create=True to add a new one."
                ),
                "candidates": [
                    {"workout_id": str(w.get("id") or ""), "title": w.get("title")} for w in existing
                ],
            })
        if existing:
            target_workout_id = str(existing[0].get("id") or "") or None

    check = None
    if target_date and applies_to(sport):
        check = await _preflight(
            tool_context, target_date, sport, title, distance_km, duration_minutes, tss_planned,
            target_workout_id,
        )

    result = await write_workout(
        tool_context=tool_context,
        date_str=date_str,
        sport=sport,
        title=title,
        workout_id=target_workout_id,
        duration_minutes=duration_minutes,
        distance_km=distance_km,
        tss_planned=tss_planned,
        description=description,
        structure=structure,
    )
    if check and (check["risks"] or check["week"].get("volume_increased")):
        try:
            payload = json.loads(result)
        except (TypeError, ValueError):  # error strings from write_workout pass through unchanged
            return result
        if check["risks"]:
            payload["warnings"] = check["risks"]
        # Volume facts for the coach's own ramp judgement (no coded % limit).
        payload["week"] = check["week"]
        result = json.dumps(payload)
    return result


create_workout_tool = FunctionTool(create_workout)
