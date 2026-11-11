"""Behavioural test for profile edit validation, saved result preservation, and coordinate invalidation."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.profile_model import ProfileUpdatePayload, apply_profile_edit


def test_profile_single_goal_edit_plan_result_preservation_and_ordering_validation():
    # Single-goal change sets goal_set_date and clears cached coords on location change
    existing_single = {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": "cyrille@cyvisser.altostrat.com",
        "location": "Utrecht",
        "latitude": 52.09,
        "longitude": 5.12,
        "goal_type": "single",
        "training_goal": "Sub-3:30 Marathon",
        "timeline": "2026-11-01",
        "goal_set_date": "2026-06-01",
    }
    single_payload = ProfileUpdatePayload(
        location="Amsterdam",
        goal_type="single",
        training_goal="Sub-3:20 Marathon",
        timeline="2027-04-11",
        shoe_rotation={"easy": "Superblast 2"},
    )
    updates, deleted = apply_profile_edit(existing_single, single_payload, today_iso="2026-11-05")
    assert "firstname" not in updates and "email" not in updates
    assert updates["goal_set_date"] == "2026-11-05"
    assert set(deleted) == {"latitude", "longitude"}

    # Plan edit preserves sub-goal results and sorts sub-goals chronologically
    saved_res = {"time": "20:42", "time_s": 1242}
    existing_plan = {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": "cyrille@cyvisser.altostrat.com",
        "goal_type": "plan",
        "sub_goals": [{"goal": "Sub-21 5K", "race_date": "2027-02-07", "result": saved_res}],
    }
    plan_payload = ProfileUpdatePayload(
        goal_type="plan",
        north_star={"goal": "Sub-3:15 Marathon", "race_name": "London", "race_date": "2028-04-23"},
        sub_goals=[
            {"goal": "Sub-43 10K", "start_date": "2027-02-15", "race_date": "2027-05-02"},
            {"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07"},
        ],
    )
    plan_updates, _ = apply_profile_edit(existing_plan, plan_payload, today_iso="2026-11-05")
    assert [s["goal"] for s in plan_updates["sub_goals"]] == ["Sub-21 5K", "Sub-43 10K"]
    assert plan_updates["sub_goals"][0]["result"] == saved_res
    assert plan_updates["sub_goals"][1]["result"] is None

    # Rejects sub-goal scheduled after north-star race date
    with pytest.raises(ValidationError):
        ProfileUpdatePayload(
            goal_type="plan",
            north_star={"goal": "Sub-3:15 Marathon", "race_date": "2027-04-01"},
            sub_goals=[{"goal": "Sub-21 5K", "start_date": "2027-03-01", "race_date": "2027-05-01"}],
        )


def test_profile_edit_round_trips_planned_flags():
    existing = {"goal_type": "plan", "north_star": {"goal": "Sub-3:15", "race_date": "2028-04-23"},
                "sub_goals": [{"goal": "Sub-43 10K", "race_date": "2027-02-14", "result": None}], "planned": True}
    payload = ProfileUpdatePayload(
        goal_type="plan",
        north_star={"goal": "Sub-3:15", "race_date": "2028-04-23", "planned": True},
        sub_goals=[{"goal": "Sub-43 10K", "start_date": "2026-11-16", "race_date": "2027-02-14", "planned": True},
                   {"goal": "Sub-1:30 HM", "start_date": "2027-03-01", "race_date": "2027-05-02"}],
    )
    updates, deleted = apply_profile_edit(existing, payload, today_iso="2026-11-11")
    assert [s["planned"] for s in updates["sub_goals"]] == [True, False]
    assert updates["north_star"]["planned"] is True
    assert "planned" in deleted  # a stale single-goal flag is removed when switching to a plan

    single = ProfileUpdatePayload(goal_type="single", training_goal="Sub-3:20", timeline="2027-04-11", planned=True)
    updates, _ = apply_profile_edit({"goal_type": "single"}, single, today_iso="2026-11-11")
    assert updates["planned"] is True


def test_profile_edit_saves_training_times_and_deletes_the_legacy_strength_text():
    existing = {"goal_type": "single", "training_goal": "Sub-3:20", "timeline": "2027-04-11",
                "cross_training_strength": "2x cycling + 1x strength"}
    payload = ProfileUpdatePayload(goal_type="single", training_goal="Sub-3:20", timeline="2027-04-11",
                                   run_time_of_day="morning", strength_time_of_day="evening")
    updates, deleted = apply_profile_edit(existing, payload, today_iso="2026-11-11")
    assert (updates["run_time_of_day"], updates["strength_time_of_day"]) == ("morning", "evening")
    assert "cross_training_strength" in deleted and "cross_training_strength" not in updates

    _, clean = apply_profile_edit({"goal_type": "single"}, payload, today_iso="2026-11-11")
    assert "cross_training_strength" not in clean

    with pytest.raises(ValidationError):
        ProfileUpdatePayload(goal_type="single", training_goal="Sub-3:20", timeline="2027-04-11",
                             run_time_of_day="noon")
