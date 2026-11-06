"""Weekly aggregation of the training log, progress over time and training patterns.

Pure functions. Weekly rows join the per-workout records with the daily TP series (PMC and
health metrics, fetched fresh when the trend is computed).
"""

import re
from datetime import date, timedelta
from statistics import mean, median
from typing import Callable, Optional

from .classification import RUN_SPORTS
from .race_readiness import MAX_EXTRAPOLATION, fit_speed_vs_hr, steady_lap_points
from .structure import fmt_clock

HEALTH_BASELINE_DAYS = 28
HEAT_FEELS_LIKE_C = 20.0
LONG_RUN_PATTERN_SHARE = 0.30      # long-run week: longest run >= 30% of the week's running km
MIN_GROUP_N = 4
SUMMARY_WEEKS = 4                   # progress compares the first and last 4 complete weeks
NIGGLE_RE = re.compile(r"\b(pain|painful|sore|soreness|niggle|tight|tightness|calf|achilles|knee|shin|injur\w*)\b",
                       re.IGNORECASE)

# Key-run Pa:Hr: which sessions carry the goal-specific durability signal.
SHORT_GOALS = frozenset({"5K", "10K"})          # key run = tempo/threshold session
KEY_BAND_PCT = (87.0, 102.0)                     # tempo/marathon + threshold bands (% threshold pace)
KEY_REP_MIN_S = 300                              # 5K/10K: shorter reps are too noisy for Pa:Hr
KEY_BLOCK_MIN_S = 600                            # HM/marathon: race-specific blocks inside the long run
TEMPO_TITLE_RE = re.compile(r"tempo|threshold|cruise|\blt\b", re.IGNORECASE)
LT_FIT_WEEKS = 4                                 # rolling window for the weekly HR->pace fit


def is_run(record: dict) -> bool:
    return str(record.get("sport") or "").lower() in RUN_SPORTS


def _avg(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _median(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _window(dated: list[tuple[date, float]], start: date, end: date) -> list[float]:
    return [v for d, v in dated if start <= d <= end]


def _is_hot(record: dict) -> bool:
    return ((record.get("weather") or {}).get("feels_like_c") or 0) > HEAT_FEELS_LIKE_C


# ------------------------------------------------------------------ key-run Pa:Hr
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


# ------------------------------------------------------------------ LT1 / LT2 paces
def lt_paces(records: list[dict], week_end: date, lthr: Optional[float], lt1_hr: Optional[float]) -> dict:
    """Pace (s/km) at LT1 HR and at LTHR from a duration-weighted HR->pace fit over steady laps
    (>= 8 min, >= 70% LTHR, hot runs excluded) of the LT_FIT_WEEKS weeks ending `week_end`.

    HRs outside the fitted range are capped at +/- MAX_EXTRAPOLATION * LTHR and flagged.
    """
    out = {"lt1_pace_s": None, "lt2_pace_s": None, "lt1_extrapolated": False, "lt2_extrapolated": False}
    if not lthr:
        return out
    start = (week_end - timedelta(weeks=LT_FIT_WEEKS) + timedelta(days=1)).isoformat()
    window = [r for r in records if is_run(r) and r.get("laps") and not _is_hot(r)
              and start <= (r.get("date") or "") <= week_end.isoformat()]
    fit = fit_speed_vs_hr(steady_lap_points(window, lthr), lthr)
    if not fit:
        return out
    margin = MAX_EXTRAPOLATION * lthr
    for key, hr in (("lt1", lt1_hr), ("lt2", lthr)):
        if not hr:
            continue
        capped = max(fit["hr_min"] - margin, min(hr, fit["hr_max"] + margin))
        speed = fit["my"] + fit["slope"] * (capped - fit["mx"])
        if speed > 0:
            out[f"{key}_pace_s"] = 1000.0 / speed
            out[f"{key}_extrapolated"] = not (fit["hr_min"] <= hr <= fit["hr_max"])
    return out


def checkin_lt_paces(records: list[dict], today: date, lthr: Optional[float],
                     lt1_hr: Optional[float]) -> Optional[dict]:
    """Check-in LT1/LT2: the LT_FIT_WEEKS fit ending today vs the previous, non-overlapping one.

    None when the current window has no usable fit (no LTHR, too few steady laps).
    """
    now = lt_paces(records, today, lthr, lt1_hr)
    if now["lt1_pace_s"] is None and now["lt2_pace_s"] is None:
        return None
    prev = lt_paces(records, today - timedelta(weeks=LT_FIT_WEEKS), lthr, lt1_hr)
    return {"lt1_hr": lt1_hr, "lthr": lthr, "now": now, "prev": prev}


def lt_verdict(now_s: Optional[float], prev_s: Optional[float]) -> Optional[str]:
    """Pace verdict with the progress_summary rule: < 1% change is stable, faster is improving."""
    if now_s is None or not prev_s:
        return None
    change = now_s - prev_s
    if abs(change / prev_s) < 0.01:
        return VERDICT_STABLE
    return VERDICT_IMPROVING if change < 0 else VERDICT_DECLINING


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
        cool_easy = [r for r in easy if not _is_hot(r)]
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


# ------------------------------------------------------------------ progress
def _num(fmt: str) -> Callable[[float], str]:
    return fmt.format


def _pace(seconds: float) -> str:
    return f"{fmt_clock(seconds)}/km"


def _pace_change(seconds: float) -> str:
    return f"{seconds:+.0f} s/km"


def progress_markers(goal_label: Optional[str] = None) -> tuple:
    """(key, label, higher_is_better, value_fmt, change_fmt) per displayed progress marker."""
    return (
        ("ctl", "CTL (fitness)", True, _num("{:.1f}"), _num("{:+.1f}")),
        ("km", "Weekly running km", True, _num("{:.0f}"), _num("{:+.0f}")),
        ("lt1_pace_s", "Pace @ LT1 (top of zone 2)", False, _pace, _pace_change),
        ("lt2_pace_s", "Pace @ LT2 (LTHR)", False, _pace, _pace_change),
        ("key_decoupling", f"Key-run Pa:Hr % ({key_run_label(goal_label)})", False,
         _num("{:.1f}"), _num("{:+.1f}")),
        ("hrv", "HRV (ms)", True, _num("{:.0f}"), _num("{:+.0f}")),
        ("rhr", "Resting HR (bpm)", False, _num("{:.0f}"), _num("{:+.0f}")),
        ("sleep_h", "Sleep (h)", True, _num("{:.1f}"), _num("{:+.1f}")),
    )


VERDICT_IMPROVING, VERDICT_STABLE, VERDICT_DECLINING = "🟢 improving", "🟡 stable", "🔴 declining"


def progress_summary(rows: list[dict], goal_label: Optional[str] = None) -> list[dict]:
    """Per marker: mean of the first and last 4 complete weeks, best week, change and direction.

    `arrow` is the direction of the number; `verdict` judges the runner (e.g. a rising Pa:Hr or
    a slower LT pace is 🔴 declining even though the number went up).
    """
    complete = [r for r in rows if r["complete"]]
    out = []
    for key, label, higher, fmt, change_fmt in progress_markers(goal_label):
        values = [(r["week"], r[key]) for r in complete if r.get(key) is not None]
        if len(values) < 2:
            continue
        n = min(SUMMARY_WEEKS, max(1, len(values) // 2))
        first, latest = mean(v for _, v in values[:n]), mean(v for _, v in values[-n:])
        best = (max if higher else min)(values, key=lambda x: x[1])
        change = latest - first
        arrow = "→" if abs(change) < 1e-9 or (first and abs(change / first) < 0.01) else ("↑" if change > 0 else "↓")
        improving = change > 0 if higher else change < 0
        verdict = VERDICT_STABLE if arrow == "→" else (VERDICT_IMPROVING if improving else VERDICT_DECLINING)
        out.append({"key": key, "label": label, "first": fmt(first), "latest": fmt(latest),
                    "best": f"{fmt(best[1])} (wk {best[0].isoformat()})", "change": change_fmt(change),
                    "arrow": arrow, "verdict": verdict})
    return out


# ------------------------------------------------------------------ training patterns
def _outcomes(rows: list[dict], idx: list[int]) -> dict:
    """Mean next-week change in easy EF (%) and HRV delta, and same-week RPE, over weeks `idx`."""
    ef_changes, hrv_next, rpes = [], [], []
    for i in idx:
        cur, nxt = rows[i], rows[i + 1] if i + 1 < len(rows) else None
        if nxt and cur.get("easy_ef") and nxt.get("easy_ef"):
            ef_changes.append((nxt["easy_ef"] / cur["easy_ef"] - 1) * 100)
        if nxt and nxt.get("hrv_delta_pct") is not None:
            hrv_next.append(nxt["hrv_delta_pct"])
        if cur.get("rpe") is not None:
            rpes.append(cur["rpe"])
    n = max(len(ef_changes), len(hrv_next))
    return {"n": n, "ef_change_pct": _avg(ef_changes), "next_hrv_pct": _avg(hrv_next), "rpe": _avg(rpes),
            "insufficient": n < MIN_GROUP_N}


def _long_share(row: dict) -> float:
    """Longest run as a share of the week's running km (0 for weeks without volume)."""
    km = row.get("km") or 0.0
    return (row.get("long_km") or 0.0) / km if km > 0 else 0.0


def training_patterns(rows: list[dict]) -> list[dict]:
    """Session-mix comparisons (what kind of training, not how much or how fast)."""
    weeks = [i for i, r in enumerate(rows) if r["complete"] and r["runs"]]
    sleeps = [rows[i]["sleep_h"] for i in weeks if rows[i]["sleep_h"] is not None]
    sleep_mid = median(sleeps) if sleeps else None
    comparisons = [
        ("2+ quality sessions", "0-1 quality sessions",
         [i for i in weeks if rows[i]["quality"] >= 2], [i for i in weeks if rows[i]["quality"] < 2]),
        (f"Long run >= {LONG_RUN_PATTERN_SHARE:.0%} of week km", f"Long run < {LONG_RUN_PATTERN_SHARE:.0%} of week km",
         [i for i in weeks if _long_share(rows[i]) >= LONG_RUN_PATTERN_SHARE],
         [i for i in weeks if _long_share(rows[i]) < LONG_RUN_PATTERN_SHARE]),
    ]
    if sleep_mid is not None:
        comparisons.append((f"Sleep >= {sleep_mid:.1f} h", f"Sleep < {sleep_mid:.1f} h",
                            [i for i in weeks if (rows[i]["sleep_h"] or 0) >= sleep_mid],
                            [i for i in weeks if rows[i]["sleep_h"] is not None and rows[i]["sleep_h"] < sleep_mid]))
    return [{"a": a, "b": b, "a_out": _outcomes(rows, ia), "b_out": _outcomes(rows, ib)}
            for a, b, ia, ib in comparisons]


def spearman(xs: list[float], ys: list[float]) -> Optional[float]:
    """Spearman rank correlation (average ranks for ties); None when n < 5 or no variance."""
    if len(xs) != len(ys) or len(xs) < 5:
        return None

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = mean(rx), mean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return round(sxy / (sxx * syy) ** 0.5, 2) if sxx and syy else None


# ------------------------------------------------------------------ formatting
def _f(value: Optional[float], fmt: str = "{:.0f}", suffix: str = "") -> str:
    return fmt.format(value) + suffix if value is not None else "-"


def format_progress_table(progress: list[dict]) -> str:
    if not progress:
        return ""
    lines = ["**Progress** (mean of the first vs last complete weeks, up to 4 each):", "",
             "| Marker | First | Latest | Best | Change | Trend |", "|---|---|---|---|---|---|"]
    lines += [f"| {p['label']} | {p['first']} | {p['latest']} | {p['best']} | {p['change']} | {p['arrow']} {p['verdict']} |"
              for p in progress]
    return "\n".join(lines)


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


def format_patterns(patterns: list[dict]) -> str:
    lines = ["Training patterns (associations, not causes; outcome = next-week easy-EF change and HRV vs 28d "
             "baseline; same-week RPE):"]
    for p in patterns:
        parts = []
        for label, o in ((p["a"], p["a_out"]), (p["b"], p["b_out"])):
            tag = " INSUFFICIENT" if o["insufficient"] else ""
            parts.append(f"{label}: n={o['n']}{tag}, EF {_f(o['ef_change_pct'], '{:+.1f}', '%')}, "
                         f"HRV {_f(o['next_hrv_pct'], '{:+.0f}', '%')}, RPE {_f(o['rpe'], '{:.1f}')}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)
