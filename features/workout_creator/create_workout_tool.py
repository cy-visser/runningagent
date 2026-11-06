"""Tool for creating or updating a planned TrainingPeaks workout."""

import json
from typing import Any, Optional

from google.adk.tools import FunctionTool, ToolContext

from ...shared.dates import iso_date, parse_date
from .helpers.workout_upsert import find_existing_workouts, write_workout


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

    return await write_workout(
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


create_workout_tool = FunctionTool(create_workout)
