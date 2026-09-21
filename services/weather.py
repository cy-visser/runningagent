from __future__ import annotations
import functools
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from ..utils.date_helpers import parse_iso_timestamp

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 5.0
FORECAST_HORIZON_DAYS = 16
_USER_AGENT = {"User-Agent": "Mozilla/5.0"}


def _fetch_json(url: str) -> dict:
    """Performs a GET request and decodes the JSON response body."""
    req = urllib.request.Request(url, headers=_USER_AGENT)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode())


@functools.lru_cache(maxsize=128)
def geocode_location(location: str) -> Optional[tuple[float, float]]:
    """Helper to geocode a location string to (latitude, longitude) with LRU caching."""
    try:
        city = location.split(",")[0].strip() if location else ""
        if not city:
            return None
        geocode_url = (
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={urllib.parse.quote(city)}&count=1&language=en&format=json"
        )
        geocode_data = _fetch_json(geocode_url)
        if geocode_data.get("results"):
            result = geocode_data["results"][0]
            return float(result["latitude"]), float(result["longitude"])
    except Exception as e:
        logger.warning("Geocoding failed for '%s': %s", location, e)
    return None

def _build_condition_map(
    location: str,
    dates: list[str],
    lat: Optional[float],
    lon: Optional[float],
) -> tuple[Optional[str], dict[str, str]]:
    """Resolves per-input weather conditions.

    Returns (error_message, conditions) where `conditions` maps each input
    date/timestamp to a human-readable conditions string. Exactly one of the two
    is meaningful: on failure the map is empty and an error message is returned.
    """
    if not dates:
        return "No dates provided.", {}

    if lat is None or lon is None:
        coords = geocode_location(location)
        if not coords:
            return f"Could not geocode location: {location}", {}
        lat, lon = coords

    parsed_dates = []
    input_mapping = []  # (input_str, date_str, hour_int)
    for d in dates:
        dt = parse_iso_timestamp(d)
        if not dt:
            continue
        parsed_dates.append(dt.date())
        has_hour = ("T" in str(d) or " " in str(d)) and len(str(d)) > 10
        input_mapping.append((d, dt.strftime("%Y-%m-%d"), dt.hour if has_hour else None))

    if not parsed_dates:
        return "No valid dates could be parsed.", {}

    min_date, max_date = min(parsed_dates), max(parsed_dates)
    horizon = datetime.now().date() + timedelta(days=FORECAST_HORIZON_DAYS)
    if max_date > horizon:
        return (
            f"Weather forecast is only available up to {FORECAST_HORIZON_DAYS} days in advance. "
            f"Cannot fetch live weather for dates beyond {horizon.strftime('%Y-%m-%d')} "
            f"(requested range: {min_date} to {max_date})."
        ), {}

    weather_url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&start_date={min_date}&end_date={max_date}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
        "&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m"
        "&timezone=auto"
    )
    weather_data = _fetch_json(weather_url)

    daily = weather_data.get("daily", {})
    hourly = weather_data.get("hourly", {})
    if not daily or not daily.get("temperature_2m_max"):
        return f"No weather data available for {location} in range {min_date} to {max_date}.", {}

    daily_units = weather_data.get("daily_units", {})
    temp_unit = daily_units.get("temperature_2m_max", "°C")
    precip_unit = daily_units.get("precipitation_sum", "mm")
    wind_unit = daily_units.get("wind_speed_10m_max", "km/h")

    daily_map = {
        t_str: (
            f"Day: {daily['temperature_2m_min'][i]}{temp_unit}-{daily['temperature_2m_max'][i]}{temp_unit}, "
            f"Precip: {daily['precipitation_sum'][i]}{precip_unit}, "
            f"Wind: {daily['wind_speed_10m_max'][i]}{wind_unit}"
        )
        for i, t_str in enumerate(daily.get("time", []))
    }

    hourly_units = weather_data.get("hourly_units", {})
    h_temp_unit = hourly_units.get("temperature_2m", "°C")
    h_humidity_unit = hourly_units.get("relative_humidity_2m", "%")
    h_precip_unit = hourly_units.get("precipitation", "mm")
    h_wind_unit = hourly_units.get("wind_speed_10m", "km/h")

    hourly_map = {
        t_str: (
            f"{hourly['temperature_2m'][i]}{h_temp_unit} "
            f"(feels {hourly['apparent_temperature'][i]}{h_temp_unit}), "
            f"{hourly['relative_humidity_2m'][i]}{h_humidity_unit} hum, "
            f"{hourly['wind_speed_10m'][i]}{h_wind_unit} wind, "
            f"{hourly['precipitation'][i]}{h_precip_unit} precip"
        )
        for i, t_str in enumerate(hourly.get("time", []))
    }

    conditions: dict[str, str] = {}
    for input_str, date_str, hour_int in input_mapping:
        day_str = daily_map.get(date_str)
        if not day_str:
            conditions[input_str] = "No weather data found."
            continue
        hour_str = hourly_map.get(f"{date_str}T{hour_int:02d}:00") if hour_int is not None else None
        conditions[input_str] = f"{hour_str} | [{day_str}]" if hour_str else f"[{day_str}]"

    return None, conditions


def get_weather_conditions(
    location: str,
    dates: list[str],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> dict[str, str]:
    """Returns a {date_or_timestamp: conditions} map, or an empty map on failure.

    Use this when the caller needs to attach conditions to individual records.
    For narrative text destined for the model, use `get_weather_for_dates`.
    """
    try:
        error, conditions = _build_condition_map(location, dates, lat, lon)
    except Exception as e:
        logger.warning("Weather lookup failed for '%s': %s", location, e)
        return {}
    if error:
        logger.info("Weather unavailable for '%s': %s", location, error)
        return {}
    return conditions


def get_weather_for_dates(
    location: str,
    dates: list[str],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> str:
    """Fetches weather data (daily and hourly) for a list of dates/timestamps in a single API call.

    Bypasses geocoding if lat and lon are provided.
    """
    try:
        error, conditions = _build_condition_map(location, dates, lat, lon)
    except Exception as e:
        logger.warning("Weather lookup failed for '%s': %s", location, e)
        return f"Error fetching weather data: {e}"

    if error:
        return error

    lines = [f"- {input_str}: {summary}" for input_str, summary in conditions.items()]
    return f"Weather in {location} for requested dates/times:\n" + "\n".join(lines)
