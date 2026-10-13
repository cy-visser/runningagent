"""Tests for the latency work: thinking policy, check-in table splicing, report saving, weekly progression."""

import asyncio

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

import running_coach.tools as tools
from running_coach.callbacks import (
    CHECKIN_PLACEHOLDER,
    CHECKIN_TABLES_STATE_KEY,
    LAST_CHECKIN_REPORT_STATE_KEY,
    apply_thinking_policy,
    splice_checkin_tables,
)

TABLES = "| Metric | Current Value |\n|---|---|\n| **CTL (Fitness)** | `66.6` |\n"


class FakeContext:
    def __init__(self, state=None):
        self.state: dict = dict(state or {})


def _tool_response(*names: str) -> types.Content:
    return types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name=n, response={"result": "ok"})) for n in names
    ])


def _request(*contents: types.Content) -> LlmRequest:
    return LlmRequest(contents=list(contents), config=types.GenerateContentConfig())


def _text_response(*texts: str, thought: bool = False) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t, thought=thought) for t in texts]))


# ---------------------------------------------------------------- thinking policy
class TestThinkingPolicy:
    def test_low_after_write_tools(self):
        for tool in ("save_checkin_report", "create_workout", "create_note", "request_new_goal"):
            req = _request(_tool_response(tool))
            assert apply_thinking_policy(FakeContext(), req) is None
            assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW, tool
        # A request without a config gets one.
        req = LlmRequest(contents=[_tool_response("create_note")])
        req.config = None
        apply_thinking_policy(FakeContext(), req)
        assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW


# ---------------------------------------------------------------- table splicing
class TestSpliceCheckinTables:
    def test_replaces_placeholder_and_stores_report(self):
        ctx = FakeContext({CHECKIN_TABLES_STATE_KEY: TABLES})
        resp = _text_response(f"## Overview\n\n### 📊 Metrics Progress\n{CHECKIN_PLACEHOLDER}\n\n### 🎯 Status")
        out = splice_checkin_tables(ctx, resp)
        text = out.content.parts[0].text
        assert CHECKIN_PLACEHOLDER not in text
        assert "| **CTL (Fitness)** | `66.6` |" in text
        assert text.index("Metrics Progress") < text.index("CTL (Fitness)") < text.index("🎯 Status")
        assert ctx.state[LAST_CHECKIN_REPORT_STATE_KEY] == text


# ---------------------------------------------------------------- save_checkin_report
class TestSaveCheckinReport:
    PROFILE = {"firstname": "Cyrille", "lastname": "Visser"}

    @pytest.fixture
    def saved(self, monkeypatch):
        calls = []

        async def fake_save(user_id, doc_id, data):
            calls.append(data)

        monkeypatch.setattr(tools, "save_checkin_report_data", fake_save)
        return calls

    def test_saves_delivered_report_without_arguments(self, saved):
        ctx = FakeContext({"user_profile": self.PROFILE, LAST_CHECKIN_REPORT_STATE_KEY: "full report"})
        out = asyncio.run(tools.save_checkin_report(ctx))
        assert out.startswith("Success")
        assert saved[0]["report_markdown"] == "full report"
