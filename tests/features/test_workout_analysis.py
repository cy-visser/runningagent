"""Behavioural test for workout analysis (`analyze_workout` + `no_workout_reply`)."""

import asyncio

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data
from running_coach.features.workout_analysis.analyze_workout_tool import analyze_workout
from running_coach.features.workout_analysis.no_workout_reply_callback import no_workout_reply


def test_workout_analysis_saves_sub_goal_result_matches_gap_fill_and_short_circuits_no_workout(runner):
    ctx = runner.ctx()
    out = asyncio.run(analyze_workout(ctx, workout_id="w_race_5k"))

    assert "### Workout Analysis" in out
    assert "### Planned structure & execution" in out
    assert "**Planned session notes:**" in out
    assert "**Athlete feedback:** RPE 6/10" in out
    assert "**Environmental & Weather Context:**" in out
    assert "Result saved" in out
    assert len(runner.profile_updates) == 1
    saved_sub = ctx.state["user_profile"]["sub_goals"][0]["result"]
    assert saved_sub and saved_sub["workout_id"] == "w_race_5k"

    via_analysis = {k: v for k, v in runner.training_records["w_race_5k"].items() if k != "recorded_at"}
    runner.training_records.clear()
    asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))
    via_gap_fill = {k: v for k, v in runner.training_records["w_race_5k"].items() if k != "recorded_at"}
    assert via_analysis == via_gap_fill

    # Date with no workout returns deterministic text that no_workout_reply short-circuits.
    no_w_msg = asyncio.run(analyze_workout(runner.ctx(), date_str="2026-10-28"))
    assert "No completed workout on 2026-10-28" in no_w_msg
    req = LlmRequest(contents=[types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name="analyze_workout", response={"result": no_w_msg}))
    ])])
    res = no_workout_reply(runner.ctx(), req)
    assert res is not None and res.content.parts[0].text == no_w_msg
