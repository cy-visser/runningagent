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
_USER_AGENT = {"User-Agent": "running-coach/1.0"}


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
    utc: bool = False,
) -> tuple[Optional[str], dict[str, str]]:
    """Resolves per-input weather conditions.

    Returns (error_message, conditions) where `conditions` maps each input
    date/timestamp to a human-readable conditions string. Exactly one of the two
    is meaningful: on failure the map is empty and an error message is returned.
    When `utc=True`, timestamp inputs are treated as UTC and converted to the
    target location's local clock via Open-Meteo's `utc_offset_seconds`.
    """
    if not dates:
        return "No dates provided.", {}

    if lat is None or lon is None:
        coords = geocode_location(location)
        if not coords:
            return f"Could not geocode location: {location}", {}
        lat, lon = coords

    parsed: list[tuple[str, datetime, bool]] = []
    for d in dates:
        dt = parse_iso_timestamp(d)
        if not dt:
            continue
        has_hour = ("T" in str(d) or " " in str(d)) and len(str(d)) > 10
        parsed.append((d, dt, has_hour))

    if not parsed:
        return "No valid dates could be parsed.", {}

    min_date = min(dt.date() for _, dt, _ in parsed)
    max_date = max(dt.date() for _, dt, _ in parsed)
    horizon = datetime.now().date() + timedelta(days=FORECAST_HORIZON_DAYS)
    if max_date > horizon:
        return (
            f"Weather forecast is only available up to {FORECAST_HORIZON_DAYS} days in advance. "
            f"Cannot fetch live weather for dates beyond {horizon.strftime('%Y-%m-%d')} "
            f"(requested range: {min_date} to {max_date})."
        ), {}

    # A UTC timestamp near midnight can fall on the previous or next local day.
    query_start = min_date - timedelta(days=1) if utc else min_date
    query_end = min(horizon, max_date + timedelta(days=1)) if utc else max_date
    weather_url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&start_date={query_start}&end_date={query_end}"
        "&daily=temperature_2m_max,temperature_2m_min,apparent_temperature_max,"
        "relative_humidity_2m_mean,precipitation_sum,wind_speed_10m_max"
        "&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m"
        "&timezone=auto"
    )
    weather_data = _fetch_json(weather_url)
    offset = timedelta(seconds=int(weather_data.get("utc_offset_seconds") or 0)) if utc else timedelta(0)

    daily = weather_data.get("daily", {})
    hourly = weather_data.get("hourly", {})
    if not daily or not daily.get("temperature_2m_max"):
        return f"No weather data available for {location} in range {min_date} to {max_date}.", {}

    daily_units = weather_data.get("daily_units", {})
    temp_unit = daily_units.get("temperature_2m_max", "°C")
    precip_unit = daily_units.get("precipitation_sum", "mm")
    wind_unit = daily_units.get("wind_speed_10m_max", "km/h")
    hum_unit = daily_units.get("relative_humidity_2m_mean", "%")

    def _daily(key: str, i: int):
        values = daily.get(key) or []
        return values[i] if i < len(values) else None

    def _day_summary(i: int) -> str:
        parts = [f"Day: {_daily('temperature_2m_min', i)}{temp_unit}-{_daily('temperature_2m_max', i)}{temp_unit}"]
        feels = _daily("apparent_temperature_max", i)
        if feels is not None:
            parts.append(f"Feels max: {feels}{temp_unit}")
        humidity = _daily("relative_humidity_2m_mean", i)
        if humidity is not None:
            parts.append(f"Humidity: {humidity}{hum_unit}")
        parts.append(f"Precip: {_daily('precipitation_sum', i)}{precip_unit}")
        parts.append(f"Wind: {_daily('wind_speed_10m_max', i)}{wind_unit}")
        return ", ".join(parts)

    daily_map = {t_str: _day_summary(i) for i, t_str in enumerate(daily.get("time", []))}

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
    for input_str, dt, has_hour in parsed:
        local = (dt + offset) if has_hour else dt
        date_str = local.strftime("%Y-%m-%d")
        day_str = daily_map.get(date_str)
        if not day_str:
            conditions[input_str] = "No weather data found."
            continue
        hour_str = hourly_map.get(f"{date_str}T{local.hour:02d}:00") if has_hour else None
        conditions[input_str] = f"{hour_str} | [{day_str}]" if hour_str else f"[{day_str}]"

    return None, conditions


def get_weather_conditions(
    location: str,
    dates: list[str],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    utc: bool = False,
) -> dict[str, str]:
    """Returns a {date_or_timestamp: conditions} map, or an empty map on failure.

    Use this when the caller needs to attach conditions to individual records.
    For narrative text destined for the model, use `get_weather_for_dates`.
    """
    try:
        error, conditions = _build_condition_map(location, dates, lat, lon, utc=utc)
    except Exception as e:
        logger.warning("Weather lookup failed for '%s': %s", location, e)
        return {}
    if error:
        logger.info("Weather unavailable for '%s': %s", location, error)
        return {}
    return conditions


def format_weather_conditions(location: str, conditions: dict[str, str]) -> str:
    """Renders a {date_or_timestamp: conditions} map as model-facing narrative text."""
    if not conditions:
        return ""
    lines = [f"- {input_str}: {summary}" for input_str, summary in conditions.items()]
    return f"Weather in {location or 'your location'} for requested dates/times:\n" + "\n".join(lines)


def get_weather_for_dates(
    location: str,
    dates: list[str],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    utc: bool = False,
) -> str:
    """Fetches weather data (daily and hourly) for a list of dates/timestamps in a single API call.

    Bypasses geocoding if lat and lon are provided. Failures are returned as a
    human-readable message (this is the ad-hoc tool path).
    """
    try:
        error, conditions = _build_condition_map(location, dates, lat, lon, utc=utc)
    except Exception as e:
        logger.warning("Weather lookup failed for '%s': %s", location, e)
        return f"Error fetching weather data: {e}"

    if error:
        return error
    return format_weather_conditions(location, conditions)


# The forecast API only serves ~92 days of history; older dates come from the archive API.
FORECAST_HISTORY_DAYS = 80


def get_conditions_at(lat: float, lon: float, timestamp: str, utc: bool = False) -> Optional[dict]:
    """Structured conditions at one timestamp (YYYY-MM-DDTHH:MM:SS), or None on failure.

    Returns {"temp_c", "feels_like_c", "humidity", "wind_kmh"} for the local hour
    of the timestamp (`utc=True` converts from UTC via `utc_offset_seconds`).
    """
    dt = parse_iso_timestamp(timestamp)
    if dt is None or lat is None or lon is None:
        return None
    start_day = (dt.date() - timedelta(days=1) if utc else dt.date()).isoformat()
    end_day = (dt.date() + timedelta(days=1) if utc else dt.date()).isoformat()
    old = dt.date() < datetime.now().date() - timedelta(days=FORECAST_HISTORY_DAYS)
    host = "https://archive-api.open-meteo.com/v1/archive" if old else "https://api.open-meteo.com/v1/forecast"
    url = (
        f"{host}?latitude={lat}&longitude={lon}&start_date={start_day}&end_date={end_day}"
        "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m&timezone=auto"
    )
    try:
        payload = _fetch_json(url)
        local = dt + timedelta(seconds=int(payload.get("utc_offset_seconds") or 0)) if utc else dt
        hourly = payload.get("hourly") or {}
        i = (hourly.get("time") or []).index(f"{local.strftime('%Y-%m-%d')}T{local.hour:02d}:00")
        return {
            "temp_c": hourly["temperature_2m"][i],
            "feels_like_c": hourly["apparent_temperature"][i],
            "humidity": hourly["relative_humidity_2m"][i],
            "wind_kmh": hourly["wind_speed_10m"][i],
        }
    except Exception as e:  # network, missing hour or missing key -> no weather on the record
        logger.info("Structured weather unavailable for %s: %s", timestamp, e)
        return None
