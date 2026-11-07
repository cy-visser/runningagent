"""Behavioural test for workout analysis (`analyze_workout` + `no_workout_reply`)."""

import asyncio
import json
from datetime import date

from google.adk.models.llm_request import LlmRequest
from google.genai import types

from running_coach.features.trend_analysis.fetch_trend_data_tool import fetch_trend_data
from running_coach.features.workout_analysis.analyze_workout_tool import analyze_workout
from running_coach.features.workout_analysis.helpers.web_report import workout_report_data
from running_coach.features.workout_analysis.no_workout_reply_callback import no_workout_reply


def test_workout_analysis_web_banner_payload_for_run_and_bike(runner):
    # By date: the day's key session (the 5K race) with its local start time and the other session.
    ctx = runner.ctx()
    out = asyncio.run(analyze_workout(ctx, date_str="2026-10-20"))
    report = json.loads(json.dumps(ctx.state["workout_report_data"]))
    assert report["version"] == 1 and report["workout_id"] == "w_race_5k"
    assert report["title"] == "Amsterdam 5K Race" and report["sport_family"] == "run"
    assert report["date"] == "2026-10-20" and report["start_time"] == "09:00"
    assert report["location"] == "Amsterdam"  # GPS start lies next to the profile's home
    assert [s["title"] for s in report["other_sessions"]] == ["Threshold 2 x 15'"]

    tiles = {t["key"]: t for t in report["tiles"]}
    assert [t["key"] for t in report["tiles"]][:4] == ["distance", "duration", "pace", "hr"]
    assert len(report["tiles"]) <= 6
    assert tiles["duration"]["value"] == "20:45"
    assert (tiles["pace"]["label"], tiles["pace"]["value"], tiles["pace"]["unit"]) == ("NGP", "4:57", "/km")
    assert (tiles["hr"]["value"], tiles["hr"]["sub"]) == ("146", "max 162")
    if "decoupling" in tiles:  # same windowed Pa:Hr the coach reads, never the whole-session TP value
        assert tiles["decoupling"]["label"] == "Pa:Hr"
        assert f"{tiles['decoupling']['value']}%" in out

    zones = report["hr_zones"]
    assert [z["label"] for z in zones] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    assert abs(sum(z["pct"] for z in zones) - 100.0) < 0.5
    assert report["weather"] == {"temp_c": 12.0, "feels_like_c": 11.0, "humidity": 70.0, "wind_kmh": 11.0}
    readiness = {r["key"]: r for r in report["readiness"]}
    assert set(readiness) == {"hrv", "rhr"}  # no sleep metric in the fake data
    assert readiness["hrv"]["unit"] == "ms" and readiness["hrv"]["direction"] in ("up", "down", "flat")
    assert readiness["rhr"]["date"] == "2026-10-20"

    # The coach's text is unchanged: the banner data lives only in session state.
    assert "workout_report_data" not in out and "hr_zones" not in out

    # Bike: power / IF tiles instead of pace; the run HR-zone group is not applied to a ride.
    bike_ctx = runner.ctx()
    asyncio.run(analyze_workout(bike_ctx, date_str="2026-10-22", sport="bike"))
    bike = bike_ctx.state["workout_report_data"]
    assert bike["sport_family"] == "bike" and bike["title"] == "Z2 Spin"
    bike_tiles = {t["key"]: t for t in bike["tiles"]}
    assert "pace" not in bike_tiles
    assert bike_tiles["distance"]["value"] == "30.0"
    assert (bike_tiles["tss"]["label"], bike_tiles["tss"]["value"]) == ("TSS", "45")
    assert bike_tiles["if"]["value"] == "0.85"
    assert bike["hr_zones"] is None


def test_workout_banner_elevation_profile_and_missing_data():
    series = [
        {"time": i * 10, "Distance": i * 0.05, "HeartRate": 140, "SmoothedAltitude": 10 + (i % 20)}
        for i in range(200)
    ]
    report = workout_report_data(
        {"totals": {"El. Gain": {"value": 86}, "El. Loss": {"value": "--"}}, "lapData": []},
        {"metrics": {}},
        profile={"location": "Amsterdam", "latitude": 52.37, "longitude": 4.89},
        sport="Run", title="Hill reps", workout_date=date(2026, 11, 4), local_start=None,
        series=series, alignment=None, hr_zones=[], weather=None, dated_metrics=None,
        start_position={"lat": 40.75, "lon": -73.95},  # New York: not the profile's home
        structured=False,
    )
    elevation = report["elevation"]
    assert elevation["gain_m"] == 86.0 and elevation["loss_m"] is None
    assert 10 <= len(elevation["profile"]) <= 60
    assert all(10 <= alt <= 29 for _, alt in elevation["profile"])
    assert report["location"] is None and report["start_time"] is None
    assert report["weather"] is None and report["readiness"] is None and report["hr_zones"] is None


def test_workout_analysis_saves_sub_goal_result_matches_gap_fill_and_short_circuits_no_workout(runner):
    ctx = runner.ctx()
    out = asyncio.run(analyze_workout(ctx, workout_id="w_race_5k"))

    assert "### Workout Analysis" in out
    assert "### Planned structure & execution" in out
    planned = out.split("### Planned structure & execution", 1)[1].split("\n### ", 1)[0]
    if "| Step |" in planned:   # laps aligned: facts-only delta column, no coded verdicts
        assert "Δ vs target" in planned and "| Check |" not in planned
        assert not any(v in planned for v in ("✓", "fast (", "slow (", "[key block]"))
    assert "**Planned session notes:**" in out
    assert "**Athlete feedback:** RPE 6/10" in out
    assert "**Environmental & Weather Context:**" in out
    assert "Result saved" in out
    assert len(runner.profile_updates) == 1
    saved_sub = ctx.state["user_profile"]["sub_goals"][0]["result"]
    assert saved_sub and saved_sub["workout_id"] == "w_race_5k"

    via_analysis = {k: v for k, v in runner.training_records["w_race_5k"].items() if k != "recorded_at"}
    runner.training_records.clear()
    asyncio.run(fetch_trend_data(runner.ctx(), weeks=6))
    via_gap_fill = {k: v for k, v in runner.training_records["w_race_5k"].items() if k != "recorded_at"}
    assert via_analysis == via_gap_fill

    # Date with no workout returns deterministic text that no_workout_reply short-circuits.
    no_w_msg = asyncio.run(analyze_workout(runner.ctx(), date_str="2026-10-28"))
    assert "No completed workout on 2026-10-28" in no_w_msg
    req = LlmRequest(contents=[types.Content(role="user", parts=[
        types.Part(function_response=types.FunctionResponse(name="analyze_workout", response={"result": no_w_msg}))
    ])])
    res = no_workout_reply(runner.ctx(), req)
    assert res is not None and res.content.parts[0].text == no_w_msg
