import json
from typing import Any

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
    except Exception as e:
        print(f"Error parsing MCP JSON: {e}")
        return None

def extract_health_metrics(metrics_raw: Any) -> dict[str, list[float]]:
    """Extracts sleep, HRV, and RHR (Pulse) values from raw TrainingPeaks metrics.
    Returns a dictionary of lists: {'sleep': [...], 'hrv': [...], 'rhr': [...]}
    """
    metrics_data = parse_mcp_response(metrics_raw) or {}
    metrics_list = metrics_data.get("metrics", [])
    
    sleep_hours = []
    hrv_values = []
    rhr_values = []
    
    if isinstance(metrics_list, list):
        for m in metrics_list:
            details = m.get("details", [])
            for detail in details:
                val = detail.get("value")
                if val is None:
                    continue
                m_type = detail.get("type")
                if m_type == 6:       # Sleep
                    sleep_hours.append(val)
                elif m_type == 60:    # HRV
                    hrv_values.append(val)
                elif m_type == 5:     # Pulse (RHR)
                    rhr_values.append(val)
                    
    return {
        "sleep": sleep_hours,
        "hrv": hrv_values,
        "rhr": rhr_values
    }
