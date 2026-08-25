from __future__ import annotations
import functools
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional
from ..utils import parse_iso_timestamp

@functools.lru_cache(maxsize=128)
def geocode_location(location: str) -> Optional[tuple[float, float]]:
    """Helper to geocode a location string to (latitude, longitude) with LRU caching."""
    try:
        city = location.split(",")[0].strip() if location else ""
        if not city:
            return None
        geocode_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=en&format=json"
        req = urllib.request.Request(geocode_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            geocode_data = json.loads(response.read().decode())
        if geocode_data.get("results"):
            result = geocode_data["results"][0]
            return float(result["latitude"]), float(result["longitude"])
    except Exception as e:
        print(f"Geocoding error for '{location}': {e}")
    return None

def get_weather_for_dates(
    location: str,
    dates: list[str],
    lat: Optional[float] = None,
    lon: Optional[float] = None
) -> str:
    """Fetches weather data (daily and hourly) for a list of dates/timestamps in a single API call.
    Bypasses geocoding if lat and lon are provided.
    """
    if not dates:
        return "No dates provided."
        
    try:
        resolved_name = location
        if lat is None or lon is None:
            coords = geocode_location(location)
            if not coords:
                return f"Could not geocode location: {location}"
            lat, lon = coords
            
        parsed_dates = []
        input_mapping = []  # List of (input_str, date_str, hour_int)
        
        for d in dates:
            dt = parse_iso_timestamp(d)
            if dt:
                parsed_dates.append(dt.date())
                has_hour = ("T" in str(d) or " " in str(d)) and len(str(d)) > 10
                hour_int = dt.hour if has_hour else None
                input_mapping.append((d, dt.strftime("%Y-%m-%d"), hour_int))
                
        if not parsed_dates:
            return "No valid dates could be parsed."
            
        min_date = min(parsed_dates)
        max_date = max(parsed_dates)
        
        today_date = datetime.now().date()
        if max_date > today_date + timedelta(days=16):
            limit_date_str = (today_date + timedelta(days=16)).strftime("%Y-%m-%d")
            return (
                f"Weather forecast is only available up to 16 days in advance. "
                f"Cannot fetch live weather for dates beyond {limit_date_str} "
                f"(requested range: {min_date.strftime('%Y-%m-%d')} to {max_date.strftime('%Y-%m-%d')})."
            )
            
        start_date_str = min_date.strftime("%Y-%m-%d")
        end_date_str = max_date.strftime("%Y-%m-%d")
        
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?"
            f"latitude={lat}&longitude={lon}&start_date={start_date_str}&end_date={end_date_str}"
            f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
            f"&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,wind_speed_10m"
            f"&timezone=auto"
        )
            
        req = urllib.request.Request(weather_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5.0) as response:
            weather_data = json.loads(response.read().decode())
            
        daily = weather_data.get("daily", {})
        hourly = weather_data.get("hourly", {})
        
        if not daily or not daily.get("temperature_2m_max"):
            return f"No weather data available for {resolved_name} in range {start_date_str} to {end_date_str}."
            
        # 1. Process Daily Weather
        times_daily = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        precips_daily = daily.get("precipitation_sum", [])
        winds_daily = daily.get("wind_speed_10m_max", [])
        
        daily_units = weather_data.get("daily_units", {})
        temp_unit = daily_units.get("temperature_2m_max", "°C")
        precip_unit = daily_units.get("precipitation_sum", "mm")
        wind_unit = daily_units.get("wind_speed_10m_max", "km/h")
        
        daily_map = {}
        for i, t_str in enumerate(times_daily):
            daily_map[t_str] = {
                "max_temp": f"{max_temps[i]}{temp_unit}",
                "min_temp": f"{min_temps[i]}{temp_unit}",
                "precipitation": f"{precips_daily[i]}{precip_unit}",
                "max_wind": f"{winds_daily[i]}{wind_unit}"
            }
            
        # 2. Process Hourly Weather
        times_hourly = hourly.get("time", [])
        temps_hourly = hourly.get("temperature_2m", [])
        humidity_hourly = hourly.get("relative_humidity_2m", [])
        apparent_hourly = hourly.get("apparent_temperature", [])
        precips_hourly = hourly.get("precipitation", [])
        winds_hourly = hourly.get("wind_speed_10m", [])
        
        hourly_units = weather_data.get("hourly_units", {})
        h_temp_unit = hourly_units.get("temperature_2m", "°C")
        h_humidity_unit = hourly_units.get("relative_humidity_2m", "%")
        h_precip_unit = hourly_units.get("precipitation", "mm")
        h_wind_unit = hourly_units.get("wind_speed_10m", "km/h")
        
        hourly_map = {}
        for i, t_str in enumerate(times_hourly):
            hourly_map[t_str] = {
                "temp": f"{temps_hourly[i]}{h_temp_unit}",
                "humidity": f"{humidity_hourly[i]}{h_humidity_unit}",
                "apparent": f"{apparent_hourly[i]}{h_temp_unit}",
                "precipitation": f"{precips_hourly[i]}{h_precip_unit}",
                "wind": f"{winds_hourly[i]}{h_wind_unit}"
            }
            
        # 3. Compile results compactly
        results = []
        for input_str, date_str, hour_int in input_mapping:
            d_weather = daily_map.get(date_str)
            if not d_weather:
                results.append(f"- {input_str}: No weather data found.")
                continue
                
            day_str = f"Day: {d_weather['min_temp']}-{d_weather['max_temp']}, Precip: {d_weather['precipitation']}, Wind: {d_weather['max_wind']}"
            
            if hour_int is not None:
                target_hour_str = f"{date_str}T{hour_int:02d}:00"
                h_weather = hourly_map.get(target_hour_str)
                if h_weather:
                    results.append(
                        f"- {input_str}: {h_weather['temp']} (feels {h_weather['apparent']}), "
                        f"{h_weather['humidity']} hum, {h_weather['wind']} wind, {h_weather['precipitation']} precip | [{day_str}]"
                    )
                else:
                    results.append(f"- {input_str}: [{day_str}]")
            else:
                results.append(f"- {input_str}: [{day_str}]")
                
        return f"Weather in {resolved_name} for requested dates/times:\n" + "\n".join(results)
        
    except Exception as e:
        print(f"Error in get_weather_for_dates: {e}")
        return f"Error fetching weather data: {e}"
