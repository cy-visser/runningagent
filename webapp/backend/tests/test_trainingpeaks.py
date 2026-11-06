"""Tests for TrainingPeaks Production_tpAuth validation and cookie sanitization."""

import asyncio
import json

import httpx
import pytest

from app.trainingpeaks import (
    TrainingPeaksValidationError,
    clean_tp_cookie_input,
    validate_tp_cookie,
)


def test_clean_tp_cookie_input():
    assert clean_tp_cookie_input("  abc123token ") == "abc123token"
    assert clean_tp_cookie_input("foo=1; Production_tpAuth=xyz_987; Path=/") == "xyz_987"
    with pytest.raises(TrainingPeaksValidationError):
        clean_tp_cookie_input("bad value with spaces")


def test_validate_tp_cookie_exchanges_token_and_derives_runner_id():
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
