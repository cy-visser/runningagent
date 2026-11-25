"""Shared deterministic fakes and synthetic runner data for feature-level behavioural tests."""

from datetime import date, datetime, timedelta
import json
import pathlib
from types import SimpleNamespace
from typing import Any

FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
CANOVA = json.loads((FIXTURES_DIR / "structured_workouts.json").read_text(encoding="utf-8"))["canova"]

FROZEN_NOW = datetime(2026, 10, 27, 9, 0, 0)
TODAY = FROZEN_NOW.date()
EMAIL = "cyrille@cyvisser.altostrat.com"

PLAN_PROFILE = {
    "firstname": "Cyrille",
    "lastname": "Visser",
    "email": EMAIL,
    "age": "38",
    "height": "182 cm",
    "weight": "72 kg",
    "location": "Amsterdam",
    "latitude": 52.37,
    "longitude": 4.89,
    "goal_type": "plan",
    "north_star": {
        "goal": "Sub-3:15 Marathon",
        "race_name": "London Marathon 2028",
        "start_date": None,
        "race_date": "2028-04-23",
    },
    "sub_goals": [
        {
            "goal": "Sub-21 5K",
            "race_name": "Amsterdam 5K",
            "start_date": "2026-08-01",
            "race_date": "2026-10-20",
            "result": None,
        },
        {
            "goal": "Sub-43 10K",
            "race_name": "Schoorl 10K",
            "start_date": "2026-11-16",
            "race_date": "2027-02-14",
            "result": None,
        },
    ],
    "personal_records": {
        "5k": {"time": "21:30", "time_s": 1290, "date": "2026-05-10"},
        "10k": None,
        "10_mile": None,
        "half_marathon": None,
        "marathon": None,
    },
    "injuries": "Past left Achilles tendinopathy",
    "run_time_of_day": "morning",
    "strength_time_of_day": "evening",
    "shoe_rotation": {
        "easy": "Superblast 2",
        "tempo": "Takumi Sen",
        "interval": "Takumi Sen",
        "long_run": "Superblast 2",
        "race": None,
    },
}

SINGLE_PROFILE = {
    "firstname": "Cyrille",
    "lastname": "Visser",
    "email": EMAIL,
    "age": "38",
    "height": "182 cm",
    "weight": "72 kg",
    "location": "Amsterdam",
    "latitude": 52.37,
    "longitude": 4.89,
    "goal_type": "single",
    "training_goal": "Sub-3:30 Marathon",
    "timeline": "2026-12-06",
    "goal_set_date": "2026-08-01",
}

SETTINGS = {
    "settings": {
        "heartRateZones": [
            {
                "workoutTypeId": 3,
                "threshold": 172,
                "maximum": 190,
                "resting": 48,
                "zones": [
                    {"label": "Zone 1", "minimum": 111, "maximum": 145},
                    {"label": "Zone 2", "minimum": 146, "maximum": 155},
                    {"label": "Zone 3", "minimum": 156, "maximum": 164},
                    {"label": "Zone 4", "minimum": 165, "maximum": 172},
                    {"label": "Zone 5", "minimum": 173, "maximum": 190},
                ],
            }
        ],
        "speedZones": [{"workoutTypeId": 3, "threshold": 3.509}],
        "powerZones": [{"workoutTypeId": 2, "threshold": 260}],
    }
}


def envelope(data: Any) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data)}]}


def _range_days(kw: dict) -> int:
    """Days between start_date and end_date of a TP list call (0 when either is missing)."""
    s, e = kw.get("start_date"), kw.get("end_date")
    if not s or not e:
        return 0
    return (date.fromisoformat(e[:10]) - date.fromisoformat(s[:10])).days


class FakeContext:
    """Minimal ADK ToolContext / Workflow Context double."""

    def __init__(
        self,
        profile: dict | None = None,
        state: dict | None = None,
        user_id: str | None = None,
        invocation_id: str = "inv-1",
    ):
        self.state: dict[str, Any] = dict(state or {})
        if profile is not None and "user_profile" not in self.state:
            self.state["user_profile"] = json.loads(json.dumps(profile))
        self.session = SimpleNamespace(user_id=user_id, events=[])
        self.route: str | None = None
        self.invocation_id = invocation_id
        self.function_call_id: str | None = None
        self.actions = SimpleNamespace(skip_summarization=None)
        self.ui_widgets: list = []

    def render_ui_widget(self, ui_widget) -> None:
        self.ui_widgets.append(ui_widget)

    def reply_text(self) -> str | None:
        """The latest coded reply a tool showed the runner (None if none)."""
        texts = [w.payload["data"]["text"] for w in self.ui_widgets if w.payload.get("kind") == "reply"]
        return texts[-1] if texts else None


class FakeRunnerEnv:
    """In-memory TrainingPeaks, Firestore, Open-Meteo and clock state for one synthetic runner."""

    def __init__(self, data_file_path: str | None = None):
        self.now = FROZEN_NOW
        self.today = TODAY
        self.data_file_path = data_file_path
        self.profiles: dict[str, dict] = {"cyrille_visser": json.loads(json.dumps(PLAN_PROFILE))}
        self.connected_runners: set[str] = {"cyrille_visser"}
        self.training_records: dict[str, dict] = {}
        self.volume_history_cache: dict[str, dict] = {}
        self.race_projection_cache: dict[str, dict] = {}
        self.year_review_cache: dict[tuple[str, int], dict] = {}
        self.year_review_raw_cache: dict[tuple[str, int], dict] = {}
        self.year_review_index: dict[str, dict] = {}
        self.events: list[dict] = []
        self.peaks: dict[tuple, list[dict]] = {}
        self.analysis_overrides: dict[str, dict] = {}
        self.profile_updates: list[tuple[str, dict]] = []
        self.tp_calls: list[tuple[str, dict]] = []
        self.rate_limited_workout_ids: set[str] = set()
        # TP tool names that always answer with an error envelope (outage simulation).
        self.failing_tools: set[str] = set()
        # The next N workout writes (create / update / delete) answer 429 Too Many Requests.
        self.write_429s = 0
        self.workouts, self.daily_pmc, self.metrics, self.notes = self._build_data()

    def ctx(self, profile: dict | None = None, state: dict | None = None, user_id: str | None = None) -> FakeContext:
        return FakeContext(profile=profile if profile is not None else PLAN_PROFILE, state=state, user_id=user_id)

    def _build_data(self) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        workouts: list[dict] = []
        base_monday = date(2026, 8, 31)
        wid = 100
        for wk in range(13):
            monday = base_monday + timedelta(weeks=wk)
            for offset, (sport, title, km, dur_h, tss) in enumerate([
                ("Run", "Easy Aerobic Run", 10.0, 0.9, 52.0),
                ("Run", "Threshold 2 x 15'", 12.5, 1.05, 82.0),
                ("Bike", "Z2 Spin", 30.0, 1.0, 45.0),
                ("Run", "Easy Run", 8.0, 0.72, 42.0),
                ("Run", "Long Run", 20.0 if wk < 8 else 14.0, 1.8 if wk < 8 else 1.25, 110.0 if wk < 8 else 76.0),
            ]):
                day = monday + timedelta(days=offset + (1 if offset >= 2 else 0))
                wid += 1
                completed = day <= self.today
                d_iso = day.strftime("%Y-%m-%d")
                w: dict[str, Any] = {
                    "id": f"w{wid}",
                    "date": d_iso,
                    "start_time": f"{d_iso}T07:30:00",
                    "title": title,
                    "sport": sport,
                    "type": "completed" if completed else "planned",
                    "distance_planned_km": km,
                    "duration_planned": dur_h,
                    "tss_planned": tss,
                }
                if completed:
                    w.update({"distance_actual_km": km, "duration_actual": dur_h, "tss_actual": tss})
                workouts.append(w)

        workouts.append({
            "id": "w_race_5k",
            "date": "2026-10-20",
            "start_time": "2026-10-20T09:00:00",
            "title": "Amsterdam 5K Race",
            "sport": "Run",
            "type": "completed",
            "distance_actual_km": sum(lap["TotalDistance"] for lap in CANOVA["laps"]),
            "duration_actual": 1245 / 3600,
            "tss_actual": 85.0,
            "distance_planned_km": 5.0,
            "duration_planned": 0.35,
            "tss_planned": 75.0,
        })

        daily_pmc = []
        for i in range(100):
            d = self.today - timedelta(days=99 - i)
            ctl = round(50.0 + i * 0.14, 2)
            atl = round(ctl + 4.0, 2)
            daily_pmc.append({"date": d.strftime("%Y-%m-%d"), "ctl": ctl, "atl": atl, "tsb": round(ctl - atl, 2)})

        metrics = []
        for i in range(45):
            d = self.today - timedelta(days=44 - i)
            metrics.append({
                "timeStamp": f"{d.strftime('%Y-%m-%d')}T00:00:00",
                "details": [
                    {"type": 60, "value": 58.0 + (i % 3)},
                    {"type": 5, "value": 48.0 - (i % 2)},
                    {"type": 7, "value": 7.6},
                ],
            })

        notes = [
            {"id": "n1", "date": "2026-10-25", "title": "Slight calf tightness", "description": "Foam rolled"},
            {"id": "n2", "date": "2026-11-01", "title": "Work trip to Berlin", "description": "Hotel gym available"},
        ]
        return workouts, daily_pmc, metrics, notes

    async def run_tp_tool(self, tool_context: Any, tool_name: str, /, **kw: Any) -> Any:
        name = tool_name
        self.tp_calls.append((name, kw))
        if name in self.failing_tools:
            return envelope({"isError": True, "error_code": "API_ERROR", "message": "503 Service Unavailable"})
        if name in ("tp_get_workouts", "tp_list_notes", "tp_get_metrics", "tp_get_events") and _range_days(kw) > 90:
            # Same rule as the real MCP DateRangeInput validator.
            return envelope({"isError": True, "error_code": "VALIDATION_ERROR",
                             "message": "Date range too large. Maximum 90 days."})
        if name == "tp_get_workouts":
            s, e = kw["start_date"][:10], kw["end_date"][:10]
            return envelope({"workouts": [w for w in self.workouts if s <= w["date"] <= e]})
        if name == "tp_get_events":
            s, e = kw["start_date"][:10], kw["end_date"][:10]
            return envelope({"events": [
                ev for ev in self.events
                if s <= str(ev.get("eventDate") or ev.get("date") or "")[:10] <= e
            ]})
        if name == "tp_get_peaks":
            pr_type = str(kw.get("pr_type") or "")
            s_date = str(kw.get("start_date") or "")[:10]
            e_date = str(kw.get("end_date") or "")[:10]
            if s_date and e_date:
                recs = self.peaks.get((pr_type, s_date, e_date))
                if recs is None:
                    recs = [
                        r for r in (self.peaks.get((pr_type, 365)) or [])
                        if s_date <= str(r.get("date") or "")[:10] <= e_date
                    ]
                return envelope({
                    "sport": kw.get("sport", "Run"),
                    "pr_type": pr_type,
                    "start_date": s_date,
                    "end_date": e_date,
                    "records": recs,
                })
            days = int(kw.get("days") or 3650)
            recs = self.peaks.get((pr_type, days)) or self.peaks.get((pr_type, 365 if days <= 365 else 3650)) or []
            return envelope({"sport": kw.get("sport", "Run"), "pr_type": pr_type, "days": days, "records": recs})
        if name == "tp_list_notes":
            s, e = kw["start_date"][:10], kw["end_date"][:10]
            return envelope({"notes": [n for n in self.notes if s <= n["date"] <= e]})
        if name == "tp_get_workout":
            wid = str(kw["workout_id"])
            w = next((w for w in self.workouts if str(w["id"]) == wid), None)
            if not w:
                return envelope({"isError": True, "message": "not found"})
            is_run = w["sport"] == "Run"
            return envelope({
                "id": w["id"],
                "date": w["date"],
                "title": w["title"],
                "sport": w["sport"],
                "completed": w.get("type") == "completed",  # as the real tp_get_workout
                "description": "Warm up 15 min easy, main set controlled, cool down 10 min.",
                "rpe": 6,
                "feeling": 7,
                "new_comment": "Felt strong and controlled",
                "structured_workout": CANOVA["structured_workout"] if is_run else None,
                "metrics": {
                    "duration_actual": w.get("duration_actual", 1.0),
                    "distance_actual_km": w.get("distance_actual_km", 10.0),
                    "tss_actual": w.get("tss_actual", 70.0),
                    "if_actual": 0.85,
                    "duration_planned": w.get("duration_planned", 1.0),
                    "distance_planned_km": w.get("distance_planned_km", 10.0),
                    "tss_planned": w.get("tss_planned", 70.0),
                    "calories": 680,
                },
            })
        if name == "tp_analyze_workout":
            wid = str(kw["workout_id"])
            if wid in self.rate_limited_workout_ids:
                return envelope({"isError": True, "error_code": "API_ERROR", "message": "429 Too Many Requests"})
            if wid in self.analysis_overrides:
                return envelope(self.analysis_overrides[wid])
            return envelope({
                "lapData": CANOVA["laps"],
                "totals": {
                    "Avg heart rate": {"value": 146, "unit": "bpm"},
                    "Max heart rate": {"value": 162, "unit": "bpm"},
                    "NGP": {"value": 4.95, "unit": "min/km"},
                    "Pa:Hr": {"value": CANOVA["tp_pa_hr"], "unit": "%"},
                    "Duration": {"value": 1245, "unit": "s"},
                },
                "startTimestamp": "2026-10-20T09:00:00",
                "data_file": self.data_file_path,
            })
        if name == "tp_get_fitness":
            s, e = kw["start_date"][:10], kw["end_date"][:10]
            return envelope({"daily_data": [d for d in self.daily_pmc if s <= d["date"] <= e]})
        if name == "tp_get_metrics":
            s, e = kw["start_date"][:10], kw["end_date"][:10]
            return envelope({"metrics": [m for m in self.metrics if s <= m["timeStamp"][:10] <= e]})
        if name == "tp_get_athlete_settings":
            return envelope(SETTINGS)
        if name in ("tp_create_workout", "tp_update_workout", "tp_delete_workout") and self.write_429s > 0:
            self.write_429s -= 1
            return envelope({"isError": True, "error_code": "API_ERROR", "message": "429 Too Many Requests"})
        if name == "tp_create_workout":
            return envelope({"id": "created-999"})
        if name == "tp_update_workout":
            return envelope({"id": kw.get("workout_id", "updated-999")})
        if name == "tp_create_note":
            return envelope({"id": "note-999", "date": kw.get("date"), "title": kw.get("title")})
        if name == "tp_delete_workout":
            self.workouts = [w for w in self.workouts if str(w["id"]) != str(kw["workout_id"])]
            return envelope({"success": True})
        if name == "tp_delete_note":
            self.notes = [n for n in self.notes if str(n.get("id")) != str(kw["note_id"])]
            return envelope({"success": True})
        if name == "tp_create_event":
            ev_id = f"ev-{len(self.events) + 1}"
            ev = {
                "id": ev_id,
                "name": kw.get("name"),
                "eventDate": kw.get("date"),
                "eventType": kw.get("event_type") or "RunningRoad",
                "atpPriority": kw.get("priority") or "C",
                "raceTypeDuration": kw.get("race_type_duration"),
                "distance": round(float(kw["distance_km"]) * 1000.0, 1) if kw.get("distance_km") is not None else None,
                "distanceUnits": "Meters" if kw.get("distance_km") is not None else None,
                "goals": {
                    "time": {"value": 0.0} if kw.get("goal_time") else None,
                    "place": {"value": int(kw["goal_place"])} if kw.get("goal_place") is not None else None,
                    "pr": {"value": bool(kw["goal_pr"])} if kw.get("goal_pr") is not None else None,
                },
            }
            self.events.append(ev)
            return envelope({"success": True, "event_id": ev_id, "name": kw.get("name"), "date": kw.get("date")})
        if name == "tp_update_event":
            ev_id = str(kw.get("event_id") or "")
            for ev in self.events:
                if str(ev.get("id") or "") == ev_id:
                    if kw.get("name") is not None:
                        ev["name"] = kw["name"]
                    if kw.get("date") is not None:
                        ev["eventDate"] = kw["date"]
                    if kw.get("event_type") is not None:
                        ev["eventType"] = kw["event_type"]
                    if kw.get("priority") is not None:
                        ev["atpPriority"] = kw["priority"]
                    if kw.get("race_type_duration") is not None:
                        ev["raceTypeDuration"] = kw["race_type_duration"]
                    if kw.get("distance_km") is not None:
                        ev["distance"] = round(float(kw["distance_km"]) * 1000.0, 1)
                        ev["distanceUnits"] = "Meters"
                    break
            return envelope({"success": True, "event_id": ev_id})
        if name == "tp_delete_event":
            self.events = [e for e in self.events if str(e.get("id")) != str(kw["event_id"])]
            return envelope({"success": True})
        return envelope({})
