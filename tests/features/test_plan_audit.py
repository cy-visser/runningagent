"""Behavioural test for the plan audit feature (`fetch_plan_audit_data`)."""

import asyncio
from datetime import date, timedelta
import json
import re

from running_coach.features.plan_audit.fetch_plan_audit_data_tool import (
    fetch_plan_audit_data,
)


def test_plan_audit_surfaces_goal_context_long_run_facts_and_web_payload(runner):
    # Add a Rest Day placeholder note (must be skipped) alongside real notes.
    runner.notes.append({"id": "n_rest", "date": "2026-11-16", "title": "Rest Day", "description": ""})
    ctx = runner.ctx()
    out = asyncio.run(fetch_plan_audit_data(ctx, weeks_forward=4, weeks_back=1))

    assert "**Audit Context:**" in out
    assert "transition week, outside 10K block" in out
    # Long run & weekly volume: measured facts only (12-week history, peak, streak, recent active mean,
    # week-over-week vs prior, longest runs); no synthetic volume path, block target, floor, cap, or flag.
    assert "12 wk to 10K" in out and "LR 14 km (" in out
    assert "- Last 12 complete weeks (oldest first): weekly km `" in out
    assert "peak " in out and "-wk streak >= 50 km" in out and "recent 4-wk active mean " in out
    assert "- Longest runs (last 6 complete weeks, oldest first): `" in out and "12-wk max " in out
    for computed in (
        "north-star floor",
        "Long-run rule",
        "cap 1",
        "target 24",
        "below target",
        "Volume reference",
        "block target",
        "vs path",
        "path ",
    ):
        assert computed not in out, computed
    assert "Work trip to Berlin" in out
    assert "Rest Day" not in out
    # Single-sport-per-day sessions omit 10-digit [workout_id]s (stage_workout_changes resolves by date + sport).
    session_lines = [ln for ln in out.splitlines() if ln.startswith("  Sessions: ")]
    assert session_lines and not any(re.search(r"\[w_\w+\]", ln) for ln in session_lines)

    # Planned weeks report measured facts only (km + vs prior), never a coded ramp verdict or target path.
    assert "44.5 km (" in out and "vs prior" in out
    header_lines = [ln for ln in out.splitlines() if ln.startswith("* **")]
    assert header_lines and not any("⚠" in ln or "10%" in ln or "%/week" in ln or "path" in ln for ln in header_lines)

    report = json.loads(json.dumps(ctx.state.get("audit_report_data")))
    assert report["version"] == 1
    assert len(report["weeks"]) >= 4
    assert "volume_reference" not in report
    long_runs = [w["long_run"] for w in report["weeks"] if w.get("long_run")]
    assert long_runs and all("⚠" not in lr and "target" not in lr for lr in long_runs)
    assert all("vs_prior_pct" in w and "volume" not in w for w in report["weeks"])

    # Late in the block: nothing planned is reported as a fact without a synthetic target path.
    late = asyncio.run(fetch_plan_audit_data(runner.ctx(), start_date="2027-01-25", end_date="2027-02-07"))
    assert "(2 wk to 10K): 0.0 km (no runs planned)" in late
    assert "(1 wk to 10K): 0.0 km (no runs planned)" in late


def test_plan_audit_caches_12_week_volume_history_in_firestore_for_28_days(runner):
    # 1. Cold cache: pulls 12-week history from TrainingPeaks and stores weekly totals + fetched_at in Firestore.
    asyncio.run(fetch_plan_audit_data(runner.ctx(), start_date="2026-11-16", end_date="2026-12-13"))
    cached = runner.volume_history_cache.get("cyrille_visser")
    assert cached and cached.get("fetched_at") and len(cached.get("weeks") or []) == 12
    first_ts = cached["fetched_at"]
    workout_ranges_cold = [
        (kw["start_date"][:10], kw["end_date"][:10])
        for name, kw in runner.tp_calls
        if name == "tp_get_workouts"
    ]
    assert len(workout_ranges_cold) == 2  # audited window + 12-week baseline fetch

    # 2. Within 28 days (e.g. +20 days): Firestore cache hit -> zero 12-week history tp_get_workouts call.
    runner.tp_calls.clear()
    runner.now = runner.now + timedelta(days=20)
    warm_out = asyncio.run(fetch_plan_audit_data(runner.ctx(), start_date="2026-11-16", end_date="2026-12-13"))
    assert "- Last 12 complete weeks (oldest first): weekly km `" in warm_out
    workout_ranges_warm = [
        (kw["start_date"][:10], kw["end_date"][:10])
        for name, kw in runner.tp_calls
        if name == "tp_get_workouts"
    ]
    assert workout_ranges_warm == [("2026-11-09", "2026-12-13")]
    assert runner.volume_history_cache["cyrille_visser"]["fetched_at"] == first_ts

    # 3. Older than 28 days (e.g. +29 days total): cache expired -> repulls from TrainingPeaks and updates timestamp.
    runner.tp_calls.clear()
    runner.now = runner.now + timedelta(days=9)
    stale_out = asyncio.run(fetch_plan_audit_data(runner.ctx(), start_date="2026-12-07", end_date="2026-12-27"))
    assert "- Last 12 complete weeks (oldest first): weekly km `" in stale_out
    workout_ranges_stale = [
        (kw["start_date"][:10], kw["end_date"][:10])
        for name, kw in runner.tp_calls
        if name == "tp_get_workouts"
    ]
    assert len(workout_ranges_stale) == 2
    assert runner.volume_history_cache["cyrille_visser"]["fetched_at"] > first_ts


def _span_days(kw: dict) -> int:
    return (date.fromisoformat(kw["end_date"][:10]) - date.fromisoformat(kw["start_date"][:10])).days


def test_plan_audit_over_90_days_is_chunked_and_populated(runner):
    # Regression: "audit from today until 7 Feb 2027" (> 90 days) came back as an empty schedule because
    # TrainingPeaks rejects list ranges > 90 days and the error was coerced to [].
    # Also verify same-day same-sport planned sessions include [workout_id] + @HH:MM for disambiguation.
    runner.workouts.extend([
        {
            "id": "w_far_am", "date": "2027-02-03", "start_time": "2027-02-03T07:30:00", "title": "Far Tempo Run",
            "sport": "Run", "type": "planned", "distance_planned_km": 11.0, "duration_planned": 0.9,
            "tss_planned": 70.0,
        },
        {
            "id": "w_far_pm", "date": "2027-02-03", "start_time": "2027-02-03T18:00:00", "title": "Shakeout Double",
            "sport": "Run", "type": "planned", "distance_planned_km": 5.0, "duration_planned": 0.45,
            "tss_planned": 28.0,
        },
    ])
    runner.notes.append({"id": "n_far", "date": "2027-02-01", "title": "Taper starts", "description": ""})
    ctx = runner.ctx()
    out = asyncio.run(fetch_plan_audit_data(ctx, start_date="2026-10-27", end_date="2027-02-07"))

    list_calls = [kw for name, kw in runner.tp_calls if name in ("tp_get_workouts", "tp_list_notes")]
    assert list_calls and all(_span_days(kw) <= 90 for kw in list_calls)
    assert "Run@07:30 'Far Tempo Run' 11km TSS 70 [w_far_am]" in out
    assert "Run@18:00 'Shakeout Double' 5km TSS 28 [w_far_pm]" in out
    assert "Taper starts" in out
    assert "Threshold 2 x 15'" in out           # planned sessions near the start of the window too
    assert "unavailable" not in out.lower()
    report = ctx.state.get("audit_report_data")
    assert report and len(report["weeks"]) == 15


def test_plan_audit_reports_tp_failure_instead_of_empty_schedule(runner):
    runner.failing_tools.add("tp_get_workouts")
    ctx = runner.ctx()
    out = asyncio.run(fetch_plan_audit_data(ctx, weeks_forward=4, weeks_back=1))

    assert out.startswith("Error:")
    assert "TrainingPeaks" in out and "empty" in out
    assert "no runs planned" not in out
    assert "audit_report_data" not in ctx.state
