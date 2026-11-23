"""Behavioural test for the check-in report feature (`fetch_checkin_data`)."""

import asyncio
import json

from running_coach.features.check_in_report.fetch_checkin_data_tool import fetch_checkin_data
from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data


def test_check_in_report_populates_sections_tables_and_web_payload(runner):
    # Populate the training log via trend gap-fill so LT1/LT2 paces and start positions exist.
    asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))

    ctx = runner.ctx()
    out = asyncio.run(fetch_checkin_data(ctx))

    assert "### Weekly Check-In Training & Physiological Report" in out
    assert "**1. Fitness PMC Trends, Goal Race Projection & Trajectory" in out
    assert "**3. Weekly Totals (completed, pre-computed; do not recompute):**" in out
    assert "### North Star Progress" in out
    assert "Slight calf tightness" in out
    # The goal-plan table is in the coach instruction; the check-in references it instead of repeating it.
    assert "see GOAL PLAN in your instructions" in out
    assert "| Sub goal | Block | Status |" not in out
    assert "north-star equivalent" in out
    assert "█" not in out

    # Metrics are rendered by the web app from the payload; nothing is spliced into the coach's text.
    assert ctx.state.get("checkin_tables") is None

    report = json.loads(json.dumps(ctx.state.get("checkin_report_data")))
    assert report["version"] == 1
    assert report["ctl"]["current"] > 0
    assert report["projection"]["goal_label"] == "10K"
    drivers = report["projection"]["drivers"]
    assert [d["driver"] for d in drivers][-2:] == ["Load", "Health"]
    assert all({"driver", "evidence", "implied"} == set(d) for d in drivers)
    assert len(report["weeks"]) >= 2

    # The coach's text is facts only: no coded verdicts, tiers or badges (the coach draws the conclusions).
    for verdict in ("🟢", "🟡", "🔴", "⚪", "✅", "⚠️", "safe (", "aggressive", "high risk", "Confidence:",
                    "Readiness", "-> weak", "-> moderate", "-> strong", "race-day target",
                    "hold fitness, shed fatigue"):
        assert verdict not in out, verdict
    if report["ctl"].get("phase") == "build":
        assert "required CTL build" in out
    assert "Evidence:" in out
    assert "signal" in out.split("Evidence:", 1)[1].split("|", 1)[0]

    # The web payload is unchanged: drivers keep their tiers and readiness badge for the UI.
    by_name = {d["driver"]: d for d in drivers}
    assert "readiness" in by_name["Health"]["implied"]
    assert "->" in by_name["Durability"]["evidence"]
    assert report["projection"]["confidence"] in ("Low", "Medium", "High")
    assert report["projection"]["readiness"] in ("🟢", "🟡", "🔴", "⚪")


def test_check_in_report_includes_pace_matched_running_dynamics_facts_only(runner):
    # Populate training records via trend gap-fill, then attach running dynamics to the recent run laps.
    asyncio.run(fetch_trend_data(runner.ctx(), weeks=8))
    for idx, rec in enumerate(sorted(runner.training_records.values(), key=lambda r: r.get("date") or "")):
        if str(rec.get("sport") or "").lower() != "run" or not rec.get("laps"):
            continue
        improving = idx >= len(runner.training_records) // 2
        for lap in rec["laps"]:
            lap["cadence"] = 172.0 if improving else 170.0
            lap["gct_ms"] = 250.0 if improving else 260.0
            lap["stride_m"] = 1.12
            lap["vert_osc_cm"] = 9.3 if improving else 9.9
            lap["vert_ratio_pct"] = round(lap["vert_osc_cm"] / lap["stride_m"], 2)
        rec["dynamics_version"] = 1
        rec["late_drift"] = {
            "scope": "session",
            "speed_delta_pct": -1.0,
            "gct_delta_ms": 15.0 if idx == len(runner.training_records) - 1 else 2.0,
            "cadence_delta": -4.0 if idx == len(runner.training_records) - 1 else 0.0,
            "stride_delta_pct": -2.0,
            "vr_delta_pp": 0.8 if idx == len(runner.training_records) - 1 else 0.1,
            "fatigue_flag": idx == len(runner.training_records) - 1,
        }

    ctx = runner.ctx()
    out = asyncio.run(fetch_checkin_data(ctx))
    assert "**Running Dynamics (pace-matched 4-wk vs prior 4-wk & 14d late-run drift):**" in out
    assert "Late-run mechanical drift (last 14d):" in out
    for verdict in ("🟢", "🟡", "🔴", "⚪", "✅", "⚠️"):
        assert verdict not in out, verdict

    dyn = ctx.state["checkin_report_data"]["dynamics"]
    assert dyn is not None
    assert dyn["gct_ms"] is not None
    assert dyn["late_fade"]["checked"] >= 1

