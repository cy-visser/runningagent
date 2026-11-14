"""Pytest configuration and shared `runner` fixture for the running_coach agent tests."""

import json
import os
import sys
from typing import Any

import pytest

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_PARENT = os.path.dirname(PACKAGE_ROOT)

if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)

from running_coach.integrations import firestore, open_meteo
from running_coach.integrations.trainingpeaks import credentials, tp_calls
from running_coach.shared import dates
from running_coach.tests.fakes import CANOVA, FakeRunnerEnv


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> FakeRunnerEnv:
    monkeypatch.delenv("DEV_RUNNER_EMAIL", raising=False)

    points = []
    for idx, pt in enumerate(CANOVA["series"]):
        item = dict(pt)
        if idx == 5:
            item["PositionLat"] = 52.37022
            item["PositionLong"] = 4.89517
        points.append(item)
    data_file = tmp_path / "telemetry.json"
    data_file.write_text(json.dumps({"data": points}), encoding="utf-8")

    env = FakeRunnerEnv(data_file_path=str(data_file))

    async def fake_get_cached_analysis(user_id: str, workout_id: str) -> Any:
        return env.analysis_cache.get((user_id, str(workout_id)))

    async def fake_save_cached_analysis(user_id: str, workout_id: str, summary: dict) -> None:
        env.analysis_cache[(user_id, str(workout_id))] = summary

    async def fake_list_records(user_id: str, start: str, end: str) -> list[dict]:
        return [
            r for r in env.training_records.values()
            if start <= str(r.get("date") or "") <= end
        ]

    async def fake_save_record(user_id: str, workout_id: str, record: dict) -> None:
        env.training_records[str(workout_id)] = dict(record)

    async def fake_get_profile(user_id: str) -> dict | None:
        doc = env.profiles.get(user_id)
        return dict(doc) if doc else None

    async def fake_save_profile(user_id: str, profile: dict) -> None:
        env.profiles[user_id] = dict(profile)

    async def fake_update_profile(user_id: str, updates: dict) -> None:
        env.profile_updates.append((user_id, updates))
        if user_id in env.profiles:
            env.profiles[user_id].update(updates)

    async def fake_find_by_email(email: str) -> tuple[str, dict] | None:
        for rid, doc in env.profiles.items():
            if (doc.get("email") or "").lower() == email.lower():
                return rid, dict(doc)
        return None

    async def fake_has_credential(runner_id: str) -> bool:
        return runner_id in env.connected_runners

    def fake_weather_conditions(
        location: str = "",
        dates: list[str] | None = None,
        lat: Any = None,
        lon: Any = None,
        utc: bool = False,
    ) -> dict[str, str]:
        return {str(d): "12°C (feels 11°C), 70% RH, wind 11 km/h, 0.0 mm" for d in (dates or [])}

    def fake_weather_for_dates(
        location: str = "",
        dates: list[str] | None = None,
        lat: Any = None,
        lon: Any = None,
    ) -> str:
        label = location or f"{lat}, {lon}"
        lines = [f"- {d}: 12°C (feels 11°C), clear" for d in (dates or [])]
        return f"Weather for {label}:\n" + "\n".join(lines)

    def fake_conditions_at(lat: Any, lon: Any, ts: str, utc: bool = False) -> dict:
        return {"temp_c": 12.0, "feels_like_c": 11.0, "humidity_pct": 70, "wind_kph": 11.0, "precip_mm": 0.0}

    def fake_geocode(location: str) -> tuple[float, float]:
        return (52.37, 4.89)

    async def fake_get_volume_history(user_id: str) -> dict | None:
        doc = env.volume_history_cache.get(user_id)
        return json.loads(json.dumps(doc)) if doc else None

    async def fake_save_volume_history(user_id: str, payload: dict) -> None:
        env.volume_history_cache[user_id] = json.loads(json.dumps(payload))

    monkeypatch.setattr(dates, "_now", lambda: env.now)

    monkeypatch.setattr(firestore, "get_cached_workout_analysis", fake_get_cached_analysis)
    monkeypatch.setattr(firestore, "save_workout_analysis", fake_save_cached_analysis)
    monkeypatch.setattr(firestore, "get_cached_volume_history", fake_get_volume_history)
    monkeypatch.setattr(firestore, "save_volume_history", fake_save_volume_history)
    monkeypatch.setattr(firestore, "list_training_records", fake_list_records)
    monkeypatch.setattr(firestore, "save_training_record", fake_save_record)
    monkeypatch.setattr(firestore, "get_user_profile", fake_get_profile)
    monkeypatch.setattr(firestore, "save_user_profile", fake_save_profile)
    monkeypatch.setattr(firestore, "update_user_profile", fake_update_profile)
    monkeypatch.setattr(firestore, "find_user_profile_by_email", fake_find_by_email)

    monkeypatch.setattr(open_meteo, "get_weather_conditions", fake_weather_conditions)
    monkeypatch.setattr(open_meteo, "get_weather_for_dates", fake_weather_for_dates)
    monkeypatch.setattr(open_meteo, "get_conditions_at", fake_conditions_at)
    monkeypatch.setattr(open_meteo, "geocode_location", fake_geocode)

    async def fake_warm_tp(runner_id: str | None) -> None:
        return None

    monkeypatch.setattr(credentials, "has_tp_credential", fake_has_credential)
    monkeypatch.setattr(tp_calls, "run_tp_tool", env.run_tp_tool)
    monkeypatch.setattr(tp_calls, "warm_runner_tp", fake_warm_tp)

    return env
