import logging
import os
import shutil
from typing import Any

from google.adk.tools import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from .secrets import inject_production_secrets
from ..utils.paths import PACKAGE_DIR

logger = logging.getLogger(__name__)

tp_mcp_path = shutil.which("tp-mcp") or os.path.join(
    PACKAGE_DIR, "trainingpeaks-mcp", ".venv", "bin", "tp-mcp"
)

TP_MCP_CONNECT_TIMEOUT_S = float(os.environ.get("TP_MCP_CONNECT_TIMEOUT_S", "30"))

_tp_toolset: Any = None
_tp_tools_by_name: dict[str, Any] = {}


def _build_toolset() -> Any:
    # Fetches the cookie from Secret Manager when it isn't in the environment.
    inject_production_secrets()
    cookie_value = os.environ.get("TP_AUTH_COOKIE")
    if not cookie_value:
        logger.warning("TP_AUTH_COOKIE is not set; TrainingPeaks calls will likely fail.")
    tp_env = {"TP_AUTH_COOKIE": cookie_value} if cookie_value else None
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=tp_mcp_path,
                args=["serve"],
                env=tp_env,
            ),
            timeout=TP_MCP_CONNECT_TIMEOUT_S,
        )
    )


def reset_tp_tool_cache() -> None:
    """Forgets the cached tool map (e.g. after an MCP connection error)."""
    _tp_tools_by_name.clear()


async def get_tp_tool(name: str) -> Any:
    """Returns a TrainingPeaks MCP tool by name; the tool list is fetched once and cached."""
    global _tp_toolset
    if _tp_toolset is None:
        _tp_toolset = _build_toolset()

    if name not in _tp_tools_by_name:
        try:
            tools = await _tp_toolset.get_tools()
        except Exception:
            reset_tp_tool_cache()
            raise
        _tp_tools_by_name.clear()
        _tp_tools_by_name.update({t.name: t for t in tools})

    try:
        return _tp_tools_by_name[name]
    except KeyError:
        raise ValueError(f"Tool '{name}' not found in TrainingPeaks MCP toolset.") from None
