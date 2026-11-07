"""Behavioural test for the trend analysis feature (`fetch_trend_data`)."""

import asyncio
import json

from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data
from running_coach.features.trend_analysis.helpers.goal_progress import implied_time_s
from running_coach.features.trend_analysis.helpers.load_capacity import format_levels_table, format_outlook
from running_coach.features.trend_analysis.helpers.pacing import format_pacing_details, slope_s_per_pct_lthr


def test_trend_analysis_gap_fills_flags_rate_limited_runs_and_builds_web_payload(runner):
    ctx = runner.ctx()
    out = asyncio.run(fetch_trend_data(ctx, weeks=6))

    assert "## Trend data: 2026-09-14 to 2026-10-27 (6 weeks)" in out
    assert "added by gap-fill now" in out
    assert "### Weekly rows" in out
    assert "### Load capacity" in out
    # Long runs: history facts only; the coach reasons the distance (no computed target or floor).
    assert "Long-run history (longest run of each of the last " in out
    assert "no computed long-run target" in out and "Long-run target" not in out
    assert "### Pacing" in out
    assert "### Training patterns" in out
    assert "Felt strong and controlled" in out
    assert "### Goal context" in out
    assert "- Current block (upcoming block, not started yet): Sub-43 10K, race 2027-02-14" in out
    assert "- North star: Sub-3:15 Marathon, race 2028-04-23" in out
    # The goal-plan table is in the coach instruction; the trend output references it once.
    assert "see GOAL PLAN in your instructions" in out and "| Sub goal | Block | Status |" not in out

    # Facts only in the coach text: no coded verdicts (the web payload keeps its badges).
    for verdict in ("room to go faster", "too hard", "on target", "| Proven", "proven ", "within reach",
                    "untested", "INSUFFICIENT", "-> confirmed", "-> unconfirmed", "🟢", "🟡", "🔴"):
        assert verdict not in out, verdict
    assert "weeks at or above (longest streak " in out
    assert "| Band | Sessions (reps) | Target range | Pace hit | Median pace | Median HR |" in out
    assert "- LTHR check: TP LTHR 172 bpm; " in out

    # 26 weeks: the coach gets the last 8 weekly rows; the web payload keeps every week.
    ctx26 = runner.ctx()
    out26 = asyncio.run(fetch_trend_data(ctx26, weeks=26))
    for verdict in ("room to go faster", "proven ", "INSUFFICIENT", "🟢", "🟡", "🔴"):
        assert verdict not in out26, verdict
    assert "| Marker | First | Latest | Best | Change | Higher is better |" in out26
    assert "_Pace @ LT2 uses the TrainingPeaks LTHR; see the LTHR check line" in out26
    rows_section = out26.split("### Weekly rows", 1)[1].split("###", 1)[0]
    assert "(last 8 of 27 weeks" in rows_section
    assert sum(1 for line in rows_section.splitlines() if line.startswith("| 20")) == 8
    assert len(ctx26.state["trend_report_data"]["weeks"]) == 27
    comments = out26.split("### Athlete comments", 1)[1]
    assert "2026-09-01" not in comments and "2026-10-27" in comments   # older non-niggle comments dropped

    # Tables are rendered by the web UI from the payload, never spliced into the coach's text.
    assert ctx.state.get("trend_tables") is None
    report = json.loads(json.dumps(ctx.state.get("trend_report_data")))
    assert report["version"] == 1
    assert len(report["weeks"]) >= 6
    assert report["key_run_label"] == "tempo/threshold"
    progress26 = ctx26.state["trend_report_data"]["progress"]
    assert progress26 and all("verdict" in p and "arrow" in p for p in progress26)
    assert all("proven" in lv and "tolerated_share" in lv for lv in report["levels"])
    assert all("status" in t for t in report["outlook"]["targets"]) and "proven_km" in report["outlook"]

    goal = report["goal"]
    assert goal["training_goal"] == "Sub-43 10K" and goal["label"] == "10K"
    assert goal["race_date"] == "2027-02-14" and goal["goal_s"] == 43 * 60
    assert goal["ctl"]["target_peak"] and len(goal["ctl"]["range"]) == 2
    assert "long_run" not in goal                       # no computed long-run band in the payload
    # 10K block: 72% of the 100 km/week north-star peak, a linear reference path from the recent level to the peak week.
    vol = goal["volume"]
    assert vol["block_target_km"] == 72 and vol["ns_peak_km"] == 100 and "reachable" not in vol
    assert vol["first_week"] == "2026-11-16" and vol["peak_week"] == "2027-01-25"
    kms = [p["km"] for p in vol["plan"] if p["phase"] == "build"]
    assert kms == sorted(kms) and kms[-1] == 72 and kms[0] < 72
    assert vol["plan"][-1] == {"week": "2027-02-01", "km": 54, "phase": "taper"}
    # Every 4th build week is a recovery week at 80% of its path step (never the peak week).
    recovery = [(p["week"], p["km"]) for p in vol["plan"] if p["phase"] == "recovery"]
    assert [w for w, _ in recovery] == ["2026-12-07", "2027-01-04"]
    assert "- Weekly volume reference (10K block" in out and "72 km block target by 2027-01-25" in out
    assert "no % cap" in out and "%/week" not in out
    # Outlook: km gap to each target, never a build-week count derived from a fixed ramp.
    assert all("gap_km" in t and "build_weeks" not in t for t in report["outlook"]["targets"])
    assert "build weeks from current" not in out

    ns = report["north_star"]
    assert ns["training_goal"] == "Sub-3:15 Marathon" and ns["target_s"] == 195 * 60
    assert [m["training_goal"] for m in ns["milestones"]] == ["Sub-21 5K", "Sub-43 10K"]
    assert [m["status"] for m in ns["milestones"]] == ["done", "active"]
    assert all(m["target_equiv_s"] for m in ns["milestones"])

    assert report["paces"] and {"name", "pace"} <= set(report["paces"][0])
    assert all("implied_goal_s" in w and "implied_ns_s" in w for w in report["weeks"])
    # LT2 4:10/km -> 10K at threshold x 1.025 and marathon at threshold x 0.91.
    assert round(implied_time_s(250, "10K")) == 2439
    assert round(implied_time_s(250, "Marathon")) == 11592
    assert implied_time_s(None, "10K") is None

    # Rate-limiting an otherwise valid 12.5 km run prevents it from being recorded and flags its week.
    runner.training_records.clear()
    runner.rate_limited_workout_ids.add("w137")
    flagged = asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))
    assert "w137" not in runner.training_records
    assert "unrecorded)" in flagged


def test_trend_text_formatters_state_facts_without_verdicts():
    levels = [{"level": 50, "weeks": 4, "streak": 2, "niggle_weeks": 1, "tolerated_share": 0.5,
               "hrv_delta_pct": -3.0, "rhr_delta": 1.0, "rpe": 5.5, "proven": False}]
    table = format_levels_table(levels)
    assert "| Level | Weeks | Longest streak | Niggle weeks | HRV Δ | RHR Δ | RPE |" in table
    assert "| >= 50 km | 4 | 2 | 1 | -3% | +1 | 5.5 |" in table
    outlook = {"proven_km": None, "max_km": 81.0, "current_km": 73.5,
               "targets": [{"target": 80, "status": "run, not proven", "gap_km": 6.5, "weeks_at": 2, "streak": 1}]}
    text = format_outlook(outlook, None, 0)
    assert "- 80 km/week: 2 weeks at or above (longest streak 1), +6.5 km/week above current" in text
    assert "highest week 81 km" in text and "proven" not in text and "run, not" not in text

    model = {"mx": 150.0, "my": 3.3, "slope": 0.02, "hr_min": 135.0, "hr_max": 165.0, "n": 40}
    pacing = {"runs": 12, "model": model, "slope_s_per_pct": slope_s_per_pct_lthr(model, 172.0), "easy": None,
              "discipline": None,
              "lthr_check": {"lthr": 172.0, "best_hr": 168.0, "best_pct": 168 / 172, "duration_s": 32 * 60,
                             "date": "2026-10-12", "title": "Tempo"},
              "threshold": {"observed_speed": 1000 / 248, "tp_speed": 1000 / 252, "diff_pct": 252 / 248 - 1,
                            "minutes": 46, "latest": "2026-10-20"}}
    details = format_pacing_details(pacing)
    assert "- LTHR check: TP LTHR 172 bpm; best 20+ min effort 168 bpm (97.7%), 32 min, 2026-10-12 'Tempo'" in details
    assert "fitted HR range 135-165 bpm; ≈ -3.1 s/km per +1% LTHR" in details
    assert "vs TP setting 4:12/km (pace diff -1.6%)" in details
    for verdict in ("confirmed", "agrees", "too fast", "too slow", "time trial"):
        assert verdict not in details, verdict
