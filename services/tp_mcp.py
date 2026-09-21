import logging
import os
import shutil
from typing import Any

from google.adk.tools import McpToolset
from mcp import StdioServerParameters

from .secrets import inject_production_secrets
from ..utils.paths import PACKAGE_DIR

logger = logging.getLogger(__name__)

tp_mcp_path = shutil.which("tp-mcp") or os.path.join(
    PACKAGE_DIR, "trainingpeaks-mcp", ".venv", "bin", "tp-mcp"
)

_tp_toolset: Any = None


async def get_tp_tool(name: str) -> Any:
    """Asynchronously retrieves a specific tool from the TrainingPeaks MCP toolset by name."""
    global _tp_toolset
    if _tp_toolset is None:
        # Inject production secrets if in production environment
        inject_production_secrets()
        cookie_value = os.environ.get("TP_AUTH_COOKIE")
        if not cookie_value:
            logger.warning("TP_AUTH_COOKIE is not set; TrainingPeaks calls will likely fail.")
        tp_env = {"TP_AUTH_COOKIE": cookie_value} if cookie_value else None

        _tp_toolset = McpToolset(
            connection_params=StdioServerParameters(
                command=tp_mcp_path,
                args=["serve"],
                env=tp_env,
            )
        )

    tools = await _tp_toolset.get_tools()
    try:
        return next(t for t in tools if t.name == name)
    except StopIteration:
        raise ValueError(f"Tool '{name}' not found in TrainingPeaks MCP toolset.") from None
