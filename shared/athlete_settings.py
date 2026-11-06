"""Extraction of athlete threshold and HR-zone settings from TrainingPeaks payloads."""

from typing import Any, Optional

from .sports import BIKE_SPORTS
from .tp_payloads import coerce_mcp_payload
from .units import as_float

# TP zone groups: workoutTypeId 3 = run, 2 = bike, 0 = default.
_TYPE_IDS = {"run": (3, 0), "bike": (2, 0)}


def sport_family(sport: Optional[str]) -> str:
    return "bike" if (sport or "").strip().lower() in BIKE_SPORTS else "run"


def extract_thresholds(settings_raw: Any) -> dict[str, Optional[float]]:
    """Run LTHR (bpm) and threshold speed (m/s) from tp_get_athlete_settings.

    Prefers the run-specific zone group (workoutTypeId 3) over the default (0).
    """
    payload = coerce_mcp_payload(settings_raw) if settings_raw else {}
    settings = payload.get("settings", payload) if isinstance(payload, dict) else {}

    def pick(groups: Any) -> Optional[float]:
        if not isinstance(groups, list):
            return None
        by_type = {g.get("workoutTypeId"): g for g in groups if isinstance(g, dict)}
        for type_id in (3, 0):
            value = as_float((by_type.get(type_id) or {}).get("threshold"))
            if value and value > 0:
                return value
        return None

    return {
        "lthr": pick(settings.get("heartRateZones")),
        "threshold_speed": pick(settings.get("speedZones")),
    }


def extract_hr_zones(settings_raw: Any) -> list[dict]:
    """Run HR zones [{"label", "min", "max"}] from tp_get_athlete_settings (run group, else default)."""
    payload = coerce_mcp_payload(settings_raw) if settings_raw else {}
    settings = payload.get("settings", payload) if isinstance(payload, dict) else {}
    groups = {g.get("workoutTypeId"): g for g in settings.get("heartRateZones") or [] if isinstance(g, dict)}
    for type_id in (3, 0):
        zones = (groups.get(type_id) or {}).get("zones")
        if isinstance(zones, list) and zones:
            return [{"label": z.get("label"), "min": as_float(z.get("minimum")), "max": as_float(z.get("maximum"))}
                    for z in zones if isinstance(z, dict)]
    return []


def sport_thresholds(settings_raw: Any, sport: Optional[str]) -> dict[str, Optional[float]]:
    """Threshold speed (m/s), LTHR (bpm) and FTP (W) from tp_get_athlete_settings for the sport."""
    payload = coerce_mcp_payload(settings_raw) if settings_raw else {}
    settings = payload.get("settings", payload) if isinstance(payload, dict) else {}
    type_ids = _TYPE_IDS[sport_family(sport)]

    def pick(groups: Any) -> Optional[float]:
        if not isinstance(groups, list):
            return None
        by_type = {g.get("workoutTypeId"): g for g in groups if isinstance(g, dict)}
        for type_id in type_ids:
            value = as_float((by_type.get(type_id) or {}).get("threshold"))
            if value and value > 0:
                return value
        return None

    return {
        "threshold_speed": pick(settings.get("speedZones")),
        "lthr": pick(settings.get("heartRateZones")),
        "ftp": pick(settings.get("powerZones")),
    }
