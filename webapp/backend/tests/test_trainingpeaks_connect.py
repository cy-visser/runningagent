"""Behavioural test for TrainingPeaks cookie sanitization, token exchange, and 409 conflict guard."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from app.trainingpeaks import (
    TrainingPeaksValidationError,
    clean_tp_cookie_input,
    validate_tp_cookie,
)
from conftest import build_test_app


def test_trainingpeaks_cookie_cleaning_token_exchange_and_409_conflict():
    # Cookie cleaning & validation
    assert clean_tp_cookie_input("  abc123token ") == "abc123token"
    assert clean_tp_cookie_input("foo=1; Production_tpAuth=xyz_987; Path=/") == "xyz_987"
    with pytest.raises(TrainingPeaksValidationError):
        clean_tp_cookie_input("bad value with spaces")

    # Token exchange + runner_id derivation
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/v3/token":
            assert request.headers.get("Cookie") == "Production_tpAuth=validcookie"
            return httpx.Response(200, content=json.dumps({"success": True, "token": {"access_token": "tok-1"}}))
        if request.url.path == "/users/v3/user":
            assert request.headers.get("Authorization") == "Bearer tok-1"
            return httpx.Response(
                200,
                content=json.dumps(
                    {"user": {"firstName": "Cyrille", "lastName": "Visser", "userId": 101, "personId": 202}}
                ),
            )
        return httpx.Response(404)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await validate_tp_cookie("validcookie", http_client=client)

    acc = asyncio.run(run())
    assert acc.runner_id == "cyrille_visser"
    assert acc.tp_name == "Cyrille Visser"
    assert acc.tp_athlete_id == 202

    # 409 conflict when existing profile belongs to another account
    app, store, _ = build_test_app()
    store.users["cyrille_visser"] = {"firstname": "Cyrille", "lastname": "Visser"}
    headers = {"X-Goog-IAP-JWT-Assertion": "valid-jwt"}
    with TestClient(app) as client:
        resp = client.post("/api/trainingpeaks/connect", json={"cookie": "validcookie123"}, headers=headers)
        assert resp.status_code == 409
