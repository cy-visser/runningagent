"""Behavioural tests for /api/year-review and /api/year-review/refresh (calendar-year multi-year)."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from conftest import EMAIL, build_test_app

HEADERS = {"X-Goog-IAP-JWT-Assertion": "valid-jwt"}


def _sample_year_review_doc(
    *,
    year: int | None = None,
    is_complete: bool | None = None,
    last_computed_date: str | None = None,
    total_workouts: int = 240,
    total_run_km: float = 2200.0,
    version: int = 5,
) -> dict:
    today = date.today()
    yr = year if year is not None else today.year
    complete = is_complete if is_complete is not None else (yr < today.year)
    end_iso = f"{yr}-12-31" if complete else today.isoformat()
    computed = last_computed_date or end_iso
    return {
        "version": version,
        "year": yr,
        "is_complete": complete,
        "updated_at": f"{computed}T09:00:00Z",
        "as_of_date": end_iso,
        "last_computed_date": computed,
        "sync_mode": "incremental",
        "runner_name": "Cyrille Visser",
        "window": {"start": f"{yr}-01-01", "end": end_iso, "year_end": f"{yr}-12-31", "weeks": 47},
        "coverage": {"total_workouts": total_workouts, "total_runs": 180, "analyzed_runs": 140},
        "kpis": {
            "total_run_km": total_run_km,
            "avg_weekly_run_km": 42.3,
            "total_runs": 180,
            "total_workouts": total_workouts,
            "total_hours": 240.0,
            "run_hours": 195.0,
            "bike_hours": 25.0,
            "strength_hours": 20.0,
            "ctl_start": 40.0,
            "ctl_end": 60.0,
            "ctl_delta": 20.0,
            "ctl_delta_pct": 50,
            "ctl_peak": 66.0,
            "ctl_peak_date": f"{yr}-09-20",
            "total_tss": 15200,
            "active_weeks": 45,
            "total_weeks": 47,
            "active_weeks_pct": 96,
            "longest_streak_weeks": 16,
            "peak_week_km": 74.0,
            "peak_week_date": f"{yr}-09-14",
        },
        "monthly": [],
        "weekly": [],
        "races": [],
        "fitness_shift": [],
        "peaks": [],
        "milestones": {},
        "mix": {"sports": [], "run_breakdown": {}},
        "heatmap": {"weeks": [], "run_days": 180, "longest_streak_weeks": 16},
    }


def test_same_day_current_year_and_finished_past_year_serve_from_cache_without_agent():
    today = date.today()
    cur_yr = today.year
    prev_yr = cur_yr - 1

    app, store, agent = build_test_app()
    store.users["cyrille_visser"] = {"firstname": "Cyrille", "lastname": "Visser", "email": EMAIL}
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}
    store.year_reviews[("cyrille_visser", cur_yr)] = _sample_year_review_doc(
        year=cur_yr, is_complete=False, last_computed_date=today.isoformat(), total_run_km=2486.0
    )
    store.year_reviews[("cyrille_visser", prev_yr)] = _sample_year_review_doc(
        year=prev_yr, is_complete=True, last_computed_date=f"{prev_yr}-12-31", total_run_km=2140.0
    )
    store.year_review_indices["cyrille_visser"] = {
        "years": [
            {"year": cur_yr - 2, "total_run_km": 1892.0, "is_complete": True, "as_of_date": f"{cur_yr - 2}-12-31"},
            {"year": prev_yr, "total_run_km": 2140.0, "is_complete": True, "as_of_date": f"{prev_yr}-12-31"},
            {"year": cur_yr, "total_run_km": 2486.0, "is_complete": False, "as_of_date": today.isoformat()},
        ]
    }

    client = TestClient(app)

    # 1. Same-day re-open on unfinished current year skips recomputation (0 agent calls)
    res_cur = client.get("/api/year-review", headers=HEADERS)
    assert res_cur.status_code == 200
    body_cur = res_cur.json()
    assert body_cur["status"] == "ready"
    assert body_cur["year"] == cur_yr
    assert body_cur["cached"] is True
    assert body_cur["data"]["kpis"]["total_run_km"] == 2486.0
    assert [y["year"] for y in body_cur["available_years"]] == [cur_yr, prev_yr, cur_yr - 2]
    assert agent.ephemeral_calls == []

    # 2. Finished historical year serves directly from cache (0 agent calls)
    res_prev = client.get(f"/api/year-review?year={prev_yr}", headers=HEADERS)
    assert res_prev.status_code == 200
    body_prev = res_prev.json()
    assert body_prev["status"] == "ready"
    assert body_prev["year"] == prev_yr
    assert body_prev["cached"] is True
    assert body_prev["data"]["kpis"]["total_run_km"] == 2140.0
    assert agent.ephemeral_calls == []


def test_unfinished_year_auto_syncs_incrementally_and_split_refresh_modes_work():
    today = date.today()
    cur_yr = today.year
    prev_yr = cur_yr - 1

    app, store, agent = build_test_app()
    store.users["cyrille_visser"] = {"firstname": "Cyrille", "lastname": "Visser", "email": EMAIL}
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}

    def populate(call: dict) -> None:
        args = call["quick_action"]["args"]
        yr = int(args["year"])
        store.year_reviews[("cyrille_visser", yr)] = _sample_year_review_doc(
            year=yr,
            is_complete=yr < cur_yr,
            last_computed_date=today.isoformat() if yr == cur_yr else f"{yr}-12-31",
        )

    agent.on_ephemeral_action = populate
    client = TestClient(app)

    # 1. Cold current year triggers incremental year-review quick action
    cold = client.get("/api/year-review", headers=HEADERS)
    assert cold.status_code == 200
    assert cold.json()["status"] == "ready"
    assert cold.json()["cached"] is False
    assert agent.ephemeral_calls[-1]["quick_action"] == {
        "skill": "year-review",
        "args": {"year": cur_yr, "force_full": False},
    }

    # 2. Yesterday's last_computed_date on unfinished current year triggers auto incremental sync
    yesterday = (today - timedelta(days=1)).isoformat()
    store.year_reviews[("cyrille_visser", cur_yr)] = _sample_year_review_doc(
        year=cur_yr, is_complete=False, last_computed_date=yesterday
    )
    inc = client.get("/api/year-review", headers=HEADERS)
    assert inc.status_code == 200
    assert inc.json()["cached"] is False
    assert len(agent.ephemeral_calls) == 2
    assert agent.ephemeral_calls[-1]["quick_action"] == {
        "skill": "year-review",
        "args": {"year": cur_yr, "force_full": False},
    }

    # 3. Manual POST /api/year-review/refresh defaults to incremental (force_full=False)
    ref_inc = client.post(f"/api/year-review/refresh?year={cur_yr}", headers=HEADERS)
    assert ref_inc.status_code == 200
    assert ref_inc.json()["cached"] is False
    assert len(agent.ephemeral_calls) == 3
    assert agent.ephemeral_calls[-1]["quick_action"] == {
        "skill": "year-review",
        "args": {"year": cur_yr, "force_full": False},
    }

    # 4. Manual POST /api/year-review/refresh?year=YYYY&mode=full triggers full re-pull (force_full=True)
    ref_full = client.post(f"/api/year-review/refresh?year={prev_yr}&mode=full", headers=HEADERS)
    assert ref_full.status_code == 200
    assert ref_full.json()["cached"] is False
    assert len(agent.ephemeral_calls) == 4
    assert agent.ephemeral_calls[-1]["quick_action"] == {
        "skill": "year-review",
        "args": {"year": prev_yr, "force_full": True},
    }

    # 5. Outdated schema version (v4) triggers automatic recomputation to v5
    store.year_reviews[("cyrille_visser", cur_yr)] = _sample_year_review_doc(year=cur_yr, version=4)
    upgraded = client.get("/api/year-review", headers=HEADERS)
    assert upgraded.status_code == 200
    assert upgraded.json()["cached"] is False
    assert upgraded.json()["data"]["version"] == 5
    assert len(agent.ephemeral_calls) == 5

    # 6. Validation errors on invalid mode or future year
    assert client.post("/api/year-review/refresh?mode=invalid", headers=HEADERS).status_code == 400
    assert client.get(f"/api/year-review?year={cur_yr + 1}", headers=HEADERS).status_code == 400


def test_year_review_handles_no_profile_tp_not_connected_and_empty_states():
    today = date.today()
    app, store, agent = build_test_app()
    client = TestClient(app)

    # No profile
    res_none = client.get("/api/year-review", headers=HEADERS)
    assert res_none.status_code == 200
    assert res_none.json()["status"] == "no_profile"

    # Profile exists, TP not connected, no cache
    store.users["cyrille_visser"] = {"firstname": "Cyrille", "lastname": "Visser", "email": EMAIL}
    res_tp = client.get("/api/year-review", headers=HEADERS)
    assert res_tp.status_code == 200
    assert res_tp.json()["status"] == "tp_not_connected"

    # Empty cached review (0 workouts) computed today
    store.creds["cyrille_visser"] = {"tp_name": "Cyrille Visser", "updated_at": "2026-11-15T08:00:00Z"}
    store.year_reviews[("cyrille_visser", today.year)] = _sample_year_review_doc(
        year=today.year, is_complete=False, last_computed_date=today.isoformat(), total_workouts=0
    )
    res_empty = client.get("/api/year-review", headers=HEADERS)
    assert res_empty.status_code == 200
    assert res_empty.json()["status"] == "empty"
    assert agent.ephemeral_calls == []
