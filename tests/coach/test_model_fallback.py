"""Coach model: a still-throttled (429) call is answered by the fallback model at MEDIUM thinking."""

import asyncio

import pytest
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError

from running_coach.coach.model_config import SKIP_SIGNATURE, FallbackGemini


def _request() -> LlmRequest:
    return LlmRequest(model="gemini-4-argon", config=types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM)), contents=[
        types.Content(role="user", parts=[types.Part(text="Plan my week")]),
        types.Content(role="model", parts=[
            types.Part(text="Staging", thought_signature=b"argon-sig"),
            types.Part(function_call=types.FunctionCall(name="stage_workout_changes", args={}), thought_signature=b"argon-sig")]),
    ])


def _run(monkeypatch, primary_error: int | None) -> list[LlmRequest]:
    seen: list[LlmRequest] = []

    async def fake(self, llm_request, stream=False):
        seen.append(llm_request)
        if llm_request.model == "gemini-4-argon" and primary_error:
            raise ClientError(primary_error, {"error": {"code": primary_error, "message": "x", "status": "X"}})
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=llm_request.model)]))

    monkeypatch.setattr(Gemini, "generate_content_async", fake)
    model = FallbackGemini(model="gemini-4-argon", fallback_model="gemini-3.8-flash")

    async def collect():
        return [r async for r in model.generate_content_async(_request())]

    responses = asyncio.run(collect())
    assert responses[-1].content.parts[0].text == seen[-1].model
    return seen


def test_a_throttled_call_falls_back_to_flash_at_medium_without_argon_signatures(monkeypatch):
    primary, fallback = _run(monkeypatch, 429)
    assert (primary.model, fallback.model) == ("gemini-4-argon", "gemini-3.8-flash")
    assert fallback.config.thinking_config.thinking_level == types.ThinkingLevel.MEDIUM
    text_part, call_part = fallback.contents[1].parts
    assert text_part.thought_signature is None and call_part.thought_signature == SKIP_SIGNATURE
    assert primary.contents[1].parts[1].thought_signature == b"argon-sig"  # the original request is untouched


def test_no_fallback_without_throttling_and_other_errors_surface(monkeypatch):
    assert [r.model for r in _run(monkeypatch, None)] == ["gemini-4-argon"]
    with pytest.raises(ClientError):
        _run(monkeypatch, 400)
