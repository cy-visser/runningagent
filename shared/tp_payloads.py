"""TrainingPeaks MCP envelope parsing and payload coercion."""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def parse_mcp_response(response: Any) -> Any:
    """Parses the JSON payload from a raw MCP tool response envelope."""
    if not response or not isinstance(response, dict):
        return None
    content = response.get("content", [])
    if not content:
        return None
    text = content[0].get("text", "")
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse MCP JSON payload: %s", e)
        return None


def coerce_mcp_payload(response: Any, default: Optional[dict] = None) -> dict:
    """Best-effort coercion of an MCP tool result into a dictionary.

    Falls back through the MCP envelope, a raw dict, a raw JSON string, and
    finally a plain-text message so callers never have to branch themselves.
    """
    parsed = parse_mcp_response(response)
    if isinstance(parsed, dict):
        return parsed

    if isinstance(response, dict):
        content = response.get("content") or []
        first = content[0] if isinstance(content, list) and content else None
        text = first.get("text") if isinstance(first, dict) else None
        if text:
            return {"isError": bool(response.get("isError")), "message": text}
        return response
    if isinstance(response, str):
        try:
            decoded = json.loads(response)
        except json.JSONDecodeError:
            return {"message": response}
        return decoded if isinstance(decoded, dict) else {"message": response}

    return default if default is not None else {}
