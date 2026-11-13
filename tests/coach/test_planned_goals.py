"""Behavioural test for planned / unplanned goals: which goal Build Plan targets, the coach's profile block,
automatic marking when a plan is fully applied, and re-onboarding."""

import asyncio
import copy
from datetime import date

from google.genai import types

from running_coach.coach.coaching.goal_plan_summary import format_goal_plan
from running_coach.coach.coaching.instruction import build_profile_context
from running_coach.coach.coaching.model_callbacks import thinking_for
from running_coach.coach.coaching.quick_actions import DISPATCHED_SKILL_STATE_KEY, DISPATCHED_STATE_KEY
from running_coach.coach.onboarding import profile_creation
from running_coach.features.plan_builder.apply_training_plan_tool import apply_training_plan
from running_coach.features.plan_builder.stage_training_plan_tool import stage_training_plan
from running_coach.shared.goal_plan import all_future_goals_planned, next_unplanned_goal, planned_update
from running_coach.tests.fakes import PLAN_PROFILE, SINGLE_PROFILE

TODAY = date(2026, 10, 27)  # a Tuesday; the 5K sub goal (2026-10-20) is past


def _plan(**planned) -> dict:
    """PLAN_PROFILE with planned flags: sub0 / sub1 / ns."""
    p = copy.deepcopy(PLAN_PROFILE)
    for i in (0, 1):
        p["sub_goals"][i]["planned"] = planned.get(f"sub{i}", False)
    p["north_star"]["planned"] = planned.get("ns", False)
    return p


def test_next_unplanned_goal_skips_past_and_planned_goals_with_its_block_window():
    nxt = next_unplanned_goal(_plan(), TODAY)                       # 5K is past -> the 10K, own start ahead
    assert (nxt["training_goal"], nxt["window_start"], nxt["window_end"]) == (
        "Sub-43 10K", date(2026, 11, 16), date(2027, 2, 14))
    nxt = next_unplanned_goal(_plan(sub1=True), TODAY)              # 10K planned -> north star after the 10K race
    assert (nxt["training_goal"], nxt["window_start"], nxt["window_end"]) == (
        "Sub-3:15 Marathon", date(2027, 2, 15), date(2028, 4, 23))
    assert next_unplanned_goal(_plan(sub1=True, ns=True), TODAY) is None

    # The block already started (own start in the past): next Monday.
    late = next_unplanned_goal(_plan(), date(2026, 12, 2))
    assert late["window_start"] == date(2026, 12, 7)

    single = next_unplanned_goal(SINGLE_PROFILE, TODAY)             # goal_set_date is past -> next Monday
    assert (single["window_start"], single["window_end"]) == (date(2026, 11, 2), date(2026, 12, 6))
    assert next_unplanned_goal({**SINGLE_PROFILE, "planned": True}, TODAY) is None

    # A future block configured with a Sunday 1st-of-the-month start (2027-08-01) snaps to Monday 2027-08-02.
    aug_sun = {**SINGLE_PROFILE, "goal_set_date": "2027-08-01", "timeline": "2027-10-31"}
    assert (next_unplanned_goal(aug_sun, TODAY)["window_start"], next_unplanned_goal(aug_sun, TODAY)["window_end"]) == (
        date(2027, 8, 2), date(2027, 10, 31)
    )


def test_all_future_goals_planned_needs_at_least_one_future_goal():
    assert not all_future_goals_planned(_plan(sub1=True), TODAY)
    assert all_future_goals_planned(_plan(sub1=True, ns=True), TODAY)   # the past 5K does not count
    assert all_future_goals_planned({**SINGLE_PROFILE, "planned": True}, TODAY)
    assert not all_future_goals_planned({**SINGLE_PROFILE, "planned": True}, date(2027, 1, 1))  # race passed
    assert not all_future_goals_planned({}, TODAY)


def test_planned_update_marks_goals_racing_inside_the_window():
    update = planned_update(_plan(), date(2026, 11, 16), date(2027, 2, 14))
    assert [s.get("planned") for s in update["sub_goals"]] == [False, True] and "north_star" not in update
    both = planned_update(_plan(), date(2026, 11, 16), date(2028, 4, 30))
    assert both["sub_goals"][1]["planned"] and both["north_star"]["planned"]
    assert planned_update(_plan(sub1=True), date(2026, 11, 16), date(2027, 2, 14)) is None  # nothing changes
    assert planned_update(SINGLE_PROFILE, date(2026, 11, 2), date(2026, 12, 6)) == {"planned": True}
    assert planned_update(SINGLE_PROFILE, date(2026, 11, 2), date(2026, 11, 30)) is None


def test_profile_block_and_goal_plan_table_show_the_planning_status():
    block = build_profile_context(_plan(), TODAY)
    assert ("NEXT UNPLANNED GOAL: Sub-43 10K (Schoorl 10K), race 2027-02-14; block window 2026-11-16 -> 2027-02-14"
            in block)
    assert "| Planned |" in format_goal_plan(_plan(sub1=True), TODAY)
    assert "| Sub-43 10K | 2026-11-16 -> 2027-02-14 | upcoming (next block) | yes |" in format_goal_plan(
        _plan(sub1=True), TODAY)
    done = build_profile_context(_plan(sub1=True, ns=True), TODAY)
    assert "ALL GOALS ARE PLANNED" in done and "NEXT UNPLANNED GOAL" not in done
    assert "(Timeline: 2026-12-06; planned)" in build_profile_context({**SINGLE_PROFILE, "planned": True}, TODAY)


def test_plan_intake_opener_uses_low_thinking_only_on_its_own_report_call():
    intake = {DISPATCHED_STATE_KEY: "inv-1", DISPATCHED_SKILL_STATE_KEY: "plan-builder:intake"}
    from google.adk.models.llm_request import LlmRequest

    req = LlmRequest(contents=[types.Content(role="user", parts=[types.Part(text="I'd like to build a new training plan")])])
    assert thinking_for(intake, req, "inv-1") == (thinking_for(intake, req, "inv-1")[0], "intake")
    assert thinking_for(intake, req, "inv-1")[0].thinking_level == types.ThinkingLevel.LOW
    assert thinking_for(intake, req, "inv-2")[1] == "default"                      # a later typed turn
    assert thinking_for({**intake, DISPATCHED_SKILL_STATE_KEY: "trend-analysis"}, req, "inv-1")[1] == "default"


def test_fully_applying_a_plan_marks_the_goals_it_covers_as_planned(runner):
    ctx = runner.ctx()
    plan = {"start_date": "2027-01-25", "weeks": [
        {"week": n, "phase": "taper", "days": {"Tue": "E 8", "Sun": "L 14"}} for n in (1, 2, 3)]}
    staged_id = __import__("json").loads(asyncio.run(stage_training_plan(ctx, plan)))["staged_id"]
    for week in (1, 2):
        asyncio.run(apply_training_plan(ctx, staged_id, week))
    assert not runner.profiles["cyrille_visser"]["sub_goals"][1].get("planned")   # not done yet
    asyncio.run(apply_training_plan(ctx, staged_id, 3))                           # last week: 25 Jan -> 14 Feb
    assert ctx.state["applied_training_plan"]["done"]
    assert runner.profiles["cyrille_visser"]["sub_goals"][1]["planned"] is True   # the 10K races on 14 Feb
    assert not runner.profiles["cyrille_visser"]["north_star"].get("planned")
    assert ctx.state["user_profile"]["sub_goals"][1]["planned"] is True


def test_re_onboarding_keeps_planned_flags_of_unchanged_goals():
    merged = profile_creation.merge_profile_data(
        answers={
            "goal_type": "plan",
            "north_star_goal": "Sub-3:15 Marathon",
            "north_star_race_date": "2028-04-23",
            "sub_goals": [
                {"goal": "Sub-43 10K", "start_date": "2026-11-16", "race_date": "2027-02-14"},
                {"goal": "Sub-1:30 HM", "start_date": "2027-03-01", "race_date": "2027-05-02"},
            ],
        },
        temp_data={
            "firstname": "Cyrille", "lastname": "Visser",
            "sub_goals": [{"goal": "Sub-43 10K", "race_date": "2027-02-14", "planned": True}],
            "north_star": {"goal": "Sub-3:15 Marathon", "race_date": "2028-04-23", "planned": True},
        },
    )
    assert [s["planned"] for s in merged["sub_goals"]] == [True, False]
    assert merged["north_star"]["planned"] is True
