"""Behavioural test for coaching instruction, thinking policy, and feature-turn-only routing omission."""

from datetime import datetime
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.coach.coaching.instruction import build_coach_instruction, build_profile_context
from running_coach.coach.coaching.model_callbacks import apply_thinking_policy
from running_coach.coach.coaching.quick_actions import DISPATCHED_STATE_KEY
from running_coach.tests.fakes import FakeContext, PLAN_PROFILE, SINGLE_PROFILE


def test_coaching_instruction_notices_thinking_policy_and_feature_turn_routing(runner):
    # Goal-plan runner on 2026-10-27 has an unrecorded 2026-10-20 sub-goal race -> SUB-GOAL RACE DONE + GOAL PLAN LENS.
    plan_instr = build_coach_instruction(SimpleNamespace(state={"user_profile": dict(PLAN_PROFILE)}))
    plan_ctx = build_profile_context(dict(PLAN_PROFILE))
    assert "GOAL PLAN (north star with sub goals)" in plan_ctx
    assert "GOAL PLAN LENS:" in plan_ctx
    assert "SUB-GOAL RACE DONE: sub goal Sub-21 5K was raced on 2026-10-20" in plan_ctx
    assert "Do not offer onboarding." in plan_ctx
    # The profile lives only in the injected block, never in the instruction provider.
    assert "RUNNER PROFILE" not in plan_instr and "GOAL PLAN" not in plan_instr

    # Single-goal runner after race date -> GOAL RACE DONE and no GOAL PLAN LENS.
    runner.now = datetime(2026, 12, 10, 9, 0, 0)
    single_ctx = build_profile_context(dict(SINGLE_PROFILE))
    assert "GOAL PLAN LENS:" not in single_ctx
    assert "GOAL RACE DONE: the runner's goal race (2026-12-06) is in the past" in single_ctx

    # Write-tool responses lower thinking to LOW; non-write responses keep default thinking.
    req = LlmRequest(
        contents=[types.Content(role="user", parts=[
            types.Part(function_response=types.FunctionResponse(name="create_workout", response={"result": "ok"}))
        ])],
        config=types.GenerateContentConfig(),
    )
    apply_thinking_policy(FakeContext(), req)
    assert req.config.thinking_config.thinking_level == types.ThinkingLevel.LOW

    # Typed chat always gets the routing rules; only a dispatched quick action's report call drops them.
    assert "SKILL ROUTING" in plan_instr
    report_ctx = SimpleNamespace(
        state={"user_profile": dict(PLAN_PROFILE), DISPATCHED_STATE_KEY: "inv-1"}, invocation_id="inv-1"
    )
    assert "SKILL ROUTING" not in build_coach_instruction(report_ctx)
    later_chat = SimpleNamespace(
        state={"user_profile": dict(PLAN_PROFILE), DISPATCHED_STATE_KEY: "inv-1"}, invocation_id="inv-2"
    )
    assert "SKILL ROUTING" in build_coach_instruction(later_chat)
