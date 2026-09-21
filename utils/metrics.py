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
        return response
    if isinstance(response, str):
        try:
            decoded = json.loads(response)
        except json.JSONDecodeError:
            return {"message": response}
        return decoded if isinstance(decoded, dict) else {"message": response}

    return default if default is not None else {}


# TrainingPeaks metric type identifiers used in the `details` payload.
METRIC_TYPE_SLEEP = 6
METRIC_TYPE_HRV = 60
METRIC_TYPE_RHR = 5


def extract_health_metrics(metrics_raw: Any) -> dict[str, list[float]]:
    """Extracts sleep, HRV, and RHR (Pulse) values from raw TrainingPeaks metrics.

    Returns a dictionary of lists: {'sleep': [...], 'hrv': [...], 'rhr': [...]}
    """
    metrics_data = parse_mcp_response(metrics_raw) or {}
    metrics_list = metrics_data.get("metrics", [])

    buckets: dict[int, list[float]] = {
        METRIC_TYPE_SLEEP: [],
        METRIC_TYPE_HRV: [],
        METRIC_TYPE_RHR: [],
    }

    if isinstance(metrics_list, list):
        for m in metrics_list:
            for detail in m.get("details", []):
                val = detail.get("value")
                if val is None:
                    continue
                bucket = buckets.get(detail.get("type"))
                if bucket is not None:
                    bucket.append(val)

    return {
        "sleep": buckets[METRIC_TYPE_SLEEP],
        "hrv": buckets[METRIC_TYPE_HRV],
        "rhr": buckets[METRIC_TYPE_RHR],
    }
