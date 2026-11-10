"""Behavioural test for coaching instruction, thinking policy, and feature-turn-only routing omission."""

from datetime import datetime
from types import SimpleNamespace

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.coach.coaching.instruction import build_coach_instruction, build_profile_context
from running_coach.coach.coaching.model_callbacks import apply_thinking_policy
from running_coach.coach.coaching.quick_actions import DISPATCHED_STATE_KEY
from running_coach.tests.fakes import FakeContext, PLAN_PROFILE, SINGLE_PROFILE


STAGED = {"staged_workout_changes": {"staged_id": "s-1", "changes": [{"kind": "workout", "title": "Tempo"}]}}


def _thinking(part: types.Part, state: dict | None = None) -> types.ThinkingLevel:
    req = LlmRequest(contents=[types.Content(role="user", parts=[part])], config=types.GenerateContentConfig())
    apply_thinking_policy(FakeContext(state=state), req)
    return req.config.thinking_config.thinking_level


def _thinking_after(tool_name: str) -> types.ThinkingLevel:
    return _thinking(types.Part(function_response=types.FunctionResponse(name=tool_name, response={"result": "ok"})))


def _thinking_for(text: str, state: dict | None = None) -> types.ThinkingLevel:
    return _thinking(types.Part(text=text), state)


def test_coaching_instruction_notices_thinking_policy_and_feature_turn_routing(runner):
    # Goal-plan runner on 2026-10-27 has an unrecorded 2026-10-20 sub-goal race -> SUB-GOAL RACE DONE.
    plan_instr = build_coach_instruction(SimpleNamespace(state={"user_profile": dict(PLAN_PROFILE)}))
    plan_ctx = build_profile_context(dict(PLAN_PROFILE))
    assert "GOAL PLAN (north star with sub goals)" in plan_ctx
    # Every profile gets the GOAL REASONING frame; a plan reasons toward the sub goal AND the north star.
    assert "GOAL REASONING" in plan_ctx and "- North star: Sub-3:15 Marathon" in plan_ctx
    assert "current goal AND for the" in plan_ctx and "never alter or invent them" in plan_ctx
    # The north-star CTL range is judged with the time left, never as today's level; no double-flagging.
    assert "judge it with the time left" in plan_ctx and "never today's CTL against it" in plan_ctx
    assert "never\n      flag both sides as risks" in plan_ctx
    # The staging call carries the coaching message (reasoning and context).
    assert "in the same response as your coaching message" in plan_instr
    assert "GOAL PLAN LENS" not in plan_ctx and "long-run target the tools report" not in plan_ctx
    assert "SUB-GOAL RACE DONE: sub goal Sub-21 5K was raced on 2026-10-20" in plan_ctx
    assert "Do not offer onboarding." in plan_ctx
    # The profile lives only in the injected block, never in the instruction provider.
    assert "RUNNER PROFILE" not in plan_instr and "GOAL PLAN" not in plan_instr

    # Single-goal runner after race date -> GOAL RACE DONE; goal reasoning without a north-star clause.
    runner.now = datetime(2026, 12, 10, 9, 0, 0)
    single_ctx = build_profile_context(dict(SINGLE_PROFILE))
    assert "GOAL REASONING" in single_ctx and "- Goal: judge every assessment" in single_ctx
    assert "- North star:" not in single_ctx
    assert "GOAL RACE DONE: the runner's goal race (2026-12-06) is in the past" in single_ctx

    # No goal set -> general-development variant, no 'None' leaking into the profile.
    no_goal = {k: v for k, v in SINGLE_PROFILE.items() if k not in ("training_goal", "timeline")}
    no_goal_ctx = build_profile_context(no_goal)
    assert "- No goal is set" in no_goal_ctx and "Goal: not set" in no_goal_ctx and "None" not in no_goal_ctx

    # Thinking: MEDIUM by default; LOW for a short chat approval of staged changes (it just applies them).
    assert _thinking_for("update them", STAGED) == types.ThinkingLevel.LOW
    assert _thinking_for("Yes, but make Saturday 18 km", STAGED) == types.ThinkingLevel.LOW
    assert _thinking_for("Why move the long run?", STAGED) == types.ThinkingLevel.MEDIUM     # a question
    assert _thinking_for("update them") == types.ThinkingLevel.MEDIUM                       # nothing staged
    assert _thinking_for(" ".join(["word"] * 13), STAGED) == types.ThinkingLevel.MEDIUM     # not a short reply
    assert _thinking_for("Lets move the 5k of Nov 25th to Nov 26th") == types.ThinkingLevel.MEDIUM
    for tool in ("stage_workout_changes", "apply_staged_changes", "request_new_goal", "fetch_checkin_data"):
        assert _thinking_after(tool) == types.ThinkingLevel.MEDIUM
    # An unexplained clean staging: the next call writes the coaching message at LOW, tools off.
    explain = LlmRequest(contents=[
        types.Content(role="user", parts=[types.Part(text="Plan my week")]),
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="stage_workout_changes"))]),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="stage_workout_changes", response={"result": '{"staged": 2, "explain": true}'}))]),
    ], config=types.GenerateContentConfig())
    apply_thinking_policy(FakeContext(), explain)
    assert explain.config.thinking_config.thinking_level == types.ThinkingLevel.LOW
    assert explain.config.tool_config.function_calling_config.mode == types.FunctionCallingConfigMode.NONE
    assert "STAGED WITHOUT EXPLANATION" in str(explain.config.system_instruction)
    assert "a moved session is moved, not removed" in str(explain.config.system_instruction)
    # Rule 2: staged changes are confirmed with the button, so the coach stages its safer version.
    assert "the Update TrainingPeaks button is the\n       runner's confirmation" in plan_instr
    # Moves / renames go straight to stage_workout_changes (no load_skill round trip).
    assert "Move / swap / rename planned sessions (no new content): NO load_skill" in plan_instr
    # No "write nothing" rule: it silenced the post-staging coaching message.
    assert "write nothing" not in plan_instr.lower()

    # Typed chat always gets the routing rules; only a dispatched quick action's report call drops them.
    assert "SKILL ROUTING" in plan_instr
    # Report tools render a report: never a data lookup for a follow-up or another skill.
    assert "REPORT TOOLS (fetch_checkin_data, fetch_trend_data, fetch_schedule_audit_data)" in plan_instr
    assert "Never use one as a data lookup" in plan_instr
    report_ctx = SimpleNamespace(
        state={"user_profile": dict(PLAN_PROFILE), DISPATCHED_STATE_KEY: "inv-1"}, invocation_id="inv-1"
    )
    assert "SKILL ROUTING" not in build_coach_instruction(report_ctx)
    later_chat = SimpleNamespace(
        state={"user_profile": dict(PLAN_PROFILE), DISPATCHED_STATE_KEY: "inv-1"}, invocation_id="inv-2"
    )
    assert "SKILL ROUTING" in build_coach_instruction(later_chat)
