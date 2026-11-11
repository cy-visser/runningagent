"""Training zones of the plan builder: run zones as % of threshold speed, bike zones as % of FTP.

Resolved once at staging and saved with the staged plan, so `apply_training_plan` expands every code
with exactly the same targets later (even if the runner's thresholds or goals change in between).
Goal-pace codes (@5K / @10K / @HM / @M) use the runner's goal target when a goal of that distance has a
target time, otherwise the typical threshold -> race speed ratio of that distance.
"""

from datetime import date
from typing import Any, Optional

from ....shared.athlete_settings import sport_thresholds
from ....shared.goal_distance import DISTANCE_PROFILES, resolve_goal_distance
from ....shared.goal_plan import blocks, current_goal
from ....shared.race_equivalents import goal_km, goal_target_s
from ....shared.units import fmt_clock

# Run zones, whole % of threshold speed (TrainingPeaks' percentOfThresholdPace: higher = faster).
RUN_ZONES: dict[str, tuple[int, int]] = {
    "R": (68, 75),     # recovery run
    "E": (75, 82),     # easy run
    "L": (75, 83),     # long run
    "WU": (72, 80),    # warm-up / cool-down
    "JOG": (65, 75),   # recovery jog between reps
    "T": (97, 101),    # threshold
    "I": (106, 111),   # VO2max intervals
    "Rp": (112, 120),  # speed reps
    "H": (100, 110),   # hill reps (effort; pace drops on the hill)
}
# Bike zones, whole % of FTP.
BIKE_ZONES: dict[str, tuple[int, int]] = {
    "Z1": (45, 55),
    "Z2": (56, 75),
    "Z3": (76, 87),
    "SS": (88, 94),
    "T": (95, 105),
    "VO2": (106, 120),
    "WU": (50, 65),
    "REC": (45, 55),
}
# Goal-pace code -> distance label of shared.goal_distance.
GOAL_PACES = {"5K": "5K", "10K": "10K", "HM": "Half Marathon", "M": "Marathon"}
# Half-width of a goal-pace band in % of threshold speed (~ +-3 s/km).
GOAL_BAND_PCT = 1.0
# A goal-derived pace outside this range of threshold speed is not trusted (typo, stale threshold).
GOAL_PCT_RANGE = (70.0, 130.0)


def _goal_blocks(profile: Optional[dict], today: date) -> list[dict]:
    """The runner's goals, the current block first (it decides a pace when two goals share a distance)."""
    plan_blocks = blocks(profile)
    current = current_goal(profile, today)
    return [current, *[b for b in plan_blocks if b.get("timeline") != current.get("timeline")]]


def _goal_pct(goal_text: Any, threshold_speed: Optional[float]) -> Optional[float]:
    km, target = goal_km(goal_text), goal_target_s(goal_text)
    if not km or not target or not threshold_speed:
        return None
    pct = km * 1000.0 / target / threshold_speed * 100.0
    return pct if GOAL_PCT_RANGE[0] <= pct <= GOAL_PCT_RANGE[1] else None


def _band(pct: float) -> list[int]:
    return [round(pct - GOAL_BAND_PCT), round(pct + GOAL_BAND_PCT)]


def resolve_zones(settings_raw: Any, profile: Optional[dict], today: date) -> dict:
    """JSON-safe zone table: thresholds per sport, run / bike zones, goal paces (with their source) and
    the goal races (date, title, km, pace band) a RACE code can refer to."""
    run_thr = sport_thresholds(settings_raw, "Run")
    bike_thr = sport_thresholds(settings_raw, "Bike")
    speed = run_thr.get("threshold_speed")
    goals = _goal_blocks(profile, today)

    goal_paces: dict[str, dict] = {}
    for code, label in GOAL_PACES.items():
        goal = next((g for g in goals if resolve_goal_distance(g.get("training_goal")) == label
                     and _goal_pct(g.get("training_goal"), speed)), None)
        if goal:
            pct, source = _goal_pct(goal["training_goal"], speed), f"goal {goal['training_goal']}"
        else:
            pct, source = DISTANCE_PROFILES[label]["ratios"]["moderate"] * 100.0, "typical for the distance"
        goal_paces[code] = {"pct": _band(pct), "source": source}

    races = []
    for g in goals:
        label = resolve_goal_distance(g.get("training_goal"))
        code = next((c for c, lbl in GOAL_PACES.items() if lbl == label), None)
        if not g.get("timeline") or not code or str(g["timeline"])[:10] < today.isoformat():
            continue
        races.append({"date": str(g["timeline"])[:10], "title": g.get("race_name") or g.get("training_goal"),
                      "km": goal_km(g.get("training_goal")), "pace": code})
    races.sort(key=lambda r: r["date"])
    return {
        "thr": {"run": run_thr, "bike": bike_thr},
        "run": {k: list(v) for k, v in RUN_ZONES.items()},
        "bike": {k: list(v) for k, v in BIKE_ZONES.items()},
        "goal": goal_paces,
        "races": races,
    }


def run_band(zones: dict, key: str) -> list[int]:
    """[min %, max %] of a run zone or goal-pace code ('E', 'T', 'M', 'HM', ...)."""
    if key in zones["goal"]:
        return list(zones["goal"][key]["pct"])
    return list(zones["run"][key])


def pace_text(band: list[int], threshold_speed: Optional[float]) -> str:
    """'4:42–4:54/km' for a % band, or '97–101%' without a threshold pace."""
    if not threshold_speed:
        return f"{band[0]}–{band[1]}%"
    fast, slow = (fmt_clock(1000.0 / (threshold_speed * p / 100.0)) for p in (band[1], band[0]))
    return f"{fast}/km" if fast == slow else f"{fast}–{slow}/km"


def zone_table_text(zones: dict) -> str:
    """Compact zone table for the plan context (what each code resolves to)."""
    speed = zones["thr"]["run"].get("threshold_speed")
    ftp = zones["thr"]["bike"].get("ftp")
    head = f"threshold {fmt_clock(1000.0 / speed)}/km" if speed else "no threshold pace in TrainingPeaks: % only"
    run = " · ".join(f"{k} {pace_text(v, speed)}" for k, v in zones["run"].items() if k not in ("WU", "JOG"))
    goal = " · ".join(f"@{k} {pace_text(v['pct'], speed)} ({v['source']})" for k, v in zones["goal"].items())

    def watts(band: list[int]) -> str:
        return f"{band[0]}–{band[1]}% FTP" + (f" ({round(ftp * band[0] / 100)}–{round(ftp * band[1] / 100)} W)"
                                              if ftp else "")

    bike = " · ".join(f"{k} {watts(v)}" for k, v in zones["bike"].items() if k not in ("WU", "REC"))
    lines = [f"- Run ({head}): {run}", f"- Goal paces: {goal}",
             f"- Bike ({f'FTP {round(ftp)} W' if ftp else 'no FTP in TrainingPeaks'}): {bike}"]
    if zones.get("races"):
        lines.append("- Goal races (RACE code): " + " · ".join(
            f"{r['date']} {r['title']} ({r['km']:g} km @{r['pace']})" for r in zones["races"]))
    return "\n".join(lines)
