"""TrainingPeaks create/update/delete dispatch and shared throttled batch execution (pure code)."""

import asyncio
import logging
import re
from typing import Any, Awaitable, Callable, Iterable, TypeVar

from google.adk.tools import ToolContext

from ..integrations.trainingpeaks import tp_calls
from .tp_payloads import coerce_mcp_payload

logger = logging.getLogger(__name__)

# Staged change kinds and actions (shared by the workout creator and the plan builder).
KIND_WORKOUT = "workout"
KIND_NOTE = "note"
KIND_EVENT = "event"
ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_DELETE = "delete"

WRITE_CONCURRENCY = 3
BACKOFF_SECONDS = (2, 4, 8)
_RATE_LIMITED = re.compile(r"\b429\b|too many requests", re.IGNORECASE)

# Per-action differences between the create and update MCP tools.
_CREATE_SPEC = {"tool": "tp_create_workout", "duration_cast": lambda v: int(round(v)), "verb": "create"}
_UPDATE_SPEC = {"tool": "tp_update_workout", "duration_cast": lambda v: int(round(v)), "verb": "update"}

T = TypeVar("T")
R = TypeVar("R")


def is_rate_limited_error(error: Any) -> bool:
    return bool(_RATE_LIMITED.search(str(error or "")))


async def _run(tool_context: ToolContext, tool: str, verb: str, what: str, node_input: dict) -> dict[str, Any]:
    """Runs one TP write; returns {"ok": True, "id": ...} or {"ok": False, "error": ...}."""
    try:
        result = await tp_calls.run_tp_tool(tool_context, tool, **node_input)
    except Exception as e:
        logger.error("Failed to %s %s (%s): %s", verb, what, node_input.get("date"), e)
        return {"ok": False, "error": f"Failed to {verb} {what}: {e}"}
    data = coerce_mcp_payload(result)
    if data.get("isError"):
        return {"ok": False, "error": str(data.get("message") or "Unknown error")}
    return {"ok": True, "id": data.get("id") or data.get("workout_id") or data.get("event_id")}


async def write_workout(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Creates or updates one resolved workout change (update when it carries a workout_id).

    An update writes only what the coach changed: fields listed in `inherited` (the current workout's
    title / planned totals, shown on the card) are left to TrainingPeaks.
    """
    spec = _UPDATE_SPEC if change.get("workout_id") else _CREATE_SPEC
    inherited = set(change.get("inherited") or ()) if change.get("workout_id") else set()

    def changed(field: str) -> bool:
        return change.get(field) is not None and field not in inherited

    node_input: dict[str, Any] = {"date": change["date"], "sport": change["sport"]}
    if changed("title"):
        node_input["title"] = change["title"]
    if change.get("workout_id"):
        node_input["workout_id"] = change["workout_id"]
    if changed("duration_minutes"):
        node_input["duration_minutes"] = spec["duration_cast"](change["duration_minutes"])
    if changed("distance_km"):
        node_input["distance_km"] = float(change["distance_km"])
    if changed("tss_planned"):
        node_input["tss_planned"] = float(change["tss_planned"])
    if change.get("description"):
        node_input["description"] = change["description"]
    if change.get("tags"):
        node_input["tags"] = str(change["tags"])
    if change.get("structured_workout"):
        node_input["structured_workout"] = change["structured_workout"]
    result = await _run(tool_context, spec["tool"], spec["verb"], "workout", node_input)
    if result["ok"] and change.get("workout_id"):
        result["id"] = change["workout_id"]
    return result


async def write_note(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Creates one calendar note."""
    node_input: dict[str, Any] = {"date": change["date"][:10], "title": change["title"]}
    if change.get("description"):
        node_input["description"] = change["description"]
    return await _run(tool_context, "tp_create_note", "create", "note", node_input)


async def write_event(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Creates or updates one TrainingPeaks Calendar Event (update when `event_id` is set)."""
    is_update = bool(change.get("event_id"))
    tool = "tp_update_event" if is_update else "tp_create_event"
    verb = "update" if is_update else "create"
    name = change.get("name") or change.get("title") or "Race Event"
    node_input: dict[str, Any] = {
        "name": str(name),
        "date": str(change["date"])[:10],
    }
    if is_update:
        node_input["event_id"] = str(change["event_id"])
    for key in (
        "event_type",
        "priority",
        "distance_km",
        "description",
        "race_type_duration",
        "goal_distance_km",
        "goal_time",
        "goal_place",
        "goal_finish",
        "goal_pr",
    ):
        if change.get(key) is not None:
            node_input[key] = change[key]
    result = await _run(tool_context, tool, verb, "event", node_input)
    if result["ok"] and is_update:
        result["id"] = str(change["event_id"])
    return result


async def delete_item(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Deletes one staged workout, calendar note, or calendar event."""
    kind = change.get("kind")
    if kind == KIND_NOTE:
        tool, what, item_id = "tp_delete_note", "note", {"note_id": change["note_id"]}
    elif kind == KIND_EVENT:
        tool, what, item_id = "tp_delete_event", "event", {"event_id": change["event_id"]}
    else:
        tool, what, item_id = "tp_delete_workout", "workout", {"workout_id": change["workout_id"]}
    result = await _run(tool_context, tool, "delete", what, item_id)
    return {**result, "id": next(iter(item_id.values()))} if result["ok"] else result


async def write_change(tool_context: ToolContext, change: dict) -> dict[str, Any]:
    """Writes one resolved staged change; returns the change (without its native builder) merged with its outcome."""
    if change.get("action") == ACTION_DELETE:
        writer = delete_item
    elif change.get("kind") == KIND_NOTE:
        writer = write_note
    elif change.get("kind") == KIND_EVENT:
        writer = write_event
    else:
        writer = write_workout
    outcome = await writer(tool_context, change)
    return {**{k: v for k, v in change.items() if k != "structured_workout"}, **outcome}


async def write_with_backoff(
    tool_context: ToolContext,
    change: dict,
    gate: asyncio.Semaphore,
    *,
    unpaused: asyncio.Event | None = None,
    cooldown_state: list[int] | None = None,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> dict[str, Any]:
    """Writes one change under `gate` (`WRITE_CONCURRENCY`), backing off 2s, 4s, 8s on 429s and pausing queued tasks."""
    for delay in (*BACKOFF_SECONDS, None):
        if unpaused is not None:
            await unpaused.wait()
        async with gate:
            result = await write_change(tool_context, change)
        if result.get("ok") or delay is None or not is_rate_limited_error(result.get("error")):
            return result
        if unpaused is not None and cooldown_state is not None:
            cooldown_state[0] += 1
            unpaused.clear()
        try:
            await sleep(delay)
        finally:
            if unpaused is not None and cooldown_state is not None:
                cooldown_state[0] -= 1
                if cooldown_state[0] <= 0:
                    unpaused.set()
    return result


async def write_changes_throttled(
    tool_context: ToolContext,
    changes: Iterable[dict],
    *,
    concurrency: int = WRITE_CONCURRENCY,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> list[dict[str, Any]]:
    """Writes any number of staged changes (1..150+) with bounded concurrency and shared global 429 cooldown."""
    items = list(changes)
    if not items:
        return []
    gate = asyncio.Semaphore(concurrency)
    unpaused = asyncio.Event()
    unpaused.set()
    cooldown_state = [0]
    return list(
        await asyncio.gather(
            *(
                write_with_backoff(
                    tool_context, c, gate, unpaused=unpaused, cooldown_state=cooldown_state, sleep=sleep
                )
                for c in items
            )
        )
    )


async def run_throttled(
    items: Iterable[T],
    fn: Callable[[T], Awaitable[R]],
    *,
    concurrency: int = WRITE_CONCURRENCY,
) -> list[R]:
    """Runs async `fn(item)` across `items` with bounded concurrency so large batches never burst TrainingPeaks."""
    seq = list(items)
    if not seq:
        return []
    gate = asyncio.Semaphore(concurrency)

    async def _one(item: T) -> R:
        async with gate:
            return await fn(item)

    return list(await asyncio.gather(*(_one(x) for x in seq)))
