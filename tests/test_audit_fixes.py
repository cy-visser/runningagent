"""Regression tests for the audit remediation (bugs #1-#15, skill toolset, caching, secrets)."""

import asyncio
import json
import os
import shutil
from datetime import date

import pytest

import running_coach.agent as agent
import running_coach.services.secrets as secrets
import running_coach.services.tp_mcp as tp_mcp
import running_coach.steps as steps
import running_coach.tools as tools
from running_coach.utils import RUNNER_ID_STATE_KEY, format_profile_summary
from running_coach.utils.classification import is_quality_title
from running_coach.utils.paths import PACKAGE_DIR
from running_coach.utils.weekly import build_week_buckets
from running_coach.utils.workouts import format_workout_analysis

PROFILE = {"firstname": "Cyrille", "lastname": "Visser", "timeline": "2099-11-01",
           "location": "Utrecht", "training_goal": "Sub-3:30 Marathon", "age": "41"}


class FakeContext:
    def __init__(self, state=None):
        self.state: dict = dict(state or {})
        self.route = None


def _route(ctx):
    asyncio.run(agent.profile_router._func(ctx))
    return ctx.route


# ---------------------------------------------------------------- classification
class TestQualityClassification:
    @pytest.mark.parametrize("title", ["VO2max 5x3min", "Tempo 20'", "6 x 400m", "Hill repeats", "Push the pace"])
    def test_quality_titles(self, title):
        assert is_quality_title(title)

    @pytest.mark.parametrize("title", ["Plyo jumps", "Recovery run in compression socks", "Easy run"])
    def test_substring_false_positives_are_easy(self, title):
        assert not is_quality_title(title)


# ---------------------------------------------------------------- weekly buckets
class TestWeekBuckets:
    def test_buckets_start_on_monday_and_include_partial_first_week(self):
        # 2026-09-17 is a Thursday; its Monday is 2026-09-14.
        weeks = build_week_buckets(
            [{"date": "2026-09-18", "sport": "Run", "title": "Easy", "distance_planned_km": 10}],
            date(2026, 9, 17), date(2026, 9, 27),
        )
        first = next(iter(weeks.values()))
        assert first["start_date"] == date(2026, 9, 14)
        assert first["start_date"].weekday() == 0
        assert first["total_distance_km"] == 10

    def test_workouts_outside_window_are_ignored(self):
        weeks = build_week_buckets(
            [{"date": "2026-09-15", "sport": "Run", "title": "Easy", "distance_planned_km": 8}],
            date(2026, 9, 17), date(2026, 9, 20),
        )
        assert sum(w["total_distance_km"] for w in weeks.values()) == 0


# ---------------------------------------------------------------- create_workout
@pytest.fixture
def tp_calls(monkeypatch):
    calls = {"runs": [], "workouts": []}

    async def fake_fetch(tool_context, start, end):
        return calls["workouts"]

    async def fake_run(tool_context, tool_name, **node_input):
        calls["runs"].append((tool_name, node_input))
        return {"id": "new-1"}

    monkeypatch.setattr(tools, "_fetch_workouts", fake_fetch)
    monkeypatch.setattr(tools, "_run_tp_tool", fake_run)
    return calls


class TestCreateWorkout:
    def test_no_same_sport_workout_creates(self, tp_calls):
        tp_calls["workouts"] = [{"id": "r1", "sport": "Run", "title": "Easy", "type": "planned"}]
        out = json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", sport="Strength", title="Core")))
        assert out["action"] == "created"
        assert tp_calls["runs"][0][0] == "tp_create_workout"

    def test_single_same_sport_workout_is_updated(self, tp_calls):
        tp_calls["workouts"] = [{"id": "r1", "sport": "Run", "title": "Easy", "type": "planned"}]
        out = json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", title="Tempo")))
        assert out["action"] == "updated"
        assert tp_calls["runs"][0][1]["workout_id"] == "r1"

    def test_ambiguous_same_sport_returns_candidates(self, tp_calls):
        tp_calls["workouts"] = [
            {"id": "r1", "sport": "Run", "title": "AM", "type": "planned"},
            {"id": "r2", "sport": "Run", "title": "PM", "type": "planned"},
        ]
        out = json.loads(asyncio.run(tools.create_workout(None, "2026-09-20")))
        assert out["action"] == "needs_workout_id"
        assert {c["workout_id"] for c in out["candidates"]} == {"r1", "r2"}
        assert tp_calls["runs"] == []

    def test_create_flag_always_creates(self, tp_calls):
        tp_calls["workouts"] = [{"id": "r1", "sport": "Run", "title": "Easy", "type": "planned"}]
        out = json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", create=True)))
        assert out["action"] == "created"

    def test_update_error_message_uses_gerund(self, monkeypatch):
        async def fake_run(tool_context, tool_name, **node_input):
            return {"isError": True, "message": "nope"}

        monkeypatch.setattr(tools, "_run_tp_tool", fake_run)
        out = asyncio.run(tools.create_workout(None, "2026-09-20", workout_id="r1"))
        assert out == "Error updating workout: nope"


# ---------------------------------------------------------------- workout formatting
class TestWorkoutFormatting:
    def test_bike_laps_use_rpm_and_pw_hr(self):
        out = format_workout_analysis(
            {"lapData": [{"AverageCadence": 90, "PowerPulseDecoupling": 2.1, "PacePulseDecoupling": 5.0}]},
            title="Endurance Ride", sport="Bike",
        )
        assert "Cad 90rpm" in out
        assert "Pw:Hr 2.1%" in out
        assert "Pa:Hr" not in out

    def test_run_laps_use_spm_and_pa_hr(self):
        out = format_workout_analysis(
            {"lapData": [{"AverageCadence": 176, "PacePulseDecoupling": 3.0}]}, title="Easy", sport="Run",
        )
        assert "Cad 176spm" in out
        assert "Pa:Hr 3.0%" in out

    def test_raw_pace_is_not_labelled_ngp(self):
        out = format_workout_analysis({"totals": {"Pace": {"value": 300, "unit": "s/km"}}}, sport="Run")
        assert "Avg Pace" in out
        assert "NGP" not in out


# ---------------------------------------------------------------- skill toolset
class TestCompactSkillToolset:
    def test_only_load_skill_is_exposed(self):
        tool_list = asyncio.run(tools.skill_toolset.get_tools())
        assert [t.name for t in tool_list] == ["load_skill"]

    def test_prompt_lists_all_skills_without_script_tools(self):
        class FakeRequest:
            def __init__(self):
                self.instructions = []

            def append_instructions(self, items):
                self.instructions.extend(items)

        req = FakeRequest()
        asyncio.run(tools.skill_toolset.process_llm_request(tool_context=None, llm_request=req))
        prompt = "\n".join(req.instructions)
        for name in tools.SKILL_NAMES:
            assert name in prompt
        assert "run_skill_script" not in prompt
        assert "load_skill_resource" not in prompt


# ---------------------------------------------------------------- router
@pytest.fixture
def router_env(monkeypatch):
    store = {"cyrille_visser": dict(PROFILE)}

    async def fake_get_user_profile(user_id):
        return dict(store[user_id]) if user_id in store else None

    async def fake_coords(user_id, profile):
        return None

    monkeypatch.setattr(steps, "get_user_profile", fake_get_user_profile)
    monkeypatch.setattr(steps, "_ensure_cached_coordinates", fake_coords)
    return store


class TestRouterState:
    def test_reonboard_with_profile_in_state_seeds_prefill_and_saves(self, router_env, monkeypatch):
        saved = []

        async def fake_save(user_id, profile):
            saved.append((user_id, profile))

        async def no_geocode(*_):
            return None

        monkeypatch.setattr(steps, "save_user_profile", fake_save)
        monkeypatch.setattr(steps.asyncio, "to_thread", lambda *a, **k: no_geocode())
        # Profile already in session state (as after an earlier turn), temp data cleared by a prior onboarding.
        ctx = FakeContext({"user_profile": dict(PROFILE), "reonboard_requested": True, "temp_onboarding_data": None})
        assert _route(ctx) == agent.ROUTE_ONBOARDING
        assert ctx.state["temp_onboarding_data"]["firstname"] == "Cyrille"

        ctx.state["onboarding_answers"] = {"training_goal": "Sub-19:30 5K", "timeline": "2099-05-01"}
        assert asyncio.run(steps.create_profile_step(ctx)) is True
        assert saved[0][0] == "cyrille_visser"
        assert saved[0][1]["training_goal"] == "Sub-19:30 5K"

    def test_router_refreshes_stale_summary(self, router_env):
        ctx = FakeContext({"user_profile": dict(PROFILE), "user_profile_summary": "stale"})
        assert _route(ctx) == agent.ROUTE_COACHING
        assert ctx.state["user_profile_summary"] == format_profile_summary(PROFILE)
        assert ctx.state["expired_timeline_notice"] == ""

    def test_router_sets_expired_notice(self, router_env):
        ctx = FakeContext({"user_profile": {**PROFILE, "timeline": "2020-01-01"}})
        assert _route(ctx) == agent.ROUTE_COACHING
        assert ctx.state["expired_timeline_date"] == "2020-01-01"
        assert "2020-01-01" in ctx.state["expired_timeline_notice"]
        assert "request_new_goal" in ctx.state["expired_timeline_notice"]

    def test_known_runner_state_summary_set(self, router_env):
        ctx = FakeContext({RUNNER_ID_STATE_KEY: "cyrille_visser"})
        assert _route(ctx) == agent.ROUTE_COACHING
        assert "Sub-3:30 Marathon" in ctx.state["user_profile_summary"]

    def test_coaching_instruction_uses_state_placeholders(self):
        instruction = agent.coaching_agent.instruction
        assert "{user_profile_summary?}" in instruction
        assert "{expired_timeline_notice?}" in instruction
        assert "load the skill first" in instruction


# ---------------------------------------------------------------- tp_mcp cache
class TestTpToolCache:
    def test_two_lookups_fetch_tools_once(self, monkeypatch):
        calls = {"get_tools": 0}

        class FakeToolset:
            async def get_tools(self):
                calls["get_tools"] += 1
                return [type("T", (), {"name": n})() for n in ("tp_get_profile", "tp_get_workouts")]

        monkeypatch.setattr(tp_mcp, "_tp_toolset", FakeToolset())
        monkeypatch.setattr(tp_mcp, "_tp_tools_by_name", {})

        async def lookups():
            await tp_mcp.get_tp_tool("tp_get_profile")
            await tp_mcp.get_tp_tool("tp_get_workouts")

        asyncio.run(lookups())
        assert calls["get_tools"] == 1

    def test_error_clears_cache(self, monkeypatch):
        class BoomToolset:
            async def get_tools(self):
                raise RuntimeError("connection lost")

        cache = {"stale": object()}
        monkeypatch.setattr(tp_mcp, "_tp_toolset", BoomToolset())
        monkeypatch.setattr(tp_mcp, "_tp_tools_by_name", cache)
        with pytest.raises(RuntimeError):
            asyncio.run(tp_mcp.get_tp_tool("tp_get_profile"))
        assert cache == {}


# ---------------------------------------------------------------- secrets
class TestInjectProductionSecrets:
    def test_skips_secret_manager_when_cookie_is_set(self, monkeypatch):
        monkeypatch.setenv("TP_AUTH_COOKIE", "local")
        monkeypatch.setattr(secrets, "get_secret_name", lambda: pytest.fail("should not be called"))
        secrets.inject_production_secrets()
        assert os.environ["TP_AUTH_COOKIE"] == "local"

    def test_reads_secret_manager_when_cookie_missing(self, monkeypatch):
        from google.cloud import secretmanager

        monkeypatch.delenv("TP_AUTH_COOKIE", raising=False)
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
        requested = {}

        class FakeClient:
            def access_secret_version(self, request):
                requested.update(request)
                payload = type("P", (), {"data": b" secret-cookie \n"})()
                return type("R", (), {"payload": payload})()

        monkeypatch.setattr(secretmanager, "SecretManagerServiceClient", FakeClient)
        secrets.inject_production_secrets()
        assert os.environ["TP_AUTH_COOKIE"] == "secret-cookie"
        assert requested["name"].startswith("projects/")
        assert requested["name"].endswith("/versions/latest")


# ---------------------------------------------------------------- deploy packaging
def test_ae_ignore_excludes_env_and_cookie_files():
    with open(os.path.join(PACKAGE_DIR, ".ae_ignore")) as f:
        patterns = [line.strip() for line in f if line.strip()]
    ignore = shutil.ignore_patterns(*patterns)
    ignored = ignore(PACKAGE_DIR, [".env", ".env.prod", "tp.cookie", "agent.py", "tools.py"])
    assert {".env", ".env.prod", "tp.cookie"} <= ignored
    assert "agent.py" not in ignored


# ---------------------------------------------------------------- ramp tiers
@pytest.mark.parametrize("rate,badge", [(None, None), (3.5, "🟢"), (4.2, "🟡"), (6.0, "🔴")])
def test_ramp_status_tiers(rate, badge):
    from running_coach.utils.trajectory import ramp_status

    result = ramp_status(rate)
    assert (result is None) if badge is None else result.startswith(badge)


# ---------------------------------------------------------------- analyze_workout primary pick
class TestAnalyzeWorkoutPrimaryPick:
    def test_date_lookup_analyses_run_and_discloses_strength(self, monkeypatch):
        workouts = [
            {"id": "3681731889", "date": "2026-09-24", "start_time": "2026-09-24T07:26:05",
             "title": "Canova 8x1km", "type": "completed", "sport": "Run",
             "duration_actual": 1.17, "tss_actual": 101.83},
            {"id": "3937515897", "date": "2026-09-24", "start_time": "2026-09-24T17:36:12",
             "title": "General S&C Work", "type": "completed", "sport": "Strength",
             "duration_actual": 0.5, "tss_actual": 17.9},
        ]
        analysed = []

        async def fake_fetch(tool_context, start, end):
            return workouts

        async def fake_run(tool_context, tool_name, **node_input):
            if tool_name == "tp_analyze_workout":
                analysed.append(node_input["workout_id"])
                payload = {"workoutId": node_input["workout_id"], "startTimestamp": "2026-09-24T07:26:05",
                           "totals": {"TSS": 101.8}}
            else:
                payload = {"sport": "Run", "title": "Canova 8x1km"}
            return {"content": [{"text": json.dumps(payload)}]}

        class Ctx:
            state = {}

        monkeypatch.setattr(tools, "_fetch_workouts", fake_fetch)
        monkeypatch.setattr(tools, "_run_tp_tool", fake_run)
        out = asyncio.run(tools.analyze_workout(
            Ctx(), date_str="2026-09-24", include_weather=False, include_recovery=False,
        ))
        assert analysed == ["3681731889"]
        assert out.startswith("Other completed sessions on 2026-09-24")
        assert "id 3937515897" in out
        assert "Workout Analysis [3681731889]" in out


# ---------------------------------------------------------------- analyze_workout planned structure
_STRUCT_FX = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "structured_workouts.json").read_text())


def _run_analyze(monkeypatch, tmp_path, workout, meta, with_series=True):
    data_file = tmp_path / "workout.json"
    data_file.write_text(json.dumps({"data": workout["series"]}))
    called = []

    async def fake_run(tool_context, tool_name, **node_input):
        called.append(tool_name)
        if tool_name == "tp_analyze_workout":
            payload = {"workoutId": node_input["workout_id"], "startTimestamp": "2026-09-24T07:26:05",
                       "totals": {"Pa:Hr": {"value": 9.38, "unit": "%"}}, "lapData": workout["laps"]}
            if with_series:
                payload["data_file"] = str(data_file)
        elif tool_name == "tp_get_athlete_settings":
            payload = _STRUCT_FX["settings"]
        else:
            payload = meta
        return {"content": [{"text": json.dumps(payload)}]}

    class Ctx:
        state = {}

    monkeypatch.setattr(tools, "_run_tp_tool", fake_run)
    out = asyncio.run(tools.analyze_workout(
        Ctx(), workout_id="3681731889", include_weather=False, include_recovery=False,
    ))
    return out, called


class TestAnalyzeWorkoutStructure:
    def test_structured_session_uses_builder_steps(self, monkeypatch, tmp_path):
        fx = _STRUCT_FX["canova"]
        meta = {"sport": "Run", "title": "Canova 8x1km", "description": "8x1km @ MP-ish, 1' float",
                "structured_workout": fx["structured_workout"]}
        out, called = _run_analyze(monkeypatch, tmp_path, fx, meta)
        assert "tp_get_athlete_settings" in called
        assert "### Planned structure & execution" in out
        assert "Pa:Hr (15:42 →" in out
        assert "**Planned session notes:** 8x1km" in out
        assert "9.38" not in out

    def test_unstructured_session_skips_first_minutes(self, monkeypatch, tmp_path):
        fx = _STRUCT_FX["easy_run"]
        out, called = _run_analyze(monkeypatch, tmp_path, fx, {"sport": "Run", "title": "Easy 10k"})
        assert "tp_get_athlete_settings" not in called
        assert "### Planned structure & execution" not in out
        assert "Pa:Hr (5:00 →" in out

    def test_no_series_no_laps_falls_back_to_labelled_tp_value(self, monkeypatch, tmp_path):
        fx = {"series": [], "laps": []}
        out, _ = _run_analyze(monkeypatch, tmp_path, fx, {"sport": "Run", "title": "Easy"}, with_series=False)
        assert "whole session, incl. warm-up" in out
