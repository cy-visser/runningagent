"""strip_stale_thoughts: completed turns lose thoughts/signatures; the current turn keeps them."""

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.coach.coaching.model_callbacks import strip_stale_thoughts

SIG = b"sig"


def _user(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text)])


def _model(*parts: types.Part) -> types.Content:
    return types.Content(role="model", parts=list(parts))


def _call(name: str, sig: bytes = SIG) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=name, args={}), thought_signature=sig)


def _resp(name: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(name=name, response={"result": "ok"}))],
    )


def _run(contents: list[types.Content]) -> list[types.Content]:
    req = LlmRequest(contents=contents)
    assert strip_stale_thoughts(None, req) is None
    return req.contents


def test_completed_turns_lose_thoughts_and_signatures():
    out = _run([
        _user("audit my plan"),
        _model(types.Part(text="thinking...", thought=True), _call("fetch_schedule_audit_data")),
        _resp("fetch_schedule_audit_data"),
        _model(types.Part(text="### Assessment", thought_signature=SIG), types.Part(text="", thought_signature=SIG)),
        _user("yes update it"),
    ])
    assert len(out) == 5
    first_model, second_model = out[1], out[3]
    assert [p.function_call.name for p in first_model.parts] == ["fetch_schedule_audit_data"]
    assert all(p.thought_signature is None and not p.thought for p in first_model.parts + second_model.parts)
    assert [p.text for p in second_model.parts] == ["### Assessment"]  # empty signed part dropped
