import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import logging
import os
import shutil
from typing import Any

from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from ..package_paths import PACKAGE_DIR

logger = logging.getLogger(__name__)

tp_mcp_path = shutil.which("tp-mcp") or os.path.join(
    PACKAGE_DIR, "trainingpeaks-mcp", ".venv", "bin", "tp-mcp"
)

TP_MCP_CONNECT_TIMEOUT_S = float(os.environ.get("TP_MCP_CONNECT_TIMEOUT_S", "30"))
TP_MCP_MAX_TOOLSETS = max(1, int(os.environ.get("TP_MCP_MAX_TOOLSETS", "8")))


@dataclass
class _ToolsetEntry:
    toolset: Any
    tools_by_name: dict[str, Any] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_toolsets_by_key: OrderedDict[str, _ToolsetEntry] = OrderedDict()


def _cookie_key(cookie: str) -> str:
    """Non-reversible cache key so a rotated cookie starts a fresh tp-mcp subprocess."""
    return hashlib.sha256(cookie.encode("utf-8")).hexdigest()[:16]


def _build_toolset(cookie: str) -> Any:
    """Builds an isolated tp-mcp subprocess scoped to a single runner's cookie."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=tp_mcp_path,
                args=["serve"],
                env={"TP_AUTH_COOKIE": cookie},
            ),
            timeout=TP_MCP_CONNECT_TIMEOUT_S,
        )
    )


async def _close_entry(entry: _ToolsetEntry) -> None:
    close_fn = getattr(entry.toolset, "close", None)
    if callable(close_fn):
        try:
            res = close_fn()
            if asyncio.iscoroutine(res):
                await res
        except Exception as exc:
            logger.debug("Ignoring error closing evicted tp-mcp toolset: %s", exc)


def reset_tp_tool_cache() -> None:
    """Forgets all cached per-cookie toolsets."""
    _toolsets_by_key.clear()


async def _ensure_entry(cookie: str) -> _ToolsetEntry:
    clean_cookie = (cookie or "").strip()
    if not clean_cookie:
        raise ValueError("A TrainingPeaks auth cookie is required to resolve MCP tools.")

    key = _cookie_key(clean_cookie)
    evicted: list[_ToolsetEntry] = []
    entry = _toolsets_by_key.get(key)
    if entry is None:
        entry = _ToolsetEntry(toolset=_build_toolset(clean_cookie))
        _toolsets_by_key[key] = entry
        while len(_toolsets_by_key) > TP_MCP_MAX_TOOLSETS:
            _, oldest = _toolsets_by_key.popitem(last=False)
            if oldest is not entry:
                evicted.append(oldest)
    else:
        _toolsets_by_key.move_to_end(key)

    for old in evicted:
        await _close_entry(old)

    async with entry.lock:
        if not entry.tools_by_name:
            try:
                tools = await entry.toolset.get_tools()
            except Exception:
                _toolsets_by_key.pop(key, None)
                await _close_entry(entry)
                raise
            entry.tools_by_name.update({t.name: t for t in tools})
    return entry


async def warm_tp_toolset(cookie: str) -> None:
    """Pre-starts and initializes the runner's tp-mcp subprocess if not already warm."""
    await _ensure_entry(cookie)


async def get_tp_tool(name: str, cookie: str) -> Any:
    """Returns the named TrainingPeaks MCP tool from that cookie's own tp-mcp subprocess."""
    entry = await _ensure_entry(cookie)
    if name not in entry.tools_by_name:
        async with entry.lock:
            if name not in entry.tools_by_name:
                tools = await entry.toolset.get_tools()
                entry.tools_by_name.clear()
                entry.tools_by_name.update({t.name: t for t in tools})
    try:
        return entry.tools_by_name[name]
    except KeyError:
        raise ValueError(f"Tool '{name}' not found in TrainingPeaks MCP toolset.") from None
