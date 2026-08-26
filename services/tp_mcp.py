import os
import shutil
from typing import Any
from google.adk.tools import McpToolset
from mcp import StdioServerParameters
from .secrets import inject_production_secrets

current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tp_mcp_path = shutil.which("tp-mcp") or os.path.join(
    current_dir, "trainingpeaks-mcp", ".venv", "bin", "tp-mcp"
)

_tp_toolset: Any = None

async def get_tp_tool(name: str) -> Any:
    """Asynchronously retrieves a specific tool from the TrainingPeaks MCP toolset by name."""
    global _tp_toolset
    if _tp_toolset is None:
        # Inject production secrets if in production environment
        inject_production_secrets()
        cookie_value = os.environ.get("TP_AUTH_COOKIE")
        tp_env = {"TP_AUTH_COOKIE": cookie_value} if cookie_value else None

        _tp_toolset = McpToolset(
            connection_params=StdioServerParameters(
                command=tp_mcp_path,
                args=["serve"],
                env=tp_env
            )
        )
    tools = await _tp_toolset.get_tools()
    try:
        return next(t for t in tools if t.name == name)
    except StopIteration:
        raise ValueError(f"Tool '{name}' not found in TrainingPeaks MCP toolset.")
