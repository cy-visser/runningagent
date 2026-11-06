"""Behavioural test for the trend analysis feature (`fetch_trend_data`)."""

import asyncio
import json

from running_coach.tools import fetch_trend_data


def test_trend_analysis_gap_fills_flags_rate_limited_runs_and_builds_web_payload(runner):
    ctx = runner.ctx()
    out = asyncio.run(fetch_trend_data(ctx, weeks=6))

    assert "## Trend data: 2026-09-14 to 2026-10-27 (6 weeks)" in out
    assert "added by gap-fill now" in out
    assert "### Weekly rows" in out
    assert "### Load capacity" in out
    assert "Long-run target for the upcoming Sub-43 10K block" in out
    assert "### Pacing" in out
    assert "### Training patterns" in out
    assert "Felt strong and controlled" in out

    assert ctx.state.get("trend_tables")
    report = json.loads(json.dumps(ctx.state.get("trend_report_data")))
    assert report["version"] == 1
    assert len(report["weeks"]) >= 6
    assert report["key_run_label"] == "tempo/threshold"

    # Rate-limiting an otherwise valid 12.5 km run prevents it from being recorded and flags its week.
    runner.training_records.clear()
    runner.rate_limited_workout_ids.add("w137")
    flagged = asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))
    assert "w137" not in runner.training_records
    assert "unrecorded)" in flagged
