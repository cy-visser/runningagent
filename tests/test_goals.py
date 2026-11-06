"""Goal plans: block progression, race-result auto-save, north-star Riegel gap, coach instruction."""

from datetime import date
from types import SimpleNamespace

import running_coach.agent as agent
from running_coach.utils.goals import (
    KIND_NORTH_STAR,
    KIND_SINGLE,
    KIND_SUB_GOAL,
    current_goal,
    final_race_passed,
    north_star_equivalent,
    race_result_update,
    sub_goals_missing_result,
)
from running_coach.utils.profile_helpers import merge_profile_data

SINGLE = {"training_goal": "Sub-3:30 Marathon", "timeline": "2026-11-01", "goal_set_date": "2026-06-01"}


def plan(results=None):
    results = results or {}
    return {
        "goal_type": "plan",
        "north_star": {"goal": "Sub-3:15 Marathon", "race_name": "London Marathon 2028",
                       "start_date": None, "race_date": "2028-04-23"},
        "sub_goals": [
            {"goal": "Sub-43 10K", "start_date": "2027-03-01", "race_date": "2027-05-16", "result": results.get(1)},
            {"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07", "result": results.get(0)},
        ],
    }


def test_block_progression_and_due_states():
    p = plan()
    assert current_goal(SINGLE, date(2026, 10, 23))["kind"] == KIND_SINGLE
    before = current_goal(p, date(2026, 11, 10))
    assert before["kind"] == KIND_SUB_GOAL and before["training_goal"] == "Sub-21 5K" and before["before_start"]
    active = current_goal(p, date(2027, 1, 15))
    assert active["training_goal"] == "Sub-21 5K" and not active["before_start"]
    assert final_race_passed(p, date(2027, 2, 10)) is None             # sub-goal race never ends the plan
    assert [b["training_goal"] for b in sub_goals_missing_result(p, date(2027, 2, 10))] == ["Sub-21 5K"]
    ns_active = current_goal(p, date(2027, 6, 1))
    assert ns_active["kind"] == KIND_NORTH_STAR and ns_active["goal_set_date"] == "2027-05-17"
    assert final_race_passed(p, date(2028, 4, 24)) is not None


def test_race_result_update_and_north_star_equivalent():
    assert round(north_star_equivalent(1260, "Sub-21 5K", "Sub-3:15 Marathon")) == 12085
    update = race_result_update(plan(), "2027-02-07", 1245, "w1", "Run")
    saved = [s for s in update["sub_goals"] if s["goal"] == "Sub-21 5K"][0]["result"]
    assert saved == {"time": "20:45", "time_s": 1245, "workout_id": "w1"}
    assert race_result_update(plan(), "2027-02-07", 1245, "w1", "Bike") is None
    assert race_result_update(SINGLE, "2026-11-01", 12000, "w1", "Run") is None


def test_merge_profile_preserves_saved_sub_goal_results():
    saved = {"time": "20:45", "time_s": 1245, "workout_id": "1"}
    merged = merge_profile_data(
        answers={
            "goal_type": "plan",
            "north_star_goal": "Sub-3:15 Marathon",
            "north_star_race_date": "2028-04-23",
            "sub_goals": [
                {"goal": "Sub-43 10K", "start_date": "2027-02-15", "race_date": "2027-05-02"},
                {"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07"},
            ],
        },
        temp_data={"firstname": "Casper", "lastname": "Visser",
                   "sub_goals": [{"goal": "sub-21 5k", "race_date": "2027-02-07", "result": saved}]},
    )
    assert [s["goal"] for s in merged["sub_goals"]] == ["Sub-21 5K", "Sub-43 10K"]
    assert merged["sub_goals"][0]["result"] == saved


def test_coach_instruction_distinguishes_plan_and_single_goal(monkeypatch):
    person = {"firstname": "Cyrille", "lastname": "Visser", "location": "Utrecht"}
    monkeypatch.setattr(agent, "get_today_date", lambda: date(2027, 2, 8))
    monkeypatch.setattr(agent, "get_today_str", lambda with_weekday=False: "2027-02-08")
    plan_text = agent.build_coach_instruction(SimpleNamespace(state={"user_profile": {**person, **plan()}}))
    assert "GOAL PLAN (north star with sub goals)" in plan_text
    assert "SUB-GOAL RACE DONE: sub goal Sub-21 5K was raced on 2027-02-07" in plan_text
    assert "Do not offer onboarding." in plan_text

    single_text = agent.build_coach_instruction(SimpleNamespace(state={"user_profile": {**person, **SINGLE}}))
    assert "GOAL PLAN (north star" not in single_text and "GOAL RACE DONE" in single_text
