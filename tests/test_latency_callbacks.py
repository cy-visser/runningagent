"""Tests for the latency work: thinking policy, check-in table splicing, report saving, weekly progression."""

import asyncio
from datetime import date

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

import running_coach.agent as agent
import running_coach.tools as tools
from running_coach.callbacks import (
    CHECKIN_PLACEHOLDER,
    CHECKIN_TABLES_STATE_KEY,
    LAST_CHECKIN_REPORT_STATE_KEY,
    apply_thinking_policy,
    expand_checkin_placeholder,
    splice_checkin_tables,
)
from running_coach.utils.status_summary import format_weekly_totals
from running_coach.utils.weekly import annotate_week_progression, new_week_bucket

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
    @pytest.mark.parametrize("tool", ["save_checkin_report", "create_workout", "create_note", "request_new_goal"])
    def test_minimal_after_write_tools(self, tool):
        req = _request(_tool_response(tool))
        assert apply_thinking_policy(FakeContext(), req) is None
        assert req.config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL

    @pytest.mark.parametrize("tool", [
        "fetch_checkin_data", "analyze_workout", "fetch_schedule_audit_data",
        "fetch_nutrition_context", "get_weather", "load_skill", "some_new_tool",
    ])
    def test_default_reasoning_after_data_and_unknown_tools(self, tool):
        req = _request(_tool_response(tool))
        apply_thinking_policy(FakeContext(), req)
        assert req.config.thinking_config is None

    def test_mixed_parallel_batch_keeps_default(self):
        req = _request(_tool_response("load_skill", "fetch_checkin_data"))
        apply_thinking_policy(FakeContext(), req)
        assert req.config.thinking_config is None

    def test_runner_message_and_empty_request_keep_default(self):
        msg = _request(types.Content(role="user", parts=[types.Part(text="Checking in")]))
        apply_thinking_policy(FakeContext(), msg)
        assert msg.config.thinking_config is None
        empty = _request()
        apply_thinking_policy(FakeContext(), empty)
        assert empty.config.thinking_config is None

    def test_creates_config_when_missing(self):
        req = LlmRequest(contents=[_tool_response("create_note")])
        req.config = None
        apply_thinking_policy(FakeContext(), req)
        assert req.config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL

    def test_coaching_agent_wires_the_callbacks(self):
        assert agent.coaching_agent.before_model_callback is apply_thinking_policy
        assert agent.coaching_agent.after_model_callback is splice_checkin_tables


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

    def test_no_placeholder_is_a_noop(self):
        ctx = FakeContext({CHECKIN_TABLES_STATE_KEY: TABLES})
        assert splice_checkin_tables(ctx, _text_response("A normal coaching answer.")) is None
        assert LAST_CHECKIN_REPORT_STATE_KEY not in ctx.state

    def test_placeholder_without_tables_is_left_alone(self):
        ctx = FakeContext()
        resp = _text_response(f"x {CHECKIN_PLACEHOLDER} y")
        assert splice_checkin_tables(ctx, resp) is None
        assert CHECKIN_PLACEHOLDER in resp.content.parts[0].text

    def test_thought_parts_are_not_spliced(self):
        ctx = FakeContext({CHECKIN_TABLES_STATE_KEY: TABLES})
        resp = _text_response(f"thinking about {CHECKIN_PLACEHOLDER}", thought=True)
        assert splice_checkin_tables(ctx, resp) is None
        assert CHECKIN_PLACEHOLDER in resp.content.parts[0].text

    def test_function_call_responses_are_ignored(self):
        ctx = FakeContext({CHECKIN_TABLES_STATE_KEY: TABLES})
        resp = LlmResponse(content=types.Content(role="model", parts=[
            types.Part(function_call=types.FunctionCall(name="fetch_checkin_data", args={}))
        ]))
        assert splice_checkin_tables(ctx, resp) is None

    def test_expand_helper(self):
        assert expand_checkin_placeholder(f"a\n{CHECKIN_PLACEHOLDER}\nb", TABLES) == f"a\n{TABLES.strip()}\nb"
        assert expand_checkin_placeholder("plain", TABLES) == "plain"
        assert expand_checkin_placeholder(CHECKIN_PLACEHOLDER, None) == CHECKIN_PLACEHOLDER


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

    def test_explicit_content_wins_and_placeholder_is_expanded(self, saved):
        ctx = FakeContext({"user_profile": self.PROFILE, CHECKIN_TABLES_STATE_KEY: TABLES,
                           LAST_CHECKIN_REPORT_STATE_KEY: "old"})
        asyncio.run(tools.save_checkin_report(ctx, f"edited\n{CHECKIN_PLACEHOLDER}"))
        assert saved[0]["report_markdown"] == f"edited\n{TABLES.strip()}"

    def test_errors_when_nothing_to_save(self, saved):
        ctx = FakeContext({"user_profile": self.PROFILE})
        assert asyncio.run(tools.save_checkin_report(ctx)).startswith("Error")
        assert saved == []


# ---------------------------------------------------------------- weekly progression
def _week(monday: date, km: float, easy: int = 3, quality: int = 1) -> dict:
    w = new_week_bucket(monday)
    w.update(total_distance_km=km, easy_count=easy, quality_count=quality)
    return w


class TestWeekProgression:
    def test_growth_only_between_complete_weeks(self):
        weeks = [_week(date(2026, 9, 21), 40), _week(date(2026, 9, 28), 50), _week(date(2026, 10, 5), 45),
                 _week(date(2026, 10, 12), 8)]
        annotate_week_progression(weeks, date(2026, 9, 24), date(2026, 10, 12))
        assert [w["partial"] for w in weeks] == [True, False, False, True]
        assert weeks[1]["growth_pct"] is None  # prior week partial
        assert weeks[2]["growth_pct"] == pytest.approx(-10.0)
        assert weeks[3]["growth_pct"] is None  # current week in progress

    def test_zero_km_prior_week_has_no_growth(self):
        weeks = [_week(date(2026, 9, 28), 0), _week(date(2026, 10, 5), 30)]
        annotate_week_progression(weeks, date(2026, 9, 28), date(2026, 10, 11))
        assert weeks[1]["growth_pct"] is None

    def test_rendering_flags_growth_over_ten_percent_and_split(self):
        weeks = [_week(date(2026, 9, 28), 40), _week(date(2026, 10, 5), 46, easy=4, quality=1)]
        annotate_week_progression(weeks, date(2026, 9, 28), date(2026, 10, 11))
        out = format_weekly_totals(weeks).splitlines()
        assert "Split: 75% easy / 25% quality (by runs)" in out[0]
        assert "Volume vs prior week" not in out[0]
        assert "Split: 80% easy / 20% quality" in out[1]
        assert "Volume vs prior week: +15.0% ⚠️ > 10%" in out[1]

    def test_rendering_marks_partial_weeks(self):
        weeks = [_week(date(2026, 10, 12), 8)]
        annotate_week_progression(weeks, date(2026, 9, 28), date(2026, 10, 12))
        assert "Partial week" in format_weekly_totals(weeks)

    def test_unannotated_weeks_render_as_before(self):
        out = format_weekly_totals([_week(date(2026, 10, 5), 40.0)])
        assert "40.0 km (4 runs: 3 easy, 1 quality)" in out
        assert "Volume vs prior week" not in out and "Partial week" not in out
