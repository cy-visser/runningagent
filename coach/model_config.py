import os

from google.adk.models.google_llm import Gemini
from google.genai import types

COACH_MODEL = os.getenv("COACH_MODEL", "gemini-3.6-flash")
ONBOARDING_MODEL = os.getenv("ONBOARDING_MODEL", "gemini-3.1-flash-lite")

# Retry 429s at the model call so tool side effects are never replayed.
MODEL_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=3, initial_delay=2, exp_base=4, http_status_codes=[429]
)


def build_model(name: str) -> Gemini:
    return Gemini(model=name, retry_options=MODEL_RETRY_OPTIONS)
