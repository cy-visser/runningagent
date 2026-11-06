"""Reads time-series telemetry and the first GPS fix from `tp_analyze_workout` data files."""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SERIES_KEYS = ("time", "HeartRate", "Speed", "Power", "Distance")


def extract_start_position(points: list) -> Optional[dict]:
    """First valid GPS fix from tp_analyze_workout telemetry points, or None."""
    for p in points:
        if not isinstance(p, dict):
            continue
        lat, lon = p.get("PositionLat"), p.get("PositionLong")
        if type(lat) in (int, float) and type(lon) in (int, float):
            if (-90.0 <= lat <= 90.0) and (-180.0 <= lon <= 180.0) and not (lat == 0.0 and lon == 0.0):
                return {"lat": round(float(lat), 5), "lon": round(float(lon), 5)}
    return None


def load_analysis_file(path: Any) -> tuple[Optional[list[dict]], Optional[dict]]:
    """Reads the time series and first GPS fix tp_analyze_workout saved to `data_file`."""
    if not path:
        return None, None
    try:
        with open(str(path), encoding="utf-8") as f:
            points = json.load(f).get("data") or []
    except (OSError, ValueError, AttributeError) as e:
        logger.info("Time series unavailable (%s): %s", path, e)
        return None, None
    series = [{k: p[k] for k in _SERIES_KEYS if k in p} for p in points if isinstance(p, dict)]
    return (series or None), extract_start_position(points)
