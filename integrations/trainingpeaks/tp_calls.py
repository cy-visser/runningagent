"""TrainingPeaks MCP tool invocation and range-chunked calendar/metrics fetch helpers."""

import asyncio
from datetime import timedelta
from typing import Any

from google.adk.tools import ToolContext

from .credentials import resolve_tp_cookie
from .mcp_toolsets import get_tp_tool
from ...shared.dates import ISO_DATE_FMT, parse_date
from ...shared.health_metrics import extract_health_metrics_dated
from ...shared.tp_payloads import coerce_mcp_payload

TP_MAX_RANGE_DAYS = 89  # TP list endpoints reject ranges > 90 days


class TPFetchError(RuntimeError):
    """A TrainingPeaks list call answered with an error envelope instead of data."""


async def run_tp_tool(tool_context: ToolContext, tool_name: str, **node_input: Any) -> Any:
    """Resolves a TrainingPeaks MCP tool by name for the active runner and invokes it."""
    tool = await get_tp_tool(tool_name, await resolve_tp_cookie(tool_context.state))
    return await tool_context.run_node(tool, node_input=node_input or None)


async def _fetch_list_chunk(tool_context: ToolContext, tool_name: str, key: str, start: str, end: str) -> list[dict]:
    raw = await run_tp_tool(tool_context, tool_name, start_date=start, end_date=end)
    payload = coerce_mcp_payload(raw) if raw else {}
    items = payload.get(key)
    if isinstance(items, list):
        return items
    if payload.get("isError") or payload.get("error_code") or payload.get("message"):
        raise TPFetchError(f"{tool_name} {start}..{end}: {payload.get('message') or 'error response'}")
    return []  # an empty calendar


async def fetch_list(tool_context: ToolContext, tool_name: str, key: str, start: Any, end: Any) -> list[dict]:
    """Fetches a dated TP list payload (workouts / notes) over any range, in chunks of at most
    TP_MAX_RANGE_DAYS, de-duplicated by id. Raises TPFetchError when TrainingPeaks answers with an
    error (never returns [] for a failed call), so callers can tell "nothing planned" from "no data"."""
    s, e = parse_date(start), parse_date(end)
    if s is None or e is None:
        raise TPFetchError(f"{tool_name}: invalid date range {start!r}..{end!r}")
    parts = await asyncio.gather(*(
        _fetch_list_chunk(tool_context, tool_name, key, cs, ce) for cs, ce in date_chunks(s, e)
    ))
    merged: dict[str, dict] = {}
    for item in (i for part in parts for i in part):
        item_id = item.get("id") if isinstance(item, dict) else None
        merged.setdefault(str(item_id) if item_id is not None else f"_{len(merged)}", item)
    return list(merged.values())


async def fetch_workouts(tool_context: ToolContext, start: Any, end: Any) -> list[dict]:
    return await fetch_list(tool_context, "tp_get_workouts", "workouts", start, end)


async def fetch_notes(tool_context: ToolContext, start: Any, end: Any) -> list[dict]:
    return await fetch_list(tool_context, "tp_list_notes", "notes", start, end)


def date_chunks(start: Any, end: Any) -> list[tuple[str, str]]:
    chunks, cur = [], start
    while cur <= end:
        chunk_end = min(end, cur + timedelta(days=TP_MAX_RANGE_DAYS))
        chunks.append((cur.strftime(ISO_DATE_FMT), chunk_end.strftime(ISO_DATE_FMT)))
        cur = chunk_end + timedelta(days=1)
    return chunks


async def fetch_workouts_range(tool_context: ToolContext, start: Any, end: Any) -> list[dict]:
    """Alias of fetch_workouts (which now chunks any range itself)."""
    return await fetch_workouts(tool_context, start, end)


async def fetch_metrics_range(tool_context: ToolContext, start: Any, end: Any) -> dict:
    raws = await asyncio.gather(*(
        run_tp_tool(tool_context, "tp_get_metrics", start_date=s, end_date=e) for s, e in date_chunks(start, end)
    ))
    merged: dict[str, list] = {"sleep": [], "hrv": [], "rhr": []}
    for raw in raws:
        for key, values in extract_health_metrics_dated(raw).items():
            merged[key].extend(values)
    return merged
