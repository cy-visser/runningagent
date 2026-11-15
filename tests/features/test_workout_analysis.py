"""Behavioural test for workout analysis (`analyze_workout`, including its coded "no workout" reply)."""

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


def test_no_completed_workout_is_a_coded_reply_that_ends_the_turn(runner):
    ctx = runner.ctx()
    out = asyncio.run(analyze_workout(ctx, date_str="2026-10-25"))
    assert ctx.reply_text() == out and ctx.actions.skip_summarization is True  # no LLM retry on other dates


def test_structured_deduplication_non_race_goal_omission_and_indoor_weather_skip(runner):
    # 1. Sub-goal race day (2026-10-20) keeps the race result + north-star equivalent line, compact Repeated blocks,
    #    and human-readable block names (never internal B1/B2/B3 builder indices).
    race_out = asyncio.run(analyze_workout(runner.ctx(), date_str="2026-10-20"))
    assert "**Sub-goal race (Sub-21 5K):**" in race_out
    assert "**Repeated blocks:**" in race_out and "in target" in race_out
    for internal_id in ("| B1 ", "| B2 ", "| B3 ", "- B1 ", "- B2 ", "- B3 "):
        assert internal_id not in race_out

    # 2. Indoor trainer ride (no GPS file, 0m gain/loss) skips outdoor Open-Meteo weather and omits non-race Goal plan.
    bike_w = next(w for w in runner.workouts if w["date"] == "2026-10-22" and w["sport"] == "Bike")
    runner.analysis_overrides[bike_w["id"]] = {
        "lapData": [],
        "totals": {
            "Distance": {"value": 17.6, "unit": "km"},
            "Duration": {"value": 1800, "unit": "s"},
            "TSS": {"value": 16, "unit": ""},
            "NP": {"value": 126, "unit": "W"},
            "El. Gain": {"value": 0, "unit": "m"},
            "El. Loss": {"value": 0, "unit": "m"},
        },
        "startTimestamp": "2026-10-22T07:00:00",
        "data_file": None,
    }
    bike_ctx = runner.ctx()
    bike_out = asyncio.run(analyze_workout(bike_ctx, date_str="2026-10-22", sport="bike"))
    assert "Environmental & Weather Context" not in bike_out
    assert "**Goal plan:**" not in bike_out
    assert bike_ctx.state["workout_report_data"]["weather"] is None

    # 3. Structured workout planned_notes strips redundant auto-generated Warm-up/Main Set/Cool-down blocks, keeping cues/gear.
    from running_coach.features.workout_analysis.helpers.session_notes_and_feedback import planned_notes

    builder_desc = (
        "Warm-up:\n- 2.5 km easy aerobic jogging\n\n"
        "Main Set (Taper Threshold):\n- 3x 2.0 km @ 4:55/km\n- Cues: Crisp turnover, cadence 174-176 spm.\n\n"
        "Cool-down:\n- 2.0 km easy jog\n\n"
        "Gear: Saucony Endorphin Speed 5."
    )
    compact_notes = planned_notes({"description": builder_desc}, structured=True)
    assert "Crisp turnover" in compact_notes and "Saucony Endorphin Speed 5" in compact_notes
    assert "2.5 km easy aerobic jogging" not in compact_notes and "2.0 km easy jog" not in compact_notes

