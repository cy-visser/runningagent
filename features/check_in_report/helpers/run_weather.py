import asyncio
from typing import Optional

from ....shared.runner_weather import fetch_weather_map


async def fetch_checkin_weather_map(
    profile: dict,
    workouts_past: list[dict],
    training_records: Optional[list[dict]],
) -> dict[str, str]:
    """Run-time weather keyed by workout start_time, grouped by recorded GPS start position."""
    pos_by_id: dict[str, dict] = {}
    for rec in training_records or []:
        if not isinstance(rec, dict):
            continue
        pos = rec.get("start_position")
        if isinstance(pos, dict) and type(pos.get("lat")) in (int, float) and type(pos.get("lon")) in (int, float):
            pos_by_id[str(rec.get("workout_id"))] = pos

    buckets: dict[Optional[tuple[float, float]], list[str]] = {}
    for w in workouts_past:
        ts = w.get("start_time")
        if not ts:
            continue
        pos = pos_by_id.get(str(w.get("id")))
        key = (round(float(pos["lat"]), 2), round(float(pos["lon"]), 2)) if pos else None
        buckets.setdefault(key, []).append(str(ts))

    if not buckets:
        return {}
    maps = await asyncio.gather(*(
        fetch_weather_map(
            profile, timestamps,
            position=({"lat": key[0], "lon": key[1]} if key else None),
        )
        for key, timestamps in buckets.items()
    ))
    merged: dict[str, str] = {}
    for m in maps:
        if isinstance(m, dict):
            merged.update(m)
    return merged
