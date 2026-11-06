"""Runner location resolution and async Open-Meteo weather wrappers."""

import asyncio
from typing import Any, Optional

from ..integrations import open_meteo


def location_args(profile: dict) -> Optional[dict[str, Any]]:
    """Returns the geo kwargs for a weather lookup, or None if the runner has no location."""
    loc = profile.get("location", "")
    lat = profile.get("latitude")
    lon = profile.get("longitude")
    if not loc and (lat is None or lon is None):
        return None
    return {"location": loc or "", "lat": lat, "lon": lon}


def geo_for_position(profile: dict, position: Optional[dict] = None) -> Optional[dict[str, Any]]:
    """Returns geo kwargs preferring GPS start coordinates when available, else profile home."""
    if isinstance(position, dict):
        lat, lon = position.get("lat"), position.get("lon")
        if type(lat) in (int, float) and type(lon) in (int, float):
            return {"location": f"{lat:.2f}, {lon:.2f}", "lat": float(lat), "lon": float(lon)}
    return location_args(profile)


async def fetch_weather_map(
    profile: dict,
    timestamps: list[str],
    *,
    position: Optional[dict] = None,
    utc: bool = False,
) -> dict[str, str]:
    """Returns {timestamp: conditions} for the given timestamps, or {} when unavailable."""
    geo = geo_for_position(profile, position)
    if not geo or not timestamps:
        return {}
    return await asyncio.to_thread(open_meteo.get_weather_conditions, dates=timestamps, utc=utc, **geo)


async def fetch_weather_text(
    profile: dict,
    dates: list[str],
    *,
    position: Optional[dict] = None,
    utc: bool = False,
) -> str:
    """Returns a formatted weather narrative for the given dates, or '' when unavailable."""
    geo = geo_for_position(profile, position)
    if not geo or not dates:
        return ""
    conditions = await asyncio.to_thread(open_meteo.get_weather_conditions, dates=dates, utc=utc, **geo)
    label = geo["location"] if position else profile.get("location", "")
    return open_meteo.format_weather_conditions(label, conditions)


def weather_at(
    profile: dict,
    start: str,
    *,
    position: Optional[dict] = None,
    utc: bool = False,
) -> Optional[dict]:
    """Structured conditions at the run's start (blocking: geocoding + HTTP; call in a thread)."""
    lat = position.get("lat") if isinstance(position, dict) else None
    lon = position.get("lon") if isinstance(position, dict) else None
    if type(lat) not in (int, float) or type(lon) not in (int, float):
        lat, lon = profile.get("latitude"), profile.get("longitude")
        if (lat is None or lon is None) and profile.get("location"):
            lat, lon = open_meteo.geocode_location(profile["location"]) or (None, None)
    return open_meteo.get_conditions_at(lat, lon, start, utc=utc) if lat is not None and lon is not None else None
