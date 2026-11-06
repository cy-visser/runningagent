"""TrainingPeaks MCP tool invocation and range-chunked calendar/metrics fetch helpers."""

import asyncio
from datetime import timedelta
from typing import Any

from google.adk.tools import ToolContext

from .credentials import resolve_tp_cookie
from .mcp_toolsets import get_tp_tool
from ...utils import coerce_mcp_payload, extract_health_metrics_dated
from ...utils.date_helpers import ISO_DATE_FMT

TP_MAX_RANGE_DAYS = 89  # TP list endpoints reject ranges > 90 days


async def run_tp_tool(tool_context: ToolContext, tool_name: str, **node_input: Any) -> Any:
    """Resolves a TrainingPeaks MCP tool by name for the active runner and invokes it."""
    tool = await get_tp_tool(tool_name, await resolve_tp_cookie(tool_context.state))
    return await tool_context.run_node(tool, node_input=node_input or None)


async def fetch_list(tool_context: ToolContext, tool_name: str, key: str, start: str, end: str) -> list[dict]:
    """Fetches a dated TP list payload (workouts / notes), returning [] when nothing is available."""
    raw = await run_tp_tool(tool_context, tool_name, start_date=start, end_date=end)
    items = coerce_mcp_payload(raw).get(key) if raw else None
    return items if isinstance(items, list) else []


async def fetch_workouts(tool_context: ToolContext, start: str, end: str) -> list[dict]:
    return await fetch_list(tool_context, "tp_get_workouts", "workouts", start, end)


async def fetch_notes(tool_context: ToolContext, start: str, end: str) -> list[dict]:
    return await fetch_list(tool_context, "tp_list_notes", "notes", start, end)


def date_chunks(start: Any, end: Any) -> list[tuple[str, str]]:
    chunks, cur = [], start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=TP_MAX_RANGE_DAYS))
        chunks.append((cur.strftime(ISO_DATE_FMT), chunk_end.strftime(ISO_DATE_FMT)))
        cur = chunk_end + timedelta(days=1)
    return chunks


async def fetch_workouts_range(tool_context: ToolContext, start: Any, end: Any) -> list[dict]:
    parts = await asyncio.gather(*(fetch_workouts(tool_context, s, e) for s, e in date_chunks(start, end)))
    return list({str(w.get("id")): w for part in parts for w in part}.values())


async def fetch_metrics_range(tool_context: ToolContext, start: Any, end: Any) -> dict:
    raws = await asyncio.gather(*(
        run_tp_tool(tool_context, "tp_get_metrics", start_date=s, end_date=e) for s, e in date_chunks(start, end)
    ))
    merged: dict[str, list] = {"sleep": [], "hrv": [], "rhr": []}
    for raw in raws:
        for key, values in extract_health_metrics_dated(raw).items():
            merged[key].extend(values)
    return merged
