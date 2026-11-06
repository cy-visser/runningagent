from datetime import date, timedelta
import re
from statistics import mean, median
from typing import Optional

from ....shared.calendar_notes import truncate_note
from ....shared.hr_pace_fit import (
    is_hot,
    is_run,
    lt_paces,
)
from ....shared.health_metrics import HEALTH_BASELINE_DAYS
from ....shared.units import fmt_clock

SHORT_GOALS = frozenset({"5K", "10K"})   # key run = tempo/threshold steps (longer goals: the long run)
NIGGLE_RE = re.compile(r"\b(pain|painful|sore|soreness|niggle|tight|tightness|calf|achilles|knee|shin|injur\w*)\b",
                       re.IGNORECASE)

# The coach sees weekly rows and comments for the most recent weeks only; progress, capacity,
# pacing and patterns are computed over the full window, and the web charts show every week.
LLM_RECENT_WEEKS = 8


def llm_comments(rows: list[dict], recent_weeks: int = LLM_RECENT_WEEKS) -> list[str]:
    """Athlete comments for the coach: every comment from the recent weeks plus older niggle
    comments (injury context), each capped like a calendar note."""
    cutoff = len(rows) - recent_weeks
    return [
        truncate_note(c)
        for i, r in enumerate(rows)
        for c in r["comments"]
        if i >= cutoff or NIGGLE_RE.search(c)
    ]

# Key-run Pa:Hr: which sessions carry the goal-specific durability signal.
KEY_BAND_PCT = (87.0, 102.0)                     # tempo/marathon + threshold bands (% threshold pace)
KEY_REP_MIN_S = 300                              # 5K/10K: shorter reps are too noisy for Pa:Hr
KEY_BLOCK_MIN_S = 600                            # HM/marathon: race-specific blocks inside the long run
TEMPO_TITLE_RE = re.compile(r"tempo|threshold|cruise|\blt\b", re.IGNORECASE)


def _avg(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _median(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _window(dated: list[tuple[date, float]], start: date, end: date) -> list[float]:
    return [v for d, v in dated if start <= d <= end]


def key_run_label(goal_label: Optional[str]) -> str:
    return "tempo/threshold" if goal_label in SHORT_GOALS else "long run / race-pace blocks"


def _key_steps(record: dict, min_s: float) -> list[dict]:
    """Work steps targeted in the tempo/threshold bands (% threshold pace), >= min_s, with Pa:Hr."""
    out = []
    for iv in record.get("work_intervals") or []:
        target = iv.get("target") or {}
        if target.get("metric") != "percentOfThresholdPace" or target.get("lo") is None or target.get("hi") is None:
            continue
        mid = (target["lo"] + target["hi"]) / 2
        if (KEY_BAND_PCT[0] <= mid < KEY_BAND_PCT[1] and (iv.get("duration_s") or 0) >= min_s
                and iv.get("decoupling") is not None):
            out.append(iv)
    return out


def _has_pace_targets(record: dict) -> bool:
    return any((iv.get("target") or {}).get("metric") == "percentOfThresholdPace"
               for iv in record.get("work_intervals") or [])


def _weighted_decoupling(steps: list[dict]) -> Optional[float]:
    total = sum(s["duration_s"] for s in steps)
    return sum(s["decoupling"] * s["duration_s"] for s in steps) / total if total else None


def key_run_decoupling(record: dict, goal_label: Optional[str]) -> Optional[float]:
    """Pa:Hr % of a goal-specific key session, or None when the run is not a key session.

    5K/10K: tempo/threshold work steps (87-102% threshold pace, reps >= 5 min), duration-weighted;
    an unstructured run titled tempo/threshold uses its session Pa:Hr. VO2/short reps never count.
    Longer goals: the long run; its race-specific blocks (same bands, >= 10 min) when present,
    otherwise the whole-run Pa:Hr (warm-up/cool-down excluded).
    """
    if not is_run(record):
        return None
    kind = record.get("kind")
    if goal_label in SHORT_GOALS:
        if kind != "quality":
            return None
        steps = _key_steps(record, KEY_REP_MIN_S)
        if steps:
            return _weighted_decoupling(steps)
        if not _has_pace_targets(record) and TEMPO_TITLE_RE.search(record.get("title") or ""):
            return record.get("session_decoupling")
        return None
    if kind != "long":
        return None
    steps = _key_steps(record, KEY_BLOCK_MIN_S)
    return _weighted_decoupling(steps) if steps else record.get("session_decoupling")


def weekly_rows(
    records: list[dict], daily_pmc: list[dict], dated_metrics: dict, start: date, end: date,
    unrecorded_dates: Optional[list[str]] = None, goal_label: Optional[str] = None,
    lthr: Optional[float] = None, lt1_hr: Optional[float] = None,
) -> list[dict]:
    """One row per ISO week (Monday) from `start` to `end`.

    `complete` is False for the current week and for weeks with completed workouts that are not
    in the training log yet (`unrecorded`): their totals would be undercounted, so they are
    excluded from progress, capacity and pattern conclusions.
    `easy_ef` is kept as an internal tolerance/pattern signal; it is not a displayed progress marker.
    """
    pmc = {str(r.get("date", ""))[:10]: r for r in daily_pmc or []}
    metrics = dated_metrics or {}
    rows = []
    week = start - timedelta(days=start.weekday())
    while week <= end:
        week_end = week + timedelta(days=6)
        recs = [r for r in records if week.isoformat() <= (r.get("date") or "") <= week_end.isoformat()]
        runs = [r for r in recs if is_run(r)]
        easy = [r for r in runs if r.get("kind") == "easy" and r.get("ef")]
        cool_easy = [r for r in easy if not is_hot(r)]
        key_decs = [d for d in (key_run_decoupling(r, goal_label) for r in runs) if d is not None]
        comments = [f"{r['date']}: {r['athlete']['comment']}" for r in recs
                    if (r.get("athlete") or {}).get("comment")]
        last_pmc = next((pmc[d.isoformat()] for d in (week_end - timedelta(days=i) for i in range(7))
                         if d.isoformat() in pmc), {})
        base_start, base_end = week - timedelta(days=HEALTH_BASELINE_DAYS), week - timedelta(days=1)
        health = {}
        for key in ("hrv", "rhr", "sleep"):
            now = _avg(_window(metrics.get(key, []), week, min(week_end, end)))
            base = _avg(_window(metrics.get(key, []), base_start, base_end))
            health[key] = now
            health[f"{key}_base"] = base
        unrecorded = sum(week.isoformat() <= d[:10] <= week_end.isoformat() for d in unrecorded_dates or [])
        rows.append({
            "week": week,
            "complete": week_end <= end and not unrecorded,
            "unrecorded": unrecorded,
            "km": round(sum(r.get("distance_km") or 0 for r in runs), 1),
            "tss": round(sum(r.get("tss") or 0 for r in recs), 1),
            "runs": len(runs),
            "quality": sum(r.get("kind") in ("quality", "race") for r in runs),
            "long_km": max((r.get("distance_km") or 0 for r in runs), default=0.0),
            "ctl": last_pmc.get("ctl"),
            "tsb": last_pmc.get("tsb"),
            "hrv": health["hrv"],
            "hrv_delta_pct": (health["hrv"] / health["hrv_base"] - 1) * 100
            if health["hrv"] and health["hrv_base"] else None,
            "rhr": health["rhr"],
            "rhr_delta": health["rhr"] - health["rhr_base"] if health["rhr"] and health["rhr_base"] else None,
            "sleep_h": health["sleep"],
            "sleep_delta_min": (health["sleep"] - health["sleep_base"]) * 60
            if health["sleep"] and health["sleep_base"] else None,
            "easy_ef": _median([r["ef"] for r in cool_easy]),
            "hot_easy_runs": len(easy) - len(cool_easy),
            "key_decoupling": _median(key_decs),
            "key_sessions": len(key_decs),
            **lt_paces(records, min(week_end, end), lthr, lt1_hr),
            "rpe": _avg([(r.get("athlete") or {}).get("rpe") for r in recs]),
            "niggle": any(NIGGLE_RE.search(c) for c in comments),
            "comments": comments,
        })
        week += timedelta(days=7)
    return rows


def _f(value: Optional[float], fmt: str = "{:.0f}", suffix: str = "") -> str:
    return fmt.format(value) + suffix if value is not None else "-"


def _lt(r: dict, key: str) -> str:
    pace = r.get(f"{key}_pace_s")
    return f"{fmt_clock(pace)}{'*' if r.get(f'{key}_extrapolated') else ''}" if pace else "-"


def format_weekly_table(rows: list[dict]) -> str:
    lines = ["| Week | km | TSS | Runs (Q) | Long km | CTL | HRV Δ | RHR Δ | Sleep | LT1 | LT2 | Key Pa:Hr | RPE | Niggle |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        partial = (f" ({r['unrecorded']} unrecorded)" if r.get("unrecorded") else
                   "" if r["complete"] else " (partial)")
        lines.append(
            f"| {r['week'].isoformat()}{partial} | {r['km']:.0f} | {r['tss']:.0f} | {r['runs']} ({r['quality']}) "
            f"| {r['long_km']:.0f} | {_f(r['ctl'], '{:.1f}')} | {_f(r['hrv_delta_pct'], '{:+.0f}', '%')} "
            f"| {_f(r['rhr_delta'], '{:+.0f}')} | {_f(r['sleep_h'], '{:.1f}', 'h')} "
            f"| {_lt(r, 'lt1')} | {_lt(r, 'lt2')} | {_f(r.get('key_decoupling'), '{:.1f}', '%')} "
            f"| {_f(r['rpe'], '{:.1f}')} | {'yes' if r['niggle'] else ''} |")
    lines += ["", "LT1/LT2 = pace (min/km) at top of zone 2 / at LTHR from a rolling 4-week HR->pace fit; "
              "* = extrapolated beyond the fitted HR range."]
    return "\n".join(lines)
