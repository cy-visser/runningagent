"""Behavioural test for the schedule audit feature (`fetch_schedule_audit_data`)."""

import asyncio
import json

from running_coach.features.schedule_audit.fetch_schedule_audit_data_tool import (
    fetch_schedule_audit_data,
)
from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data


def test_schedule_audit_surfaces_goal_context_long_run_facts_and_web_payload(runner):
    ctx = runner.ctx()
    out = asyncio.run(fetch_schedule_audit_data(ctx, weeks_forward=4, weeks_back=1))

    assert "**Goal Plan Context**" in out
    assert "London Marathon 2028" in out
    assert "transition week (outside the 10K block)" in out
    # Long run: facts only (distance, duration, share of the week, block position) and the recent
    # history; the coach reasons the distance. No computed target, floor, cap or flag.
    assert "🏃 Long run: 14 km (" in out and "% of the week's running km) | 12 wk to 10K" in out
    assert "- Long-run history (longest completed run of each of the last 6 complete weeks" in out
    assert "- Long run: no computed target." in out
    for computed in ("north-star floor", "Long-run rule", "cap 1", "target 24", "below target"):
        assert computed not in out
    assert "Work trip to Berlin" in out

    # Weekly volume: 10K block target = 72% of the 100 km/week north-star peak; completed and
    # transition weeks have no path; planned weeks report facts only (vs prior week, vs path), never a
    # coded ramp verdict.
    assert "- Weekly-volume reference (10K block): block target 72 km/week (72% of the 100 km/week" in out
    assert "- Weekly ramp: no coded limit." in out
    assert "- Recent weekly running km (last 6 complete weeks, oldest first): " in out
    assert "📈 Volume: 44.5 km (" in out and "vs prior week" in out
    assert "| path 55 km (build, 12 wk to 10K; block target 72 km by 2027-01-25), -19% vs path" in out
    volume_lines = [ln for ln in out.splitlines() if "📈 Volume" in ln or "Weekly-volume reference" in ln]
    assert volume_lines and not any("⚠" in ln or "10%" in ln or "%/week" in ln for ln in volume_lines)

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
    late = asyncio.run(fetch_schedule_audit_data(runner.ctx(), start_date="2027-01-25", end_date="2027-02-07"))
    assert "path 72 km (build, 2 wk to 10K" in late
    assert "path 54 km (taper, 1 wk to 10K; 75% of the 72 km block target), no runs planned" in late
    recovery = asyncio.run(fetch_schedule_audit_data(runner.ctx(), start_date="2026-12-07", end_date="2026-12-13"))
    assert "(recovery week, 9 wk to 10K; 80% of this week's" in recovery

    # Same per-week targets as the trend report (one shared rule and baseline).
    trend_ctx = runner.ctx()
    asyncio.run(fetch_trend_data(trend_ctx, weeks=6))
    trend_plan = {p["week"]: p["km"] for p in trend_ctx.state["trend_report_data"]["goal"]["volume"]["plan"]}
    audit_targets = {wk: v["target_km"] for wk, v in by_week.items() if v}
    assert audit_targets and all(trend_plan[wk] == km for wk, km in audit_targets.items())
