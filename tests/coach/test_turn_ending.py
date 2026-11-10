"""End to end on ADK 2.14: tools end their own turns (UI widget + skip_summarization)."""

import asyncio

from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import app
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL

NEW_RUN = [{"date_str": "2026-11-04", "title": "Recovery Run", "distance_km": 6,
            "structure": {"steps": [{"name": "Recovery", "intensityClass": "active", "distance_m": 6000,
                                     "pace": "6:00-6:30"}]}}]


class ScriptedLlm(BaseLlm):
    """Fake Gemini: answers each call from a script of part lists, then with plain text."""

    script: list = []
    requests: list = []

    async def generate_content_async(self, llm_request, stream: bool = False):
        from google.adk.models.llm_response import LlmResponse

        self.requests.append(llm_request.model_copy(deep=True))
        i = len(self.requests) - 1
        step = self.script[i] if i < len(self.script) else [types.Part(text="Coach reply")]
        yield LlmResponse(content=types.Content(role="model", parts=step))


def _stage_call(changes) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name="stage_workout_changes", args={"changes": changes}))


def _run(monkeypatch, script: list, text: str = "Add a recovery run on Wednesday"):
    llm = ScriptedLlm(model="fake")
    llm.script, llm.requests = script, []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        return [ev async for ev in r.run_async(
            user_id="web_runner", session_id=session.id, state_delta={AUTH_EMAIL_STATE_KEY: EMAIL},
            new_message=types.Content(role="user", parts=[types.Part(text=text)]))]

    return llm, asyncio.run(scenario())


def _replies(events) -> list[str]:
    return [w.payload["data"]["text"] for e in events for w in e.actions.render_ui_widgets or []]


def test_text_with_the_staging_call_ends_the_turn_after_one_llm_call(runner, monkeypatch):
    llm, events = _run(monkeypatch, [[types.Part(text="An easy 6 km keeps your TSB above -15."), _stage_call(NEW_RUN)]])
    assert len(llm.requests) == 1 and events[-1].is_final_response()
    assert _replies(events)[-1].startswith("📋 1 change staged.")


def test_unexplained_staging_gets_one_tools_off_low_explanation_call(runner, monkeypatch):
    llm, events = _run(monkeypatch, [[_stage_call(NEW_RUN)]])
    assert len(llm.requests) == 2 and not _replies(events)
    explain = llm.requests[1].config
    assert explain.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert explain.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.NONE
    assert [p.text for p in events[-1].content.parts] == ["Coach reply"]
