"""Tool for workout analysis via the Peaksware analysis API."""

import asyncio
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from tp_mcp.client import TPClient, parse_workout_analysis
from tp_mcp.tools._validation import WorkoutIdInput, format_validation_error

logger = logging.getLogger("tp-mcp")

ANALYSIS_API_BASE = "https://api.peakswaresb.com"
ANALYSIS_TIMEOUT = 60.0
ANALYSIS_DATA_DIR = Path(tempfile.gettempdir()) / "tp-mcp" / "analysis"


def _save_analysis_json(workout_id: int, data: dict[str, Any]) -> str:
    """Save full analysis data to a JSON file.

    Returns:
        Absolute path to the saved file.
    """
    ANALYSIS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    filepath = ANALYSIS_DATA_DIR / f"workout_{workout_id}.json"
    filepath.write_text(json.dumps(data, indent=2))
    return str(filepath)


async def tp_analyze_workout(workout_id: str) -> dict[str, Any]:
    """Get detailed workout analysis including metrics, zones, and lap data.

    Full time-series data is saved to a JSON file for further analysis.

    Args:
        workout_id: The workout ID (from tp_get_workouts).

    Returns:
        Dict with totals, data channels, lap data, and path to full data file.
    """
    try:
        validated = WorkoutIdInput(workout_id=workout_id)
    except (ValidationError, ValueError) as e:
        msg = format_validation_error(e) if isinstance(e, ValidationError) else str(e)
        return {
            "isError": True,
            "error_code": "VALIDATION_ERROR",
            "message": msg,
        }
    wid = validated.workout_id

    async with TPClient() as client:
        athlete_id = await client.ensure_athlete_id()
        if not athlete_id:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "Could not get athlete ID. Re-authenticate.",
            }

        # Ensure we have a valid token (athlete_id may have come from cache
        # without triggering token exchange)
        token_result = await client._ensure_access_token()
        if not token_result.success:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": token_result.message or "Failed to obtain access token.",
            }

        access_token = client._token_cache.access_token
        if not access_token:
            return {
                "isError": True,
                "error_code": "AUTH_INVALID",
                "message": "No access token available. Re-authenticate.",
            }

        # Analysis API is on a different domain than the main TP API,
        # so we make a direct httpx call with the Bearer token.
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json",
            "Origin": "https://app.trainingpeaks.com",
            "Referer": "https://app.trainingpeaks.com/",
        }

        base_url = f"{ANALYSIS_API_BASE}/workout-analysis/v2/analyze"
        payload = {"workoutId": wid, "viewingPersonId": athlete_id}

        try:
            async with httpx.AsyncClient(timeout=ANALYSIS_TIMEOUT) as http_client:
                summary_resp, charts_resp, laps_resp = await asyncio.gather(
                    http_client.post(f"{base_url}/summary", headers=headers, json=payload),
                    http_client.post(f"{base_url}/charts", headers=headers, json=payload),
                    http_client.post(f"{base_url}/laps", headers=headers, json=payload),
                )
        except httpx.TimeoutException:
            return {
                "isError": True,
                "error_code": "NETWORK_ERROR",
                "message": "Analysis request timed out.",
            }
        except httpx.RequestError:
            logger.exception("Network error during workout analysis")
            return {
                "isError": True,
                "error_code": "NETWORK_ERROR",
                "message": "A network error occurred.",
            }

        status_codes = [r.status_code for r in (summary_resp, charts_resp, laps_resp)]

        if any(sc == 401 for sc in status_codes):
            return {
                "isError": True,
                "error_code": "AUTH_EXPIRED",
                "message": "Session expired. Run 'tp-mcp auth' to re-authenticate.",
            }
        if all(sc in (400, 404) for sc in status_codes):
            return {
                "isError": True,
                "error_code": "NOT_FOUND",
                "message": f"Workout {workout_id} not found for analysis.",
            }
        if not any(sc == 200 for sc in status_codes):
            return {
                "isError": True,
                "error_code": "API_ERROR",
                "message": f"Analysis API error: {status_codes[0]}",
            }

        start_timestamp = None
        stop_timestamp = None
        totals_list = []
        data_elements = []
        time_series_data = []
        lap_data = []
        lap_columns = []

        if summary_resp.status_code == 200:
            try:
                s_json = summary_resp.json()
                start_timestamp = s_json.get("startTimestamp")
                stop_timestamp = s_json.get("stopTimestamp")
                s_totals = s_json.get("totals")
                s_data = s_json.get("data")
                if isinstance(s_totals, list):
                    for t in s_totals:
                        if isinstance(t, dict):
                            totals_list.append({
                                "name": t.get("name") or t.get("friendlyName") or "",
                                "value": t.get("value"),
                                "unit": t.get("unit"),
                            })
                elif isinstance(s_data, dict):
                    for k, v in s_data.items():
                        if isinstance(v, dict):
                            totals_list.append({
                                "name": v.get("friendlyName") or k,
                                "value": v.get("value"),
                                "unit": v.get("unit"),
                            })
            except Exception as e:
                logger.warning("Failed to parse analysis summary: %s", e)

        if charts_resp.status_code == 200:
            try:
                c_json = charts_resp.json()
                c_meta = c_json.get("metadata")
                c_elems = c_json.get("dataElements")
                if isinstance(c_elems, list):
                    for el in c_elems:
                        if isinstance(el, dict):
                            data_elements.append(el)
                elif isinstance(c_meta, dict):
                    for k, v in c_meta.items():
                        if isinstance(v, dict):
                            data_elements.append({
                                "identifier": k,
                                "name": v.get("friendlyName") or k,
                                "unit": v.get("unit"),
                                "min": v.get("minimum"),
                                "max": v.get("maximum"),
                                "average": v.get("average"),
                                "zones": v.get("zones"),
                            })
                time_series_data = c_json.get("data", [])
            except Exception as e:
                logger.warning("Failed to parse analysis charts: %s", e)

        if laps_resp.status_code == 200:
            try:
                l_json = laps_resp.json()
                if "lapData" in l_json:
                    lap_data = l_json.get("lapData", [])
                else:
                    lap_data = l_json.get("data", [])

                col_meta = l_json.get("lapColumns") or l_json.get("columnMetadata", {})
                if isinstance(col_meta, list):
                    lap_columns = col_meta
                elif isinstance(col_meta, dict):
                    for k, v in col_meta.items():
                        if isinstance(v, dict):
                            col_dict = {"key": k}
                            col_dict.update(v)
                            lap_columns.append(col_dict)
            except Exception as e:
                logger.warning("Failed to parse analysis laps: %s", e)

        raw_data = {
            "workoutId": wid,
            "startTimestamp": start_timestamp,
            "stopTimestamp": stop_timestamp,
            "totals": totals_list,
            "dataElements": data_elements,
            "data": time_series_data,
            "lapData": lap_data,
            "lapColumns": lap_columns,
        }

    try:
        analysis = parse_workout_analysis(raw_data)
    except Exception:
        logger.exception("Failed to parse workout analysis")
        return {
            "isError": True,
            "error_code": "API_ERROR",
            "message": "Failed to parse workout analysis.",
        }

    # Save full raw data (including time-series) to file
    data_file = _save_analysis_json(wid, raw_data)

    # Return summary inline, point to file for full data
    totals = {t.name: {"value": t.value, "unit": t.unit} for t in analysis.totals}

    channels = [
        {
            k: v
            for k, v in {
                "identifier": ch.identifier,
                "name": ch.name,
                "unit": ch.unit,
                "min": ch.min,
                "max": ch.max,
                "average": ch.average,
                "zones": ch.zones,
            }.items()
            if v is not None
        }
        for ch in analysis.data_elements
    ]

    return {
        "workoutId": analysis.workout_id,
        "startTimestamp": analysis.start_timestamp,
        "stopTimestamp": analysis.stop_timestamp,
        "totals": totals,
        "dataChannels": channels,
        "lapData": analysis.lap_data,
        "lapColumns": analysis.lap_columns,
        "time_series_points": len(analysis.data),
        "data_file": data_file,
    }
