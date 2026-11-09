"""Behavioural test for workout analysis (`analyze_workout` + `no_workout_reply`)."""

import asyncio
import json


from running_coach.features.workout_analysis.analyze_workout_tool import analyze_workout


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
