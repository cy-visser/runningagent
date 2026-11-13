"""Behavioural test for the plan audit feature (`fetch_plan_audit_data`)."""

import asyncio
from datetime import date
import json
import re

from running_coach.features.plan_audit.fetch_plan_audit_data_tool import (
    fetch_plan_audit_data,
)
from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data


def test_plan_audit_surfaces_goal_context_long_run_facts_and_web_payload(runner):
    # Add a Rest Day placeholder note (must be skipped) alongside real notes.
    runner.notes.append({"id": "n_rest", "date": "2026-11-16", "title": "Rest Day", "description": ""})
    ctx = runner.ctx()
    out = asyncio.run(fetch_plan_audit_data(ctx, weeks_forward=4, weeks_back=1))

    assert "**Audit Context:**" in out
    assert "transition week, outside 10K block" in out
    # Long run: facts only (distance, duration, share of the week, block position) and the recent
    # history; the coach reasons the distance. No computed target, floor, cap or flag.
    assert "12 wk to 10K" in out and "LR 14 km (" in out
    assert "- Last 6 complete weeks (oldest first): weekly km `" in out and "| longest runs `" in out
    for computed in ("north-star floor", "Long-run rule", "cap 1", "target 24", "below target"):
        assert computed not in out
    assert "Work trip to Berlin" in out
    assert "Rest Day" not in out
    # Single-sport-per-day sessions omit 10-digit [workout_id]s (stage_workout_changes resolves by date + sport).
    session_lines = [ln for ln in out.splitlines() if ln.startswith("  Sessions: ")]
    assert session_lines and not any(re.search(r"\[w_\w+\]", ln) for ln in session_lines)

    # Weekly volume: 10K block target = 72% of the 100 km/week north-star peak; completed and
    # transition weeks have no path; planned weeks report facts only (vs prior, vs path), never a
    # coded ramp verdict.
    assert "- Volume reference (10K block): block target 72 km/week (72% of the 100 km/week" in out
    assert "44.5 km (" in out and "vs prior" in out
    assert "path 55 km, -19% vs path" in out
    header_lines = [ln for ln in out.splitlines() if ln.startswith("* **") or "Volume reference" in ln]
    assert header_lines and not any("⚠" in ln or "10%" in ln or "%/week" in ln for ln in header_lines)

    report = json.loads(json.dumps(ctx.state.get("audit_report_data")))
    assert report["version"] == 1
    assert len(report["weeks"]) >= 4
    long_runs = [w["long_run"] for w in report["weeks"] if w.get("long_run")]
    assert long_runs and all("⚠" not in lr and "target" not in lr for lr in long_runs)
    by_week = {w["week"]: w["volume"] for w in report["weeks"]}
    assert by_week["2026-10-26"] is None and by_week["2026-11-09"] is None
    assert by_week["2026-11-16"] == {"target_km": 55, "block_target_km": 72, "phase": "build",
                                     "vs_path_pct": -19.1}
    assert all("vs_prior_pct" in w for w in report["weeks"])
    # Caption facts: how the weekly km targets are derived (block of the first targeted week).
    assert report["volume_reference"] == {
        "goal": "Sub-43 10K", "goal_label": "10K", "ns_goal": "Sub-3:15 Marathon", "own_block": False,
        "block_target_km": 72, "ns_peak_km": 100, "start_km": 53.7, "peak_week": "2027-01-25",
        "recovery_every_weeks": 4,
    }

    # Late in the block: taper week at 75% of the block target; nothing planned is a fact, not a verdict.
    late = asyncio.run(fetch_plan_audit_data(runner.ctx(), start_date="2027-01-25", end_date="2027-02-07"))
    assert "(build, 2 wk to 10K): 0.0 km (path 72 km, no runs planned)" in late
    assert "(taper, 1 wk to 10K): 0.0 km (path 54 km [75% of 72 km], no runs planned)" in late
    recovery = asyncio.run(fetch_plan_audit_data(runner.ctx(), start_date="2026-12-07", end_date="2026-12-13"))
    assert "(recovery week, 9 wk to 10K):" in recovery and "[80% of " in recovery

    # Same per-week targets as the trend report (one shared rule and baseline).
    trend_ctx = runner.ctx()
    asyncio.run(fetch_trend_data(trend_ctx, weeks=6))
    trend_plan = {p["week"]: p["km"] for p in trend_ctx.state["trend_report_data"]["goal"]["volume"]["plan"]}
    audit_targets = {wk: v["target_km"] for wk, v in by_week.items() if v}
    assert audit_targets and all(trend_plan[wk] == km for wk, km in audit_targets.items())


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
