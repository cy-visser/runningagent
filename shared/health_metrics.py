"""Extraction and formatting of TrainingPeaks sleep, HRV and resting-HR metrics."""

from typing import Any, Optional

from .dates import parse_date
from .tp_payloads import coerce_mcp_payload, parse_mcp_response

HEALTH_BASELINE_DAYS = 28

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


def extract_health_metrics_dated(metrics_raw: Any) -> dict[str, list[tuple[Any, float]]]:
    """Like extract_health_metrics, but keeps the date: {'sleep'|'hrv'|'rhr': [(date, value)]}."""
    metrics_data = coerce_mcp_payload(metrics_raw) if metrics_raw else {}
    metrics_list = metrics_data.get("metrics", [])
    keys = {METRIC_TYPE_SLEEP: "sleep", METRIC_TYPE_HRV: "hrv", METRIC_TYPE_RHR: "rhr"}
    out: dict[str, list[tuple[Any, float]]] = {"sleep": [], "hrv": [], "rhr": []}
    if not isinstance(metrics_list, list):
        return out
    for m in metrics_list:
        if not isinstance(m, dict):
            continue
        day = parse_date(m.get("timeStamp"))
        for detail in m.get("details", []) or []:
            key = keys.get(detail.get("type"))
            val = detail.get("value")
            if key is None or val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            d = day or parse_date(detail.get("time"))
            if d is not None:
                out[key].append((d, val))
    return out


def format_recovery_metrics(metrics_data: Optional[dict]) -> str:
    """Formats sleep averages, HRV trends, and resting pulse compactly."""
    if metrics_data is None:
        return ""
    sleep_hours = metrics_data.get("sleep", [])
    hrv_clean = metrics_data.get("hrv", [])
    rhr_clean = metrics_data.get("rhr", [])

    sleep_avg = round(sum(sleep_hours) / len(sleep_hours), 2) if sleep_hours else "N/A"
    hrv_trend = ", ".join(str(h) for h in hrv_clean[-5:]) if hrv_clean else "N/A"
    hrv_latest = hrv_clean[-1] if hrv_clean else "N/A"
    rhr_trend = ", ".join(str(r) for r in rhr_clean[-5:]) if rhr_clean else "N/A"
    rhr_latest = rhr_clean[-1] if rhr_clean else "N/A"

    return (
        f"- Sleep: Avg {sleep_avg} hrs/night\n"
        f"- HRV Trend: [{hrv_trend}] (Latest: {hrv_latest} ms)\n"
        f"- RHR Trend: [{rhr_trend}] (Latest: {rhr_latest} bpm)"
    )
