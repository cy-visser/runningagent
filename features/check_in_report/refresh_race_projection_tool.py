"""Internal tool for computing and caching the 12-week Race Predictor projection (zero LLM calls)."""

from __future__ import annotations

import json

from google.adk.tools import FunctionTool, ToolContext

from ...shared.dates import get_today_date
from ...shared.goal_plan import active_race_goal
from ...shared.goal_projection.projection_cache import recompute_and_cache_race_projection


async def refresh_race_projection(
    tool_context: ToolContext,
    refresh_analysis_cache: bool = False,
) -> str:
    """Computes the 12-week key-session race projection for the active goal and caches it in Firestore.

    Args:
        refresh_analysis_cache: Re-analyse key workouts instead of reusing cached summaries.
    """
    tool_context.actions.skip_summarization = True
    profile = tool_context.state.get("user_profile") or {}
    today = get_today_date()
    _, goal_label, status = active_race_goal(profile, today)
    if status != "ok" or not goal_label:
        return json.dumps({"status": "no_goal", "reason": status})

    doc = await recompute_and_cache_race_projection(
        tool_context,
        profile,
        today,
        trigger="manual_refresh",
        refresh_analysis_cache=bool(refresh_analysis_cache),
    )
    if not doc:
        return json.dumps({"status": "unavailable"})
    return json.dumps({
        "status": "ready" if doc.get("projection") else "insufficient_data",
        "goal_key": doc.get("goal_key"),
    })


refresh_race_projection_tool = FunctionTool(refresh_race_projection)
