"""Tests for profile edit validation, saved result preservation, and coordinate invalidation."""

import pytest
from pydantic import ValidationError

from app.profile_model import ProfileUpdatePayload, apply_profile_edit


def test_single_goal_change_sets_goal_set_date_and_clears_coords_on_location_change():
    existing = {
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
    payload = ProfileUpdatePayload(
        location="Amsterdam",
        goal_type="single",
        training_goal="Sub-3:20 Marathon",
        timeline="2027-04-11",
        shoe_rotation="Superblast 2",
    )
    updates, deleted = apply_profile_edit(existing, payload, today_iso="2026-11-05")
    assert "firstname" not in updates and "email" not in updates
    assert updates["goal_set_date"] == "2026-11-05"
    assert set(deleted) == {"latitude", "longitude"}


def test_plan_edit_preserves_sub_goal_results_and_validates_ordering():
    saved_res = {"time": "20:42", "time_s": 1242}
    existing = {
        "firstname": "Cyrille",
        "lastname": "Visser",
        "email": "cyrille@cyvisser.altostrat.com",
        "goal_type": "plan",
        "sub_goals": [{"goal": "Sub-21 5K", "race_date": "2027-02-07", "result": saved_res}],
    }
    payload = ProfileUpdatePayload(
        goal_type="plan",
        north_star={"goal": "Sub-3:15 Marathon", "race_name": "London", "race_date": "2028-04-23"},
        sub_goals=[
            {"goal": "Sub-43 10K", "start_date": "2027-02-15", "race_date": "2027-05-02"},
            {"goal": "Sub-21 5K", "start_date": "2026-11-30", "race_date": "2027-02-07"},
        ],
    )
    updates, _ = apply_profile_edit(existing, payload, today_iso="2026-11-05")
    assert [s["goal"] for s in updates["sub_goals"]] == ["Sub-21 5K", "Sub-43 10K"]
    assert updates["sub_goals"][0]["result"] == saved_res
    assert updates["sub_goals"][1]["result"] is None


def test_rejects_sub_goal_after_north_star():
    with pytest.raises(ValidationError):
        ProfileUpdatePayload(
            goal_type="plan",
            north_star={"goal": "Sub-3:15 Marathon", "race_date": "2027-04-01"},
            sub_goals=[{"goal": "Sub-21 5K", "start_date": "2027-03-01", "race_date": "2027-05-01"}],
        )
