import os
from typing import AsyncGenerator

from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.genai.errors import ClientError
from opentelemetry import trace

# Set in .env (agents-cli passes it to the Agent Runtime); the defaults only serve tests and local runs.
COACH_MODEL = os.getenv("COACH_MODEL", "gemini-4-argon")
COACH_THINKING_LEVEL = os.getenv("COACH_THINKING_LEVEL", "MEDIUM").upper()
COACH_FALLBACK_MODEL = os.getenv("COACH_FALLBACK_MODEL", "gemini-3.8-flash")
ONBOARDING_MODEL = os.getenv("ONBOARDING_MODEL", "gemini-3.1-flash-lite")

# Retry 429s at the model call so tool side effects are never replayed (3 attempts = 2 retries).
MODEL_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=3, initial_delay=2, exp_base=4, http_status_codes=[429]
)
# Documented Gemini 3 escape hatch: the fallback model cannot validate the primary model's signatures.
SKIP_SIGNATURE = b"skip_thought_signature_validator"


class FallbackGemini(Gemini):
    """Gemini that answers with `fallback_model` (MEDIUM thinking) when the primary is still throttled (429)."""

    fallback_model: str

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        try:
            async for response in super().generate_content_async(llm_request, stream):
                yield response
            return
        except ClientError as e:
            if e.code != 429:
                raise
        trace.get_current_span().set_attribute("coach.fallback", self.fallback_model)
        async for response in super().generate_content_async(fallback_request(llm_request, self.fallback_model), stream):
            yield response


def fallback_request(llm_request: LlmRequest, model: str) -> LlmRequest:
    request = llm_request.model_copy(deep=True)
    request.model = model
    request.config = request.config or types.GenerateContentConfig()
    request.config.thinking_config = types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM)
    for content in request.contents or []:
        for part in content.parts or []:
            part.thought_signature = SKIP_SIGNATURE if part.function_call else None
    return request


def build_model(name: str) -> Gemini:
    return Gemini(model=name, retry_options=MODEL_RETRY_OPTIONS)


def build_coach_model() -> Gemini:
    return FallbackGemini(model=COACH_MODEL, fallback_model=COACH_FALLBACK_MODEL, retry_options=MODEL_RETRY_OPTIONS)
