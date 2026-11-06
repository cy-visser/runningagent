import asyncio
from typing import Any, Optional

from google.adk.tools import ToolContext

from ....integrations.trainingpeaks import tp_calls
from ....shared.parallel_fetch import gather_labeled
from ....shared.sports import RUN_SPORTS
from ....shared.tp_payloads import coerce_mcp_payload
from ....shared.training_log.record_writer import record_workout
from ....shared.training_log.telemetry_file import load_analysis_file

GAPFILL_CONCURRENCY = 2         # TP's analysis API rate-limits (429) bursts


async def gapfill_one(
    tool_context: ToolContext, sem: asyncio.Semaphore, profile: dict, workout: dict, **context: Any
) -> Optional[dict]:
    """Fetches one unrecorded workout from TP and records it via record_workout."""
    async with sem:
        wid = str(workout.get("id"))
        is_run = str(workout.get("sport") or "").lower() in RUN_SPORTS
        fetches = {"meta": tp_calls.run_tp_tool(tool_context, "tp_get_workout", workout_id=wid)}
        if is_run:
            fetches["analysis"] = tp_calls.run_tp_tool(tool_context, "tp_analyze_workout", workout_id=wid)
        raw = await gather_labeled(fetches)
        meta = coerce_mcp_payload(raw["meta"]) if raw["meta"] else {}
        analysis = coerce_mcp_payload(raw["analysis"]) if raw.get("analysis") else None
        if meta.get("isError") or (analysis or {}).get("isError"):
            return None
        series, start_pos = (
            await asyncio.to_thread(load_analysis_file, analysis.get("data_file"))
            if analysis else (None, None)
        )
        start_is_utc = bool((analysis or {}).get("startTimestamp"))
        start = (analysis or {}).get("startTimestamp") or workout.get("start_time")
        return await record_workout(
            profile, meta, analysis, series,
            start=start, start_position=start_pos, start_is_utc=start_is_utc, **context,
        )
