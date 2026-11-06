"""Behavioural test for coaching instruction, thinking policy, and table splicing."""

from datetime import datetime
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

import running_coach.agent as agent
from running_coach.callbacks import (
    TREND_PLACEHOLDER,
    TREND_TABLES_STATE_KEY,
    apply_thinking_policy,
    splice_tables,
)
from running_coach.tests.fakes import FakeContext, PLAN_PROFILE, SINGLE_PROFILE


def test_coaching_instruction_notices_thinking_policy_and_table_splicing(runner):
    # Goal-plan runner on 2026-10-27 has an unrecorded 2026-10-20 sub-goal race -> SUB-GOAL RACE DONE + GOAL PLAN LENS.
    plan_instr = agent.build_coach_instruction(SimpleNamespace(state={"user_profile": dict(PLAN_PROFILE)}))
    assert "GOAL PLAN (north star with sub goals)" in plan_instr
    assert "GOAL PLAN LENS:" in plan_instr
    assert "SUB-GOAL RACE DONE: sub goal Sub-21 5K was raced on 2026-10-20" in plan_instr
    assert "Do not offer onboarding." in plan_instr

    # Single-goal runner after race date -> GOAL RACE DONE and no GOAL PLAN LENS.
    runner.now = datetime(2026, 12, 10, 9, 0, 0)
    single_instr = agent.build_coach_instruction(SimpleNamespace(state={"user_profile": dict(SINGLE_PROFILE)}))
    assert "GOAL PLAN LENS:" not in single_instr
    assert "GOAL RACE DONE: the runner's goal race (2026-12-06) is in the past" in single_instr

    # Write-tool responses lower thinking to LOW; non-write responses keep default thinking.
    req = LlmRequest(
        contents=[types.Content(role="user", parts=[
            types.Part(function_response=types.FunctionResponse(name="create_workout", response={"result": "ok"}))
        ])],
        config=types.GenerateContentConfig(),
    )
    apply_thinking_policy(FakeContext(), req)
    assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW

    # Table splicing swaps placeholders for pre-rendered tables in state.
    ctx = FakeContext(state={TREND_TABLES_STATE_KEY: "| Marker | Latest |\n|---|---|\n| CTL | 62.5 |\n"})
    resp = LlmResponse(content=types.Content(role="model", parts=[
        types.Part(text=f"## Overview\n{TREND_PLACEHOLDER}\n## Progress")
    ]))
    spliced = splice_tables(ctx, resp).content.parts[0].text
    assert TREND_PLACEHOLDER not in spliced and "| CTL | 62.5 |" in spliced
