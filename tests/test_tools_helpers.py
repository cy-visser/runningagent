import asyncio
import json
from datetime import date

import pytest

from running_coach import tools
from running_coach.tools import _summarize_fitness
from running_coach.utils.race_readiness import ANALYSIS_SCHEMA_VERSION
from tests.test_metrics import mcp_envelope


class TestSummarizeFitness:
    def _fitness_payload(self):
        return mcp_envelope({"daily_data": [
            {"date": "2026-09-01", "ctl": 40.0, "atl": 45.0, "tsb": -5.0},
            {"date": "2026-09-15", "ctl": 50.0, "atl": 60.0, "tsb": -10.0},
        ]})

    def test_takes_first_and_last_values_in_date_order(self):
        result = _summarize_fitness(self._fitness_payload(), {}, date(2026, 9, 15))
        assert result["ctl_start"] == 40.0
        assert result["ctl_end"] == 50.0
        assert result["atl_end"] == 60.0
        assert result["tsb_end"] == -10.0


def _analysis(laps):
    return mcp_envelope({"totals": {"Pa:Hr": {"value": 4.0, "unit": "%"}}, "lapData": laps})


class TestLoadWorkoutSummaries:
    WORKOUTS = [
        {"id": 1, "date": "2026-09-10", "title": "Threshold 2x15", "distance_actual_km": 3.1},
        {"id": 2, "date": "2026-09-20", "title": "28km long", "distance_actual_km": 3.0},
    ]
    LAP = {"TotalTimerTime": 900, "TotalDistance": 3.1, "AveragePace": 290, "AverageHeartRate": 160}
    CACHED_LAPS = [{"distance_km": 3.1, "duration_s": 900, "speed_ms": 3.4, "hr": 160}]

    def _patch(self, monkeypatch, cache, analysed, fail_cache=False):
        async def fake_read(user_id, wid):
            if fail_cache:
                raise RuntimeError("firestore down")
            return cache.get(wid)

        async def fake_write(user_id, wid, summary):
            if fail_cache:
                raise RuntimeError("firestore down")
            cache[wid] = summary

        async def fake_tp(ctx, name, **kw):
            analysed.append(kw["workout_id"])
            return _analysis([self.LAP])

        monkeypatch.setattr(tools, "get_cached_workout_analysis", fake_read)
        monkeypatch.setattr(tools, "save_workout_analysis", fake_write)
        monkeypatch.setattr(tools, "_run_tp_tool", fake_tp)

    def test_analyses_misses_and_populates_cache(self, monkeypatch):
        cache, analysed = {}, []
        self._patch(monkeypatch, cache, analysed)
        out = asyncio.run(tools._load_workout_summaries(None, self.WORKOUTS, "user_x"))
        assert analysed == ["1", "2"]
        assert set(cache) == {"1", "2"}
        assert len(out) == 2 and out[0]["laps"][0]["hr"] == 160

    def test_uses_cache_hits_and_ignores_old_schema(self, monkeypatch):
        cache = {
            "1": {"version": ANALYSIS_SCHEMA_VERSION, "workout_id": "1", "distance_km": 3.1,
                  "laps": self.CACHED_LAPS, "date": "2026-09-10"},
            "2": {"version": ANALYSIS_SCHEMA_VERSION - 1, "workout_id": "2", "laps": self.CACHED_LAPS},
        }
        analysed = []
        self._patch(monkeypatch, cache, analysed)
        out = asyncio.run(tools._load_workout_summaries(None, self.WORKOUTS, "user_x"))
        assert analysed == ["2"]
        assert cache["2"]["version"] == ANALYSIS_SCHEMA_VERSION
        assert len(out) == 2


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
    EASY = {"id": "r1", "sport": "Run", "title": "Easy", "type": "planned"}

    def test_no_same_sport_workout_creates(self, tp_calls):
        tp_calls["workouts"] = [self.EASY]
        out = json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", sport="Strength", title="Core")))
        assert out["action"] == "created"
        assert tp_calls["runs"][0][0] == "tp_create_workout"
        payload = tp_calls["runs"][0][1]
        assert payload["date"] == "2026-09-20"
        assert "date_str" not in payload

    def test_single_same_sport_workout_is_updated(self, tp_calls):
        tp_calls["workouts"] = [self.EASY]
        out = json.loads(asyncio.run(tools.create_workout(None, "2026-09-20", title="Tempo")))
        assert out["action"] == "updated"
        assert tp_calls["runs"][0][1]["workout_id"] == "r1"
        assert tp_calls["runs"][0][1]["date"] == "2026-09-20"


def test_skill_toolset_only_exposes_load_skill():
    tool_list = asyncio.run(tools.skill_toolset.get_tools())
    assert [t.name for t in tool_list] == ["load_skill"]


class TestGoalPlanContext:
    """analyze_workout's goal-plan hook: saves a sub-goal race result, nothing else."""

    @pytest.fixture
    def writes(self, monkeypatch):
        calls = []

        async def fake_update(user_id, update):
            calls.append((user_id, update))

        monkeypatch.setattr(tools, "update_user_profile", fake_update)
        return calls

    def _run(self, profile, day, sport="Run"):
        from types import SimpleNamespace
        ctx = SimpleNamespace(state={"user_profile": profile})
        text = asyncio.run(tools._goal_plan_context(
            ctx, profile, date.fromisoformat(day), "w1", sport, {"duration_actual": 1245 / 3600}, {}
        ))
        return ctx, text

    def test_race_day_saves_result_and_refreshes_state(self, writes):
        from tests.test_goals import plan
        profile = {"firstname": "Cyrille", "lastname": "Visser", **plan()}
        ctx, text = self._run(profile, "2027-02-07")
        assert len(writes) == 1
        user_id, update = writes[0]
        assert user_id == "cyrille_visser" and set(update) == {"sub_goals"}
        saved = [s for s in update["sub_goals"] if s["goal"] == "Sub-21 5K"][0]["result"]
        assert saved == {"time": "20:45", "time_s": 1245, "workout_id": "w1"}
        assert ctx.state["user_profile"]["sub_goals"] == update["sub_goals"]
        assert "Result saved" in text

    def test_other_day_bike_or_single_goal_writes_nothing(self, writes):
        from tests.test_goals import SINGLE, plan
        profile = {"firstname": "Cyrille", "lastname": "Visser", **plan()}
        assert "current block" in self._run(profile, "2027-01-10")[1]
        self._run(profile, "2027-02-07", sport="Bike")
        assert self._run({"firstname": "C", "lastname": "V", **SINGLE}, "2026-11-01")[1] == ""
        assert writes == []
