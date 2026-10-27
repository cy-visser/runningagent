"""Tests for the coaching InstructionProvider: everything derived from user_profile, nothing from state keys."""

from datetime import date
from types import SimpleNamespace

import pytest

import running_coach.agent as agent
from tests.test_goals import SINGLE, plan

PERSON = {"firstname": "Cyrille", "lastname": "Visser", "location": "Utrecht"}


@pytest.fixture
def today(monkeypatch):
    def set_today(day: date):
        monkeypatch.setattr(agent, "get_today_date", lambda: day)
        monkeypatch.setattr(agent, "get_today_str", lambda with_weekday=False: day.isoformat())
    return set_today


def build(profile):
    return agent.build_coach_instruction(SimpleNamespace(state={"user_profile": {**PERSON, **profile}}))


def test_single_goal_has_no_goal_plan_or_notice(today):
    today(date(2026, 10, 23))
    text = build(SINGLE)
    assert "Today's date is 2026-10-23." in text
    assert "Goal: Sub-3:30 Marathon (Timeline: 2026-11-01)" in text
    assert "GOAL PLAN (north star" not in text
    assert "GOAL RACE DONE" not in text and "SUB-GOAL RACE DONE" not in text
    assert "CRITICAL COACHING CONTRACT" in text  # static rules still appended


def test_final_single_race_passed_offers_onboarding(today):
    today(date(2026, 11, 2))
    text = build(SINGLE)
    assert "GOAL RACE DONE" in text
    assert "analyze_workout for 2026-11-01" in text
    assert "request_new_goal" in text and "never force it" in text


def test_plan_shows_hierarchy(today):
    today(date(2027, 1, 10))
    text = build(plan())
    assert "Current block Sub-21 5K (Race: 2027-02-07) -> North star Sub-3:15 Marathon" in text
    assert "GOAL PLAN (north star with sub goals)" in text
    assert "SUB-GOAL RACE DONE" not in text


def test_sub_goal_race_without_result_asks_runner_no_onboarding(today):
    today(date(2027, 2, 8))
    text = build(plan())
    assert "SUB-GOAL RACE DONE: sub goal Sub-21 5K was raced on 2027-02-07" in text
    assert "upload or sync the race" in text
    assert "The next block is Sub-43 10K." in text
    assert "GOAL RACE DONE: the runner's goal race" not in text
    assert "Do not offer onboarding." in text


def test_saved_result_clears_notice(today):
    today(date(2027, 2, 8))
    text = build(plan(results={0: {"time": "20:45", "time_s": 1245}}))
    assert "SUB-GOAL RACE DONE" not in text
    assert "20:45 -> 3:19:01" in text


def test_north_star_race_passed(today):
    today(date(2028, 4, 24))
    text = build(plan(results={i: {"time_s": 1} for i in range(3)}))
    assert "GOAL RACE DONE: the runner's goal race (2028-04-23)" in text
