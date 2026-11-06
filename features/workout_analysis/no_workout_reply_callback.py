from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from .helpers.session_selection import NO_WORKOUT_PREFIX


def no_workout_reply(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> Optional[LlmResponse]:
    """before_model_callback: returns analyze_workout's 'no workout' reply directly so the LLM cannot retry."""
    if not llm_request.contents:
        return None
    for part in llm_request.contents[-1].parts or []:
        fr = part.function_response
        if fr and fr.name == "analyze_workout":
            result = (fr.response or {}).get("result")
            if isinstance(result, str) and result.startswith(NO_WORKOUT_PREFIX):
                return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=result)]))
    return None
