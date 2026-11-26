"""Behavioural tests for the Calendar-Year Annual Review feature, zero-LLM quick action, and backfill CLI."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
import importlib.util
import json
import pathlib
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from running_coach.agent import app
from running_coach.coach.coaching.coaching_agent import coaching_agent
from running_coach.coach.coaching.quick_actions import QUICK_ACTION_PART_PREFIX
from running_coach.features.year_review.helpers.fitness_progress import (
    compute_fitness_shift,
    format_peak_performances,
)
from running_coach.features.year_review.helpers.races import detect_main_races
from running_coach.features.year_review.refresh_year_review_tool import refresh_year_review
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY
from running_coach.tests.fakes import EMAIL, PLAN_PROFILE


class _NoCallLlm(BaseLlm):
    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="unexpected")]))


def test_detect_main_races_uses_only_structured_signals_and_profile_prs():
    start = date(2026, 1, 1)
    today = date(2026, 10, 27)
    workouts = [
        # 1. Matches Profile Sub-Goal on 2026-10-20 (beats stored 5K PR 21:30 -> 20:45 => is_pr=True!)
        {
            "id": "w_5k",
            "date": "2026-10-20",
            "title": "Running",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 5.0,
            "duration_actual": 1245 / 3600,
        },
        # 2. Matches TP A-priority Event (Meters distance) + Profile HM PR date
        {
            "id": "w_hm",
            "date": "2026-03-22",
            "title": "Running",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 21.1,
            "duration_actual": 5268 / 3600,
        },
        # 3. Explicitly tagged `race` in TP workout userTags (detected even without TP Event!)
        {
            "id": "w_10k_tagged",
            "date": "2026-06-14",
            "title": "Rotterdam Summer 10K",
            "sport": "Run",
            "tags": "race, road",
            "type": "completed",
            "distance_actual_km": 10.1,
            "duration_actual": 2500 / 3600,
        },
        # 4. Sport == "Race" (detected explicitly)
        {
            "id": "w_sport_race",
            "date": "2026-08-02",
            "title": "Club 5K",
            "sport": "Race",
            "type": "completed",
            "distance_actual_km": 5.0,
            "duration_actual": 1400 / 3600,  # slower than 21:30 profile PR -> is_pr=False
        },
        # 5. False-positive regression: "5km Shake out" (no Event, no race tag, sport=Run -> MUST NOT match)
        {
            "id": "w_shakeout",
            "date": "2026-10-18",
            "title": "5km Shake out",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 5.18,
            "duration_actual": 2108 / 3600,
        },
        # 6. Untagged title naming a race without Event/tag/Goal -> MUST NOT match (zero title guessing)
        {
            "id": "w_untagged_title",
            "date": "2026-09-20",
            "title": "Rotterdam 10K Race",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 10.0,
            "duration_actual": 2600 / 3600,
        },
    ]
    events = [
        {
            "id": "ev1",
            "name": "CPC Loop Den Haag Half Marathon",
            "eventDate": "2026-03-22T00:00:00",
            "eventType": "RunningRoad",
            "atpPriority": "A",
            "distance": 21097.0,
            "distanceUnits": "Meters",
            "workouts": [],
            "results": [{"resultType": "Overall", "place": None}],
        },
        # Unrun event with only empty placeholder TP results rows -> MUST NOT appear
        {
            "id": "ev_unrun",
            "name": "Skipped 10K",
            "eventDate": "2026-05-01T00:00:00",
            "eventType": "RunningRoad",
            "atpPriority": "B",
            "distance": 10000.0,
            "distanceUnits": "Meters",
            "workouts": [],
            "results": [{"resultType": "Overall", "place": None}],
        },
    ]
    profile = {
        **PLAN_PROFILE,
        "personal_records": {
            "5k": {"time": "21:30", "time_s": 1290, "date": "2025-05-10"},
            "half_marathon": {"time": "1:27:48", "time_s": 5268, "date": "2026-03-22"},
            # Marathon PR on another date should NEVER affect 10K or 5K!
            "marathon": {"time": "3:57:17", "time_s": 14237, "date": "2026-06-14"},
        },
    }
    records = [
        {
            "workout_id": "w_5k",
            "date": "2026-10-20",
            "sport": "Run",
            "distance_km": 5.0,
            "duration_s": 1245,
            "avg_hr": 176.0,
            "session_decoupling": 2.4,
        }
    ]
    daily_pmc = [
        {"date": "2026-03-22", "ctl": 58.2},
        {"date": "2026-06-14", "ctl": 60.5},
        {"date": "2026-08-02", "ctl": 61.0},
        {"date": "2026-10-20", "ctl": 63.1},
    ]

    races, unlogged = detect_main_races(
        profile=profile,
        workouts=workouts,
        records=records,
        events=events,
        daily_pmc=daily_pmc,
        start=start,
        today=today,
        lthr=172.0,
    )

    assert [r["date"] for r in races] == ["2026-10-20", "2026-08-02", "2026-06-14", "2026-03-22"]
    by_date = {r["date"]: r for r in races}

    # Sub-goal beat stored 5K profile PR (1245s <= 1290s)
    r5k = by_date["2026-10-20"]
    assert r5k["badge"] == "Sub-Goal"
    assert r5k["is_pr"] is True
    assert r5k["avg_hr"] == 176
    assert r5k["pct_lthr"] == 102
    assert r5k["goal_gap_s"] == -15
    assert r5k["ctl"] == 63.1

    # Slower 5K race than profile PR (1400s > 1290s) -> NOT a PR
    assert by_date["2026-08-02"]["is_pr"] is False

    # Distance-matched PR check: 10K on 2026-06-14 must NOT inherit Marathon PR date on 2026-06-14!
    assert by_date["2026-06-14"]["distance_label"] == "10K"
    assert by_date["2026-06-14"]["is_pr"] is False

    # TP A-event merged with workout + profile HM PR
    rhm = by_date["2026-03-22"]
    assert rhm["badge"] == "A Race"
    assert rhm["name"] == "CPC Loop Den Haag Half Marathon"
    assert rhm["is_pr"] is True
    assert rhm["short_label"] == "HM"

    assert set(unlogged) == {"w_10k_tagged", "w_sport_race", "w_hm"}


def test_format_peak_performances_fixes_zero_indexed_rank_and_uses_profile_prs():
    start = date(2026, 1, 1)
    today = date(2026, 11, 25)
    peaks_year = {
        "speedMarathon": {
            "records": [
                {"rank": 0, "value": 2.6559, "workout_id": 3677949518, "workout_title": "Running", "date": "2026-04-12"},
                {"rank": 1, "value": 2.5639, "workout_id": 3965352814, "workout_title": "NYC Marathon", "date": "2026-11-01"},
            ]
        },
        "speed5K": {
            "records": [
                {"rank": 0, "value": 3.88, "workout_id": 111, "workout_title": "5K Race", "date": "2026-05-10"},
                {"rank": 1, "value": 3.60, "workout_id": 222, "workout_title": "Tempo Run", "date": "2026-02-27"},
            ]
        },
    }
    profile = {
        "personal_records": {
            "5k": {"time": "21:30", "time_s": 1290, "date": "2026-05-10"},
            "marathon": {"time": "3:57:17", "time_s": 14237, "date": "2025-10-19"},
        }
    }

    peaks = format_peak_performances(peaks_year, profile, start, today)
    by_type = {p["pr_type"]: p for p in peaks}

    # rank: 0 MUST beat rank: 1 (Paris Apr 12 beat NYC Nov 1)
    assert by_type["speedMarathon"]["workout_id"] == "3677949518"
    assert by_type["speedMarathon"]["date"] == "2026-04-12"
    assert by_type["speedMarathon"]["all_time_pr"] is False
    assert by_type["speedMarathon"]["profile_pr_time"] == "3:57:17"

    # 5K matches profile.personal_records.5k date -> all_time_pr=True
    assert by_type["speed5K"]["workout_id"] == "111"
    assert by_type["speed5K"]["all_time_pr"] is True
    assert by_type["speed5K"]["profile_pr_time"] == "21:30"


def test_refresh_year_review_computes_calendar_year_payload_and_caches_in_firestore(runner):
    runner.events = [
        {
            "id": "ev-hm",
            "name": "Spring Half Marathon",
            "eventDate": "2026-03-22",
            "eventType": "RunningRoad",
            "atpPriority": "A",
            "distance": 21097.0,
            "distanceUnits": "Meters",
        }
    ]
    runner.workouts.extend([
        {
            "id": "w_spring_hm",
            "date": "2026-03-22",
            "title": "Running",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 21.1,
            "duration_actual": 5268 / 3600,
            "tss_actual": 148.0,
        },
        {
            "id": "w_jan_2026",
            "date": "2026-01-12",
            "title": "Easy Winter Run",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 12.0,
            "duration_actual": 1.05,
            "tss_actual": 62.0,
        },
        # Prior calendar year (2025): MUST NOT leak into 2026!
        {
            "id": "w_prior_year_dec",
            "date": "2025-12-20",
            "title": "Prior Year Run",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 15.0,
            "duration_actual": 1.25,
            "tss_actual": 70.0,
        },
        {
            "id": "w_strength_1",
            "date": "2026-09-12",
            "title": "Heavy Lower S&C",
            "sport": "Strength",
            "type": "completed",
            "duration_actual": 0.75,
            "tss_actual": 35.0,
        },
    ])
    early_base = date(2026, 1, 5)
    for i in range(40):
        d = (early_base + timedelta(days=i)).isoformat()
        runner.daily_pmc.insert(i, {"date": d, "ctl": round(38.0 + i * 0.1, 1), "atl": 40.0, "tsb": -2.0})
        runner.metrics.insert(
            i,
            {
                "timeStamp": f"{d}T00:00:00",
                "details": [
                    {"type": 60, "value": 52.0},
                    {"type": 5, "value": 53.0},
                    {"type": 7, "value": 7.4},
                ],
            },
        )

    runner.peaks = {
        ("speed5K", "2026-01-01", "2026-10-27"): [
            {"rank": 0, "value": 3.876, "workout_id": "w_pr_5k", "workout_title": "May 5K", "date": "2026-05-10"},
            {"rank": 1, "value": 3.600, "workout_id": "w_slower", "workout_title": "Tempo", "date": "2026-04-01"},
        ],
        ("speedHalfMarathon", "2026-01-01", "2026-10-27"): [
            {"rank": 0, "value": 4.005, "workout_id": "w_spring_hm", "workout_title": "Spring HM", "date": "2026-03-22"}
        ],
    }

    ctx = runner.ctx()
    raw_result = asyncio.run(refresh_year_review(ctx))
    res = json.loads(raw_result)
    assert res["status"] == "ready"
    assert res["year"] == 2026
    assert res["is_complete"] is False
    assert ctx.actions.skip_summarization is True

    cached = runner.year_review_cache.get(("cyrille_visser", 2026))
    assert cached is not None
    assert cached["version"] == 5
    assert cached["year"] == 2026
    assert cached["is_complete"] is False
    assert cached["last_computed_date"] == "2026-10-27"
    assert cached["window"]["start"] == "2026-01-01"
    assert cached["window"]["end"] == "2026-10-27"
    assert cached["window"]["year_end"] == "2026-12-31"

    # Always 12 calendar months Jan-Dec; Oct is partial, Nov & Dec are future
    assert len(cached["monthly"]) == 12
    assert [m["label"] for m in cached["monthly"]] == [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ]
    assert cached["monthly"][9]["partial"] is True
    assert cached["monthly"][10]["future"] is True
    assert cached["monthly"][11]["future"] is True

    # Heatmap spans full Jan 1 - Dec 31 with level=-2 for remaining days in 2026
    assert len(cached["heatmap"]["weeks"]) >= 52
    assert all(len(w["days"]) == 7 for w in cached["heatmap"]["weeks"])
    future_cells = [
        d for wk in cached["heatmap"]["weeks"] for d in wk["days"]
        if d["date"] > "2026-10-27" and d["date"] <= "2026-12-31"
    ]
    assert future_cells and all(c["level"] == -2 for c in future_cells)

    # Prior year workout (2025-12-20) must be excluded from 2026 raw cache
    raw_ids = {w["id"] for w in runner.year_review_raw_cache[("cyrille_visser", 2026)]["workouts"]}
    assert "w_jan_2026" in raw_ids
    assert "w_prior_year_dec" not in raw_ids

    monthly_km = round(sum(m["km"] for m in cached["monthly"]), 1)
    assert abs(monthly_km - cached["kpis"]["total_run_km"]) <= 0.5
    assert cached["kpis"]["ctl_start"] == 38.0
    assert cached["kpis"]["ctl_end"] > cached["kpis"]["ctl_start"]
    assert cached["kpis"]["strength_hours"] > 0

    race_dates = [r["date"] for r in cached["races"]]
    assert "2026-10-20" in race_dates and "2026-03-22" in race_dates
    peaks_by_type = {p["pr_type"]: p for p in cached["peaks"]}
    assert peaks_by_type["speed5K"]["workout_id"] == "w_pr_5k"
    assert peaks_by_type["speed5K"]["all_time_pr"] is True
    assert peaks_by_type["speed5K"]["profile_pr_time"] == "21:30"
    assert peaks_by_type["speedHalfMarathon"]["all_time_pr"] is False

    # Index updated with 2026
    idx_years = runner.year_review_index["cyrille_visser"]["years"]
    assert [y["year"] for y in idx_years] == [2026]

    # Exact date-bounded tp_get_peaks used (never days=3650 or tp_analyze_workout)
    peak_calls = [kw for n, kw in runner.tp_calls if n == "tp_get_peaks"]
    assert peak_calls and all(
        kw.get("start_date") == "2026-01-01" and kw.get("end_date") == "2026-10-27"
        for kw in peak_calls
    )
    assert not any(name == "tp_analyze_workout" for name, _ in runner.tp_calls)


def test_year_review_quick_action_runs_with_zero_llm_calls(runner, monkeypatch):
    llm = _NoCallLlm(model="fake")
    llm.requests = []
    monkeypatch.setattr(coaching_agent, "model", llm)

    async def scenario():
        r = InMemoryRunner(app=app)
        session = await r.session_service.create_session(app_name="running_coach", user_id="web_runner")
        parts = [
            types.Part(text="Refresh 2026 annual review"),
            types.Part(
                text=QUICK_ACTION_PART_PREFIX
                + json.dumps({"skill": "year-review", "args": {"year": 2026, "force_full": False}})
            ),
        ]
        events = []
        async for ev in r.run_async(
            user_id="web_runner",
            session_id=session.id,
            state_delta={AUTH_EMAIL_STATE_KEY: EMAIL},
            new_message=types.Content(role="user", parts=parts),
        ):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert llm.requests == []
    assert events[-1].actions.skip_summarization is True
    assert ("cyrille_visser", 2026) in runner.year_review_cache
    assert ("cyrille_visser", 2026) in runner.year_review_raw_cache
    assert runner.year_review_index["cyrille_visser"]["years"][0]["year"] == 2026


def test_refresh_year_review_incremental_only_pulls_new_dates_and_caches_finished_years(runner):
    runner.workouts.extend([
        {
            "id": "w_2025_winter",
            "date": "2025-11-04",
            "title": "Autumn 2025 Run",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 15.0,
            "duration_actual": 1.3,
            "tss_actual": 70.0,
        },
        {
            "id": "w_spring_race",
            "date": "2026-04-12",
            "title": "Spring 10K",
            "sport": "Run",
            "tags": "race",
            "type": "completed",
            "distance_actual_km": 10.0,
            "duration_actual": 2400 / 3600,
            "tss_actual": 92.0,
        },
    ])
    runner.peaks = {
        "speed5K": [
            {"rank": 0, "value": 4.016, "workout_id": "w_race_5k", "workout_title": "Amsterdam 5K", "date": "2026-05-10"}
        ],
    }

    # 1. Cold 2026 run -> full Jan 1..Oct 27 fetch + race detail for tagged spring race
    first = json.loads(asyncio.run(refresh_year_review(runner.ctx(), year=2026)))
    assert first["mode"] == "full"
    assert sum(1 for n, _ in runner.tp_calls if n == "tp_get_workouts") >= 4
    assert any(n == "tp_get_workout" and kw.get("workout_id") == "w_spring_race" for n, kw in runner.tp_calls)
    assert runner.year_review_raw_cache[("cyrille_visser", 2026)]["last_computed_date"] == "2026-10-27"

    # 2. Advance 14 days -> incremental pull strictly from last_computed_date (2026-10-27) to today (2026-11-10)
    runner.now = datetime(2026, 11, 10, 9, 0, 0)
    runner.today = runner.now.date()
    runner.workouts.append({
        "id": "w_new_nov_run",
        "date": "2026-11-08",
        "title": "November Sunday Long Run",
        "sport": "Run",
        "type": "completed",
        "distance_actual_km": 22.0,
        "duration_actual": 1.9,
        "tss_actual": 120.0,
    })
    runner.daily_pmc.append({"date": "2026-11-08", "ctl": 66.5, "atl": 70.0, "tsb": -3.5})
    runner.tp_calls.clear()

    second = json.loads(asyncio.run(refresh_year_review(runner.ctx(), year=2026, force_full=False)))
    assert second["mode"] == "incremental"

    wk_calls = [kw for n, kw in runner.tp_calls if n == "tp_get_workouts"]
    ev_calls = [kw for n, kw in runner.tp_calls if n == "tp_get_events"]
    mt_calls = [kw for n, kw in runner.tp_calls if n == "tp_get_metrics"]
    fit_calls = [kw for n, kw in runner.tp_calls if n == "tp_get_fitness"]
    assert len(wk_calls) == 1 and wk_calls[0]["start_date"] == "2026-10-27" and wk_calls[0]["end_date"] == "2026-11-10"
    assert len(ev_calls) == 1 and ev_calls[0]["start_date"] == "2026-10-27"
    assert len(mt_calls) == 1 and mt_calls[0]["start_date"] == "2026-10-27"
    assert len(fit_calls) == 1 and fit_calls[0]["start_date"] == "2026-10-27" and fit_calls[0]["end_date"] == "2026-11-10"
    # Existing workouts (< 2026-10-27) and already-cached race details are NEVER re-pulled
    assert not any(n == "tp_get_workout" and kw.get("workout_id") == "w_spring_race" for n, kw in runner.tp_calls)

    raw_ids = {w["id"] for w in runner.year_review_raw_cache[("cyrille_visser", 2026)]["workouts"]}
    assert "w_new_nov_run" in raw_ids
    assert "w_spring_race" in raw_ids
    assert "w_2025_winter" not in raw_ids

    # 3. Explicit force_full=True re-pulls Jan 1..today
    runner.tp_calls.clear()
    forced = json.loads(asyncio.run(refresh_year_review(runner.ctx(), year=2026, force_full=True)))
    assert forced["mode"] == "full"
    assert sum(1 for n, _ in runner.tp_calls if n == "tp_get_workouts") >= 4

    # 4. Finished historical year (2025): full build once, then cached with 0 TP calls unless force_full=True
    runner.tp_calls.clear()
    hist_first = json.loads(asyncio.run(refresh_year_review(runner.ctx(), year=2025)))
    assert hist_first["mode"] == "full"
    assert hist_first["is_complete"] is True
    cached_2025 = runner.year_review_cache[("cyrille_visser", 2025)]
    assert cached_2025["window"]["start"] == "2025-01-01"
    assert cached_2025["window"]["end"] == "2025-12-31"
    assert all(m["future"] is False for m in cached_2025["monthly"])
    assert [y["year"] for y in runner.year_review_index["cyrille_visser"]["years"]] == [2026, 2025]

    runner.tp_calls.clear()
    hist_cached = json.loads(asyncio.run(refresh_year_review(runner.ctx(), year=2025, force_full=False)))
    assert hist_cached["mode"] == "cached"
    assert runner.tp_calls == []

    hist_forced = json.loads(asyncio.run(refresh_year_review(runner.ctx(), year=2025, force_full=True)))
    assert hist_forced["mode"] == "full"
    assert sum(1 for n, _ in runner.tp_calls if n == "tp_get_workouts") >= 5


def test_backfill_script_resolves_years_dry_run_and_runs_against_fakes(runner):
    script_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "backfill_annual_reviews.py"
    spec = importlib.util.spec_from_file_location("backfill_annual_reviews", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Default range 2023..2025 sorted latest-first
    assert mod.resolve_target_years(today=date(2026, 10, 27)) == [2025, 2024, 2023]
    assert mod.resolve_target_years(years=[2023, 2025, 2025], today=date(2026, 10, 27)) == [2025, 2023]

    # Dry-run plans without calling TP or writing Firestore
    plan = asyncio.run(
        mod.backfill_years(
            runner_id="cyrille_visser",
            years=[2025, 2024],
            dry_run=True,
            today=date(2026, 10, 27),
        )
    )
    assert [p["year"] for p in plan] == [2025, 2024]
    assert all(p["action"] == "backfill" and p["chunks"] == 5 for p in plan)
    assert runner.tp_calls == []
    assert runner.year_review_cache == {}

    # Fake TP tools execute backfill cleanly into in-memory Firestore (zero live calls)
    runner.workouts.extend([
        {
            "id": "w_2025_run",
            "date": "2025-05-15",
            "title": "Easy 2025 Run",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 14.0,
            "duration_actual": 1.2,
            "tss_actual": 68.0,
        },
        {
            "id": "w_2024_run",
            "date": "2024-09-10",
            "title": "Easy 2024 Run",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": 11.0,
            "duration_actual": 0.95,
            "tss_actual": 55.0,
        },
    ])

    async def _call(name: str, **kw):
        env_res = await runner.run_tp_tool(None, name, **kw)
        return json.loads(env_res["content"][0]["text"])

    fake_tools = {
        "workouts": lambda s, e: _call("tp_get_workouts", start_date=s, end_date=e),
        "events": lambda s, e: _call("tp_get_events", start_date=s, end_date=e),
        "metrics": lambda s, e: _call("tp_get_metrics", start_date=s, end_date=e),
        "fitness": lambda start_date, end_date: _call("tp_get_fitness", start_date=start_date, end_date=end_date),
        "settings": lambda: _call("tp_get_athlete_settings"),
        "peaks": lambda sport, pr_type, start_date, end_date: _call(
            "tp_get_peaks", sport=sport, pr_type=pr_type, start_date=start_date, end_date=end_date
        ),
        "workout": lambda wid: _call("tp_get_workout", workout_id=wid),
    }

    results = asyncio.run(
        mod.backfill_years(
            runner_id="cyrille_visser",
            years=[2025, 2024],
            delay_seconds=0,
            tp_tools=fake_tools,
            today=date(2026, 10, 27),
        )
    )
    assert [(r["year"], r["status"], r["is_complete"]) for r in results] == [
        (2025, "ready", True),
        (2024, "ready", True),
    ]
    assert ("cyrille_visser", 2025) in runner.year_review_cache
    assert ("cyrille_visser", 2024) in runner.year_review_cache
    assert [y["year"] for y in runner.year_review_index["cyrille_visser"]["years"]] == [2025, 2024]


def test_aggregate_year_uses_peak_ctl_for_monthly_and_weekly_series():
    from running_coach.features.year_review.helpers.aggregation import aggregate_year

    daily_pmc = [
        {"date": "2026-10-05", "ctl": 64.4, "tss": 0.0},
        {"date": "2026-10-11", "ctl": 68.2, "tss": 222.7},
        {"date": "2026-10-18", "ctl": 67.3, "tss": 147.8},
        {"date": "2026-10-26", "ctl": 62.5, "tss": 0.0},
        {"date": "2026-10-31", "ctl": 58.3, "tss": 0.0},
    ]
    agg = aggregate_year(
        year=2026,
        workouts=[
            {
                "id": "w_oct",
                "date": "2026-10-11",
                "title": "Peak Long Run 30km",
                "sport": "Run",
                "type": "completed",
                "distance_actual_km": 30.0,
                "duration_actual": 2.8,
                "tss_actual": 222.7,
            }
        ],
        records=[],
        daily_pmc=daily_pmc,
        races=[],
        start=date(2026, 1, 1),
        end=date(2026, 11, 25),
        is_complete=False,
    )
    oct_row = next(m for m in agg["monthly"] if m["month"] == "2026-10")
    assert oct_row["ctl"] == 68.2
    assert oct_row["ctl_peak_date"] == "2026-10-11"

    wk_oct5 = next(w for w in agg["weekly"] if w["week"] == "2026-10-05")
    assert wk_oct5["ctl"] == 68.2
    assert wk_oct5["ctl_peak_date"] == "2026-10-11"

    wk_oct26 = next(w for w in agg["weekly"] if w["week"] == "2026-10-26")
    assert wk_oct26["ctl"] == 62.5
    assert wk_oct26["ctl_peak_date"] == "2026-10-26"

    # KPI card still reports exact Oct 11 peak and latest end-of-window CTL
    assert agg["kpis"]["ctl_peak"] == 68.2
    assert agg["kpis"]["ctl_peak_date"] == "2026-10-11"
    assert agg["kpis"]["ctl_end"] == 58.3


def test_compute_fitness_shift_guards_early_calendar_year_rhr_and_hrv_overlap():
    start = date(2026, 1, 1)

    # 1. Early January (< 8 weeks elapsed): must NOT compare January RHR/HRV against itself
    jan_today = date(2026, 1, 15)
    jan_metrics = {
        "rhr": [(start + timedelta(days=i), 54.0) for i in range(15)],
        "hrv": [(start + timedelta(days=i), 50.0) for i in range(15)],
    }
    jan_shift = compute_fitness_shift(
        records=[],
        weekly=[],
        dated_metrics=jan_metrics,
        start=start,
        today=jan_today,
        lthr=172.0,
        lt1_hr=150.0,
    )
    assert jan_shift["items"] == []

    # 2. 10 weeks elapsed (70 days -> non-overlapping 35-day early vs 35-day late windows)
    mar_today = start + timedelta(days=69)  # 2026-03-11 (70 days inclusive)
    mar_metrics = {
        "rhr": (
            [(start + timedelta(days=i), 56.0) for i in range(35)]
            + [(start + timedelta(days=35 + i), 50.0) for i in range(35)]
        ),
        "hrv": (
            [(start + timedelta(days=i), 48.0) for i in range(35)]
            + [(start + timedelta(days=35 + i), 60.0) for i in range(35)]
        ),
    }
    mar_shift = compute_fitness_shift(
        records=[],
        weekly=[],
        dated_metrics=mar_metrics,
        start=start,
        today=mar_today,
        lthr=172.0,
        lt1_hr=150.0,
    )
    by_key = {item["key"]: item for item in mar_shift["items"]}
    assert by_key["rhr"]["start"] == "56 bpm"
    assert by_key["rhr"]["latest"] == "50 bpm"
    assert by_key["rhr"]["verdict"] == "improving"
    assert by_key["hrv"]["start"] == "48 ms"
    assert by_key["hrv"]["latest"] == "60 ms"
    assert by_key["hrv"]["verdict"] == "improving"


def test_fix_historical_tss_script_computes_rtss_filters_and_rolls_back(tmp_path):
    script_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "fix_historical_tss.py"
    spec = importlib.util.spec_from_file_location("fix_historical_tss", script_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class _Resp:
        def __init__(self, data, is_error=False, message=""):
            self.data = data
            self.is_error = is_error
            self.message = message

    class _FakeTPClient:
        def __init__(self, workouts):
            self.by_id = {int(w["workoutId"]): dict(w) for w in workouts}
            self.puts = []

        async def get(self, endpoint: str):
            parts = endpoint.strip("/").split("/")
            if len(parts) == 6 and parts[-2] == "workouts":
                return _Resp(dict(self.by_id[int(parts[-1])]))
            s, e = parts[-2], parts[-1]
            return _Resp([
                dict(w) for w in self.by_id.values()
                if s <= str(w["workoutDay"])[:10] <= e
            ])

        async def put(self, endpoint: str, json: dict):
            wid = int(endpoint.strip("/").split("/")[-1])
            self.by_id[wid] = dict(json)
            self.puts.append(wid)
            return _Resp(dict(json))

        async def post(self, endpoint: str, json: dict):
            day = endpoint.strip("/").split("/")[-1]
            day_tss = sum(
                float(w.get("tssActual") or 0.0)
                for w in self.by_id.values()
                if str(w["workoutDay"])[:10] == day
            )
            return _Resp([{"workoutDay": f"{day}T00:00:00", "tssActual": day_tss, "ctl": 50.0}])

    workouts = [
        # Inflated 2023 run (no normalizedSpeedActual -> falls back to velocityAverage * 0.9888, 2023 thresh 4:25)
        {
            "workoutId": 101,
            "workoutDay": "2023-07-23T00:00:00",
            "title": "Long Run",
            "workoutTypeValueId": 3,
            "totalTime": 2.0,
            "distance": 22000.0,
            "velocityAverage": 3.0556,
            "normalizedSpeedActual": None,
            "tssActual": 510.0,
            "if": 1.60,
            "tssSource": 1,
            "normalizedPowerActual": 352.0,
        },
        # Inflated 2025 stray run (has normalizedSpeedActual, 2025 thresh 4:29)
        {
            "workoutId": 102,
            "workoutDay": "2025-09-26T00:00:00",
            "title": "Aerobic Endurance",
            "workoutTypeValueId": 3,
            "totalTime": 0.5667,
            "distance": 6281.7,
            "velocityAverage": 3.079,
            "normalizedSpeedActual": 3.0279,
            "tssActual": 145.29,
            "if": 1.61,
            "tssSource": 1,
            "normalizedPowerActual": 355.0,
        },
        # Bike with tssSource=1 -> MUST NOT be touched!
        {
            "workoutId": 201,
            "workoutDay": "2025-05-02T00:00:00",
            "title": "Indoor Cycling",
            "workoutTypeValueId": 2,
            "totalTime": 0.5,
            "tssActual": 41.8,
            "if": 0.91,
            "tssSource": 1,
            "normalizedPowerActual": 229.0,
        },
        # Normal post-June-2025 run (tssSource=2) -> MUST NOT be touched!
        {
            "workoutId": 202,
            "workoutDay": "2025-06-15T00:00:00",
            "title": "Normal Run",
            "workoutTypeValueId": 3,
            "totalTime": 1.0,
            "velocityAverage": 3.15,
            "normalizedSpeedActual": 3.08,
            "tssActual": 76.0,
            "if": 0.83,
            "tssSource": 2,
            "normalizedPowerActual": None,
        },
    ]

    client = _FakeTPClient(workouts)
    backup_file = tmp_path / "backup.json"

    # 1. Dry-run finds strictly the 2 inflated runs and performs 0 PUTs
    dry = asyncio.run(
        mod.run_fix(
            client=client,
            athlete_id=1,
            start_date=date(2023, 5, 1),
            end_date=date(2025, 10, 1),
            mode="dry-run",
        )
    )
    assert dry["count"] == 2
    assert client.puts == []

    # 2. Apply updates both runs, keeps Bike & normal Run untouched, and saves backup
    res = asyncio.run(
        mod.run_fix(
            client=client,
            athlete_id=1,
            start_date=date(2023, 5, 1),
            end_date=date(2025, 10, 1),
            mode="apply",
            delay_seconds=0.0,
            backup_path=backup_file,
            remove_backup=False,
        )
    )
    assert res["updated"] == 2
    assert res["failed"] == []
    assert client.puts == [101, 102]
    assert client.by_id[101]["tssSource"] == 2
    assert 120.0 <= client.by_id[101]["tssActual"] <= 165.0
    assert client.by_id[102]["tssSource"] == 2
    assert 35.0 <= client.by_id[102]["tssActual"] <= 55.0
    assert client.by_id[102]["normalizedPowerActual"] is None
    assert client.by_id[201]["tssActual"] == 41.8
    assert client.by_id[202]["tssActual"] == 76.0
    assert backup_file.exists()

    # 3. Rollback restores exact original Power TSS values
    rb = asyncio.run(mod.rollback_from_backup(client, 1, backup_file, delay_seconds=0.0))
    assert rb == {"restored": 2, "failed": 0}
    assert client.by_id[101]["tssActual"] == 510.0
    assert client.by_id[101]["tssSource"] == 1
    assert client.by_id[102]["tssActual"] == 145.29
    assert client.by_id[102]["normalizedPowerActual"] == 355.0

