"""Evidence-based race readiness model for goal-race projections.

Replaces extrapolating raw distance peaks (which treats Zone 2 runs as race
efforts) with physiology- and training-specific signals:

  S1 Threshold anchor      observed threshold laps (HR 88-102% LTHR) vs the TP setting
  S2 Goal-pace segments    laps near race pace, judged by %LTHR and lap Pa:Hr decoupling
  S3 HR -> pace efficiency weighted regression of steady laps, evaluated at race HR
  S4 Durability            long-run length and decoupling -> threshold-to-race-pace ratio
  S5 Load                  CTL progression to race day (today vs race-day projection)
  S6 Health                HRV / RHR / sleep vs 28-day baseline, load- and race-week-aware
  S7 Race efforts          only runs titled as races/time trials, via Riegel

Every constant below is a coaching heuristic (Daniels/McMillan-style), kept in
one place for tuning. All functions are pure (no I/O) so they are unit-testable
and so cached workout summaries can be fed straight back in.
"""

import re
from datetime import date, timedelta
from typing import Any, Optional

from .date_helpers import parse_date
from .metrics import coerce_mcp_payload
from .race_prediction import ctl_on, detraining_factor, format_seconds_hms, riegel_predict

# Bump when the cached workout-summary schema changes; older cache entries are ignored.
ANALYSIS_SCHEMA_VERSION = 1

PROJECTION_WINDOW_DAYS = 56
MAX_ANALYSES = 8

# Per-distance profiles: goal km, typical race HR as a fraction of LTHR, minimum
# goal-pace segment length, threshold->race speed ratio per durability tier, and
# what counts as a "long run" for that distance.
DISTANCE_PROFILES: dict[str, dict[str, Any]] = {
    "5K": {"km": 5.0, "race_hr": 1.03, "min_seg_s": 120, "long_km": 12.0,
           "ratios": {"strong": 1.07, "moderate": 1.07, "weak": 1.07}},
    "10K": {"km": 10.0, "race_hr": 1.00, "min_seg_s": 240, "long_km": 14.0,
            "ratios": {"strong": 1.025, "moderate": 1.025, "weak": 1.025}},
    "10 Mile": {"km": 16.0934, "race_hr": 0.97, "min_seg_s": 480, "long_km": 16.0,
                "ratios": {"strong": 0.985, "moderate": 0.985, "weak": 0.975}},
    "Half Marathon": {"km": 21.0975, "race_hr": 0.95, "min_seg_s": 480, "long_km": 18.0,
                      "ratios": {"strong": 0.97, "moderate": 0.97, "weak": 0.955}},
    "Marathon": {"km": 42.195, "race_hr": 0.89, "min_seg_s": 600, "long_km": 20.0,
                 "ratios": {"strong": 0.93, "moderate": 0.91, "weak": 0.88}},
}

# Durability tiers: (strong_min_longest_km, weak_below_longest_km) per distance.
DURABILITY_LONGEST_KM = {
    "5K": (10.0, 6.0), "10K": (14.0, 10.0), "10 Mile": (19.0, 14.0),
    "Half Marathon": (20.0, 16.0), "Marathon": (30.0, 24.0),
}
DECOUPLING_OK = 5.0       # % Pa:Hr considered aerobically stable
DECOUPLING_WEAK = 8.0     # % Pa:Hr indicating poor durability
# Runs this long are long runs whatever the goal (their MP blocks are not threshold work).
ABSOLUTE_LONG_KM = 20.0

# S1 threshold laps
THRESHOLD_LAP_MIN_S = 480
THRESHOLD_LAP_MAX_S = 2400
THRESHOLD_HR_BAND = (0.88, 1.02)
THRESHOLD_AGREEMENT = 0.03   # observed vs TP setting within 3% -> average them
# Lap must be within 10% of the TP threshold speed (drops cool-downs with lagging HR).
THRESHOLD_PACE_BAND = 0.10

# Cache only summaries whose laps cover this share of the workout distance
# (guards against caching a workout that is still syncing).
MIN_LAP_COVERAGE = 0.90

# S2 goal-pace segments
GOAL_PACE_TOLERANCE = 0.05
SUPPORT_HR_MARGIN = 0.02
HR_ELASTICITY = 2.0          # relative speed change per unit of %LTHR
MAX_HR_ADJUST = 0.05
DECOUPLING_PENALTY_PER_PCT = 0.005
MAX_DECOUPLING_PENALTY = 0.03
LATE_SEGMENT_WEIGHT = 1.5

# S3 regression
STEADY_LAP_MIN_S = 480
STEADY_MIN_HR = 0.70
MIN_REGRESSION_POINTS = 5
MIN_HR_SPREAD = 0.08
MAX_EXTRAPOLATION = 0.05

# S5 load
SAFE_RAMP_PER_WEEK = 3.5
FITNESS_EXPONENT = 0.15
MAX_RACE_DAY_GAIN = 0.04

# S6 health
HEALTH_WINDOW_DAYS = 5
HEALTH_BASELINE_DAYS = 28
HRV_DROP = 0.07
RHR_RISE = 3.0
SLEEP_DROP_H = 0.75
HEAVY_TSB = -10.0
HEAVY_ATL_CTL = 1.15
RACE_WEEK_DAYS = 7
MAX_HEALTH_PENALTY = 0.02

# Blend
SIGNAL_WEIGHTS = {"threshold": 0.35, "goal_pace": 0.30, "hr_efficiency": 0.20, "race": 0.15}
STALE_EVIDENCE_DAYS = 21

RACE_RE = re.compile(r"\b(race|parkrun|time[- ]?trial|tt|wedstrijd)\b", re.IGNORECASE)
QUALITY_RE = re.compile(
    r"(interval|tempo|threshold|speed|reps|\bmp\b|marathon pace|race pace|canova|"
    r"progression|hills?\b|fartlek|vo2|\d+\s*x\s*\d+)",
    re.IGNORECASE,
)
RUN_SPORTS = {"run", "running", "trail run", "treadmill"}
_CONFIDENCE = ("Low", "Medium", "High")


# ------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------
def _num(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        value = value.get("value")
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_pace(speed_ms: Optional[float]) -> str:
    """m/s -> 'M:SS/km'."""
    if not speed_ms or speed_ms <= 0:
        return "-"
    return f"{format_seconds_hms(1000.0 / speed_ms)}/km"


def _fmt_day(d: Optional[date]) -> str:
    return d.strftime("%d %b") if d else "date n/a"


def _pct(hr: Optional[float], lthr: Optional[float]) -> Optional[float]:
    return hr / lthr if hr and lthr else None


# ------------------------------------------------------------------------------
# Inputs: thresholds, classification, workout summaries (cache format)
# ------------------------------------------------------------------------------
def extract_thresholds(settings_raw: Any) -> dict[str, Optional[float]]:
    """Run LTHR (bpm) and threshold speed (m/s) from tp_get_athlete_settings.

    Prefers the run-specific zone group (workoutTypeId 3) over the default (0).
    """
    payload = coerce_mcp_payload(settings_raw) if settings_raw else {}
    settings = payload.get("settings", payload) if isinstance(payload, dict) else {}

    def pick(groups: Any) -> Optional[float]:
        if not isinstance(groups, list):
            return None
        by_type = {g.get("workoutTypeId"): g for g in groups if isinstance(g, dict)}
        for type_id in (3, 0):
            value = _num((by_type.get(type_id) or {}).get("threshold"))
            if value and value > 0:
                return value
        return None

    return {
        "lthr": pick(settings.get("heartRateZones")),
        "threshold_speed": pick(settings.get("speedZones")),
    }


def classify_run(workout: dict, goal_label: str) -> str:
    """Returns 'race', 'long', 'quality' or 'easy' from title and distance.

    Precedence: race > clearly long (titled 'long' or >= ABSOLUTE_LONG_KM) >
    quality title > goal-relative long distance > easy.
    """
    title = str(workout.get("title") or "")
    km = _num(workout.get("distance_actual_km")) or 0.0
    long_km = DISTANCE_PROFILES[goal_label]["long_km"]
    if RACE_RE.search(title):
        return "race"
    if km >= ABSOLUTE_LONG_KM or "long" in title.lower():
        return "long"
    if QUALITY_RE.search(title):
        return "quality"
    if km >= long_km:
        return "long"
    return "easy"


def completed_runs(workouts: Optional[list[dict]], start: date, end: date) -> list[dict]:
    """Completed run workouts within [start, end], newest first."""
    runs = []
    for w in workouts or []:
        if str(w.get("sport", "")).lower() not in RUN_SPORTS:
            continue
        d = parse_date(w.get("date") or w.get("start_time"))
        if d is None or d < start or d > end:
            continue
        if not ((_num(w.get("distance_actual_km")) or 0) > 0 or (_num(w.get("duration_actual")) or 0) > 0):
            continue
        runs.append(w)
    return sorted(runs, key=lambda w: str(w.get("date") or ""), reverse=True)


def select_for_analysis(runs: list[dict], goal_label: str, max_n: int = MAX_ANALYSES) -> list[dict]:
    """Picks the most informative recent runs to analyse: races, quality, long runs."""
    buckets: dict[str, list[dict]] = {"race": [], "quality": [], "long": []}
    for w in runs:
        kind = classify_run(w, goal_label)
        if kind in buckets:
            buckets[kind].append(w)
    picked = buckets["race"][:2] + buckets["quality"][:4] + buckets["long"][:3]
    # Fill any spare slots with the remaining candidates, newest first.
    leftovers = [w for k in ("quality", "long", "race") for w in buckets[k] if w not in picked]
    picked += sorted(leftovers, key=lambda w: str(w.get("date") or ""), reverse=True)
    return picked[:max_n]


def _pace_seconds(value: Any) -> Optional[float]:
    v = _num(value)
    if not v or v <= 0:
        return None
    return v * 60.0 if v < 30 else v  # decimal min/km -> s/km


def summarize_analysis(raw: Any, workout: dict) -> Optional[dict]:
    """Compacts a tp_analyze_workout response into the cacheable workout summary."""
    payload = coerce_mcp_payload(raw) if raw else {}
    if not payload or payload.get("isError"):
        return None
    totals = payload.get("totals") or {}
    laps_raw = payload.get("lapData") or []
    if not laps_raw and not totals:
        return None

    laps, cum_km = [], 0.0
    for lap in laps_raw:
        if not isinstance(lap, dict):
            continue
        dur = _num(lap.get("TotalTimerTime")) or _num(lap.get("TotalMovingTime")) or _num(lap.get("TotalElapsedTime"))
        if not dur or dur <= 0:
            continue
        dist = _num(lap.get("TotalDistance")) or 0.0
        dist_km = dist / 1000.0 if dist > 100 else dist
        pace_s = _pace_seconds(lap.get("AveragePace"))
        ngp_s = _pace_seconds(lap.get("NormalizedGradedPace"))
        ref_pace = ngp_s or pace_s
        speed = 1000.0 / ref_pace if ref_pace else (dist_km * 1000.0 / dur if dist_km else None)
        laps.append({
            "duration_s": round(dur, 1),
            "distance_km": round(dist_km, 3),
            "pace_s": pace_s,
            "ngp_s": ngp_s,
            "speed_ms": round(speed, 4) if speed else None,
            "hr": _num(lap.get("AverageHeartRate")),
            "decoupling": _num(lap.get("PacePulseDecoupling")),
            "start_km": round(cum_km, 3),
        })
        cum_km += dist_km

    d = parse_date(workout.get("date") or workout.get("start_time"))
    return {
        "version": ANALYSIS_SCHEMA_VERSION,
        "workout_id": str(workout.get("id") or payload.get("workoutId") or ""),
        "date": d.isoformat() if d else None,
        "title": workout.get("title") or "",
        "distance_km": _num(workout.get("distance_actual_km")) or _num(totals.get("Distance")),
        "duration_s": (_num(workout.get("duration_actual")) or 0) * 3600 or _num(totals.get("Duration")),
        "pa_hr": _num(totals.get("Pa:Hr")),
        "laps": laps,
    }


def is_complete_summary(summary: Optional[dict]) -> bool:
    """True when laps cover >= MIN_LAP_COVERAGE of the workout distance (safe to cache)."""
    if not summary or not summary.get("laps"):
        return False
    total = _num(summary.get("distance_km"))
    if not total:
        return True
    covered = sum(_num(lap.get("distance_km")) or 0.0 for lap in summary["laps"])
    return covered >= MIN_LAP_COVERAGE * total


# ------------------------------------------------------------------------------
# Signals
# ------------------------------------------------------------------------------
def _evidence_date(summary: dict) -> Optional[date]:
    return parse_date(summary.get("date"))


def threshold_anchor(
    summaries: list[dict], goal_label: str, lthr: Optional[float], tp_speed: Optional[float]
) -> Optional[dict]:
    """S1: observed threshold speed from quality/race laps, reconciled with the TP setting."""
    total_s = weighted = hr_weighted = 0.0
    latest: Optional[date] = None
    if lthr:
        for s in summaries:
            if classify_run(s | {"distance_actual_km": s.get("distance_km")}, goal_label) not in ("quality", "race"):
                continue
            for lap in s.get("laps", []):
                pct = _pct(lap.get("hr"), lthr)
                d = lap.get("duration_s") or 0
                if (pct is None or not lap.get("speed_ms")
                        or not THRESHOLD_LAP_MIN_S <= d <= THRESHOLD_LAP_MAX_S
                        or not THRESHOLD_HR_BAND[0] <= pct <= THRESHOLD_HR_BAND[1]
                        or (tp_speed and abs(lap["speed_ms"] / tp_speed - 1) > THRESHOLD_PACE_BAND)):
                    continue
                total_s += d
                weighted += lap["speed_ms"] * d
                hr_weighted += pct * d
                ed = _evidence_date(s)
                latest = max(latest, ed) if latest and ed else (ed or latest)

    tp_str = f"TP setting {format_pace(tp_speed)}" if tp_speed else "no TP threshold pace"
    if total_s:
        observed = weighted / total_s
        mean_pct = hr_weighted / total_s
        evidence = (f"{round(total_s / 60)}' of threshold laps @ {format_pace(observed)}, "
                    f"{round(mean_pct * 100)}% LTHR (latest {_fmt_day(latest)}); {tp_str}")
        if tp_speed and abs(observed / tp_speed - 1) <= THRESHOLD_AGREEMENT:
            return {"speed": (observed + tp_speed) / 2, "source": "observed+tp", "evidence": evidence, "date": latest}
        return {"speed": observed, "source": "observed", "evidence": evidence, "date": latest}
    if tp_speed:
        return {"speed": tp_speed, "source": "tp", "date": None,
                "evidence": f"{tp_str} (no recent threshold laps to confirm it)"}
    return None


def durability(runs: list[dict], summaries: list[dict], goal_label: str) -> dict:
    """S4: durability tier from longest run and long-run Pa:Hr decoupling."""
    longest = max((_num(w.get("distance_actual_km")) or 0.0 for w in runs), default=0.0)
    min_long_s = 3600 if DISTANCE_PROFILES[goal_label]["km"] <= 10 else 5400
    pa_values = [
        s["pa_hr"] for s in summaries
        if s.get("pa_hr") is not None and (s.get("duration_s") or 0) >= min_long_s
    ]
    long_pa = sum(pa_values) / len(pa_values) if pa_values else None
    strong_km, weak_km = DURABILITY_LONGEST_KM[goal_label]
    if longest < weak_km or (long_pa is not None and long_pa > DECOUPLING_WEAK):
        tier = "weak"
    elif longest >= strong_km and (long_pa is None or long_pa <= DECOUPLING_OK):
        tier = "strong"
    else:
        tier = "moderate"
    pa_str = f"long-run Pa:Hr {long_pa:.1f}%" if long_pa is not None else "no long-run Pa:Hr"
    return {
        "tier": tier,
        "ratio": DISTANCE_PROFILES[goal_label]["ratios"][tier],
        "longest_km": longest,
        "long_pa_hr": long_pa,
        "evidence": f"Longest {longest:.0f} km, {pa_str} -> {tier}",
    }


def goal_pace_segments(
    summaries: list[dict], goal_label: str, ref_speeds: list[float], lthr: Optional[float]
) -> list[dict]:
    """S2: laps run near race pace, with HR, decoupling and fatigue position."""
    prof = DISTANCE_PROFILES[goal_label]
    ceiling = prof["race_hr"] + SUPPORT_HR_MARGIN
    refs = [r for r in ref_speeds if r]
    segments = []
    for s in summaries:
        for lap in s.get("laps", []):
            speed = lap.get("speed_ms")
            if not speed or (lap.get("duration_s") or 0) < prof["min_seg_s"]:
                continue
            if not any(abs(speed / r - 1) <= GOAL_PACE_TOLERANCE for r in refs):
                continue
            pct = _pct(lap.get("hr"), lthr)
            dec = lap.get("decoupling")
            implied = speed
            if pct is not None:
                adj = max(-MAX_HR_ADJUST, min(MAX_HR_ADJUST, HR_ELASTICITY * (prof["race_hr"] - pct)))
                implied *= 1 + adj
            if dec is not None and dec > DECOUPLING_OK:
                implied *= 1 - min(MAX_DECOUPLING_PENALTY, DECOUPLING_PENALTY_PER_PCT * (dec - DECOUPLING_OK))
            late = (lap.get("start_km") or 0) >= 0.5 * prof["long_km"]
            segments.append({
                "speed": speed,
                "implied_speed": implied,
                "duration_s": lap["duration_s"],
                "distance_km": lap.get("distance_km"),
                "pace_s": lap.get("pace_s"),
                "hr_pct": pct,
                "decoupling": dec,
                "start_km": lap.get("start_km"),
                "late": late,
                "supporting": (pct is None or pct <= ceiling) and (dec is None or dec <= DECOUPLING_OK),
                "date": _evidence_date(s),
                "title": s.get("title"),
            })
    return segments


def goal_pace_candidate(segments: list[dict]) -> Optional[dict]:
    if not segments:
        return None
    weights = [seg["duration_s"] * (LATE_SEGMENT_WEIGHT if seg["late"] else 1.0) for seg in segments]
    speed = sum(seg["implied_speed"] * w for seg, w in zip(segments, weights)) / sum(weights)
    best = max(segments, key=lambda seg: (seg["date"] or date.min, seg["duration_s"]))
    parts = [f"{best['distance_km']:.1f} km @ {format_pace(best['speed'])}"]
    if best.get("pace_s") and abs(1000.0 / best["pace_s"] - best["speed"]) / best["speed"] > 0.01:
        parts[0] += f" NGP (actual {format_seconds_hms(best['pace_s'])}/km)"
    if best["hr_pct"] is not None:
        parts.append(f"{round(best['hr_pct'] * 100)}% LTHR")
    if best["decoupling"] is not None:
        parts.append(f"Pa:Hr {best['decoupling']:.1f}%")
    if best["late"] and best.get("start_km"):
        parts.append(f"after {best['start_km']:.0f} km")
    mark = "✅" if best["supporting"] else "⚠️"
    n_support = sum(1 for seg in segments if seg["supporting"])
    evidence = (f"{', '.join(parts)} ({_fmt_day(best['date'])}) {mark}; "
                f"{n_support}/{len(segments)} segments supporting")
    return {"speed": speed, "evidence": evidence, "date": max(seg["date"] or date.min for seg in segments)}


def hr_efficiency_candidate(summaries: list[dict], goal_label: str, lthr: Optional[float]) -> Optional[dict]:
    """S3: weighted linear fit of speed vs HR over steady laps, evaluated at race HR."""
    if not lthr:
        return None
    pts = []
    for s in summaries:
        for lap in s.get("laps", []):
            hr, speed, d = lap.get("hr"), lap.get("speed_ms"), lap.get("duration_s") or 0
            if hr and speed and d >= STEADY_LAP_MIN_S and hr >= STEADY_MIN_HR * lthr:
                pts.append((hr, speed, d, _evidence_date(s)))
    if len(pts) < MIN_REGRESSION_POINTS:
        return None
    hrs = [p[0] for p in pts]
    if (max(hrs) - min(hrs)) < MIN_HR_SPREAD * lthr:
        return None
    w_sum = sum(p[2] for p in pts)
    mx = sum(p[0] * p[2] for p in pts) / w_sum
    my = sum(p[1] * p[2] for p in pts) / w_sum
    sxx = sum(p[2] * (p[0] - mx) ** 2 for p in pts)
    sxy = sum(p[2] * (p[0] - mx) * (p[1] - my) for p in pts)
    if sxx <= 0 or sxy <= 0:
        return None
    slope = sxy / sxx
    target_hr = DISTANCE_PROFILES[goal_label]["race_hr"] * lthr
    capped_hr = min(target_hr, max(hrs) + MAX_EXTRAPOLATION * lthr)
    speed = my + slope * (capped_hr - mx)
    if speed <= 0:
        return None
    dates = sorted(p[3] for p in pts if p[3])
    median_date = dates[len(dates) // 2] if dates else None
    cap_note = " (capped extrapolation)" if capped_hr < target_hr else ""
    return {
        "speed": speed,
        "date": median_date,
        "evidence": f"{len(pts)} steady laps, pace @ {round(target_hr)} bpm{cap_note}",
    }


def race_effort_candidate(
    runs: list[dict], goal_label: str, daily_pmc: Optional[list[dict]], ctl_now: Optional[float]
) -> Optional[dict]:
    """S7: Riegel on runs explicitly titled as races/time trials (fitness-adjusted)."""
    goal_km = DISTANCE_PROFILES[goal_label]["km"]
    best = None
    for w in runs:
        if classify_run(w, goal_label) != "race":
            continue
        km = _num(w.get("distance_actual_km")) or 0
        hrs = _num(w.get("duration_actual")) or 0
        if km <= 0 or hrs <= 0:
            continue
        d = parse_date(w.get("date"))
        projected_s = riegel_predict(hrs * 3600, km, goal_km)
        speed = goal_km * 1000 / projected_s
        if best is None or speed > best["speed"]:
            best = {"speed": speed, "date": d,
                    "evidence": f"'{w.get('title')}' {km:.1f} km in {format_seconds_hms(hrs * 3600)} ({_fmt_day(d)}), Riegel"}
    return best


def load_projection(ctl_now: Optional[float], trajectory_info: Optional[dict]) -> dict:
    """S5: projected race-day CTL at a safe ramp and the resulting speed factor (<= 1 is faster)."""
    info = trajectory_info or {}
    build_weeks = info.get("build_weeks")
    target = info.get("target_peak_ctl")
    if not ctl_now or build_weeks is None or not target:
        return {"ctl_now": ctl_now, "ctl_race": ctl_now, "time_factor": 1.0}
    ctl_race = max(ctl_now, min(target, ctl_now + SAFE_RAMP_PER_WEEK * build_weeks))
    factor = max(1 - MAX_RACE_DAY_GAIN, (ctl_now / ctl_race) ** FITNESS_EXPONENT)
    return {"ctl_now": ctl_now, "ctl_race": ctl_race, "time_factor": factor}


def health_readiness(
    dated_metrics: Optional[dict[str, list[tuple[date, float]]]],
    today: date,
    days_to_race: Optional[float],
    tsb: Optional[float],
    atl: Optional[float],
    ctl: Optional[float],
) -> dict:
    """S6: 5-day HRV/RHR/sleep vs 28-day baseline; load-aware in build, time-affecting in race week."""
    if not dated_metrics:
        return {"flag": "⚪", "markers": 0, "confidence_drop": False, "penalty": 0.0, "detail": "no health data"}
    recent_start = today - timedelta(days=HEALTH_WINDOW_DAYS - 1)
    base_start = today - timedelta(days=HEALTH_BASELINE_DAYS)

    def split(key: str) -> tuple[Optional[float], Optional[float]]:
        vals = dated_metrics.get(key) or []
        recent = [v for d, v in vals if d and d >= recent_start]
        base = [v for d, v in vals if d and base_start <= d < recent_start]
        avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        return avg(recent), avg(base)

    parts, markers = [], 0
    hrv_r, hrv_b = split("hrv")
    if hrv_r is not None and hrv_b:
        change = hrv_r / hrv_b - 1
        parts.append(f"HRV {change * 100:+.0f}% vs 28d")
        markers += change <= -HRV_DROP
    rhr_r, rhr_b = split("rhr")
    if rhr_r is not None and rhr_b is not None:
        parts.append(f"RHR {rhr_r - rhr_b:+.0f} bpm")
        markers += (rhr_r - rhr_b) >= RHR_RISE
    sl_r, sl_b = split("sleep")
    if sl_r is not None:
        parts.append(f"sleep {sl_r:.1f}h" + (f" ({(sl_r - sl_b) * 60:+.0f} min)" if sl_b else ""))
        markers += bool(sl_b) and (sl_b - sl_r) >= SLEEP_DROP_H

    if not parts:
        return {"flag": "⚪", "markers": 0, "confidence_drop": False, "penalty": 0.0, "detail": "no health data"}

    heavy = (tsb is not None and tsb <= HEAVY_TSB) or (bool(atl) and bool(ctl) and atl / ctl >= HEAVY_ATL_CTL)
    race_week = days_to_race is not None and 0 <= days_to_race <= RACE_WEEK_DAYS
    detail = ", ".join(parts)
    if markers >= 2:
        if race_week:
            penalty = min(MAX_HEALTH_PENALTY, MAX_HEALTH_PENALTY * markers / 3)
            return {"flag": "🔴", "markers": markers, "confidence_drop": True, "penalty": penalty,
                    "detail": f"{detail} — poor trend in race week (+{penalty * 100:.1f}% race-day)"}
        if heavy:
            return {"flag": "🟡", "markers": markers, "confidence_drop": False, "penalty": 0.0,
                    "detail": f"{detail} — training-induced, expected to clear in taper"}
        return {"flag": "🔴", "markers": markers, "confidence_drop": True, "penalty": 0.0,
                "detail": f"{detail} — not explained by training load (illness/stress?)"}
    if markers == 1:
        return {"flag": "🟡", "markers": 1, "confidence_drop": False, "penalty": 0.0, "detail": detail}
    return {"flag": "🟢", "markers": 0, "confidence_drop": False, "penalty": 0.0, "detail": detail}


# ------------------------------------------------------------------------------
# Projection
# ------------------------------------------------------------------------------
def _fitness_adjust(candidate: Optional[dict], daily_pmc, ctl_now) -> Optional[dict]:
    """Slows a candidate whose evidence predates a CTL drop (detraining since the session)."""
    if not candidate:
        return None
    factor = detraining_factor(ctl_on(daily_pmc, candidate.get("date")), ctl_now)
    if factor > 1.0:
        candidate = candidate | {
            "speed": candidate["speed"] / factor,
            "evidence": f"{candidate['evidence']} (fitness-adj. +{(factor - 1) * 100:.1f}%)",
        }
    return candidate


def project_race(
    goal_label: str,
    goal_minutes: Optional[int],
    runs: list[dict],
    summaries: list[dict],
    thresholds: dict,
    daily_pmc: Optional[list[dict]],
    fitness: dict,
    trajectory_info: Optional[dict],
    dated_metrics: Optional[dict],
    today: date,
    block_start: Any = None,
) -> Optional[dict]:
    """Blends all signals into 'today' and 'race-day' projections with drivers and confidence."""
    prof = DISTANCE_PROFILES[goal_label]
    km = prof["km"]
    lthr = thresholds.get("lthr")
    ctl_now, atl_now, tsb_now = fitness.get("ctl_end"), fitness.get("atl_end"), fitness.get("tsb_end")

    dur = durability(runs, summaries, goal_label)
    anchor = threshold_anchor(summaries, goal_label, lthr, thresholds.get("threshold_speed"))
    candidates: dict[str, Optional[dict]] = {}
    if anchor:
        candidates["threshold"] = _fitness_adjust(
            {"speed": anchor["speed"] * dur["ratio"], "date": anchor["date"],
             "evidence": anchor["evidence"]}, daily_pmc, ctl_now)

    goal_speed = km * 1000 / (goal_minutes * 60) if goal_minutes else None
    refs = [goal_speed, candidates.get("threshold", {}).get("speed") if candidates.get("threshold") else None]
    segments = goal_pace_segments(summaries, goal_label, [r for r in refs if r], lthr)
    candidates["goal_pace"] = _fitness_adjust(goal_pace_candidate(segments), daily_pmc, ctl_now)
    candidates["hr_efficiency"] = _fitness_adjust(hr_efficiency_candidate(summaries, goal_label, lthr), daily_pmc, ctl_now)
    candidates["race"] = _fitness_adjust(race_effort_candidate(runs, goal_label, daily_pmc, ctl_now), daily_pmc, ctl_now)
    active = {k: c for k, c in candidates.items() if c and c.get("speed")}
    if not active:
        return None

    w_total = sum(SIGNAL_WEIGHTS[k] for k in active)
    speed_today = sum(c["speed"] * SIGNAL_WEIGHTS[k] for k, c in active.items()) / w_total
    today_s = km * 1000 / speed_today
    cand_times = [km * 1000 / c["speed"] for c in active.values()]

    weeks_remaining = (trajectory_info or {}).get("weeks_remaining")
    days_to_race = weeks_remaining * 7 if weeks_remaining is not None else None
    load = load_projection(ctl_now, trajectory_info)
    health = health_readiness(dated_metrics, today, days_to_race, tsb_now, atl_now, ctl_now)
    race_day_s = today_s * load["time_factor"] * (1 + health["penalty"])

    # Confidence: agreement between signals, then downgrades.
    speeds = [c["speed"] for c in active.values()]
    spread = (max(speeds) - min(speeds)) / (sum(speeds) / len(speeds))
    if len(active) >= 3 and spread <= 0.03:
        level = 2
    elif len(active) >= 2 and spread <= 0.06:
        level = 1
    else:
        level = 0
    newest = max((c.get("date") for c in active.values() if c.get("date")), default=None)
    block = parse_date(block_start)
    stale = newest is None or (today - newest).days > STALE_EVIDENCE_DAYS or bool(block and newest < block)
    if health["confidence_drop"]:
        level -= 1
    if stale:
        level -= 1

    goal_s = goal_minutes * 60 if goal_minutes else None
    labels = {"threshold": "Threshold anchor", "goal_pace": "Goal-pace work",
              "hr_efficiency": "HR efficiency", "race": "Race efforts"}
    drivers = []
    for key in ("threshold", "goal_pace", "hr_efficiency", "race"):
        c = candidates.get(key)
        if c:
            implied = format_pace(c["speed"])
            if key == "threshold":
                implied += f" (×{dur['ratio']})"
            drivers.append((labels[key], c["evidence"], implied))
    drivers.append(("Durability", dur["evidence"], f"ratio {dur['ratio']}"))
    if ctl_now:
        tsb_str = f", TSB {tsb_now:+.0f}" if tsb_now is not None else ""
        drivers.append(("Load", f"CTL {ctl_now:.0f} → ~{load['ctl_race']:.0f} race day{tsb_str}",
                        f"race-day {(load['time_factor'] - 1) * 100:+.1f}%"))
    drivers.append(("Health", health["detail"], f"{health['flag']} readiness"))

    return {
        "goal_label": goal_label,
        "today_s": today_s,
        "race_day_s": race_day_s,
        "goal_s": goal_s,
        "gap_s": race_day_s - goal_s if goal_s else None,
        "range_s": (min(cand_times), max(cand_times)),
        "confidence": _CONFIDENCE[max(0, level)],
        "stale": stale,
        "readiness": health["flag"],
        "durability": dur["tier"],
        "signals": sorted(active),
        "drivers": drivers,
    }


# ------------------------------------------------------------------------------
# Formatting
# ------------------------------------------------------------------------------
def _gap(gap_s: float) -> str:
    sign = "+" if gap_s > 0 else "-" if gap_s < 0 else "±"
    return f"{sign}{format_seconds_hms(gap_s)}"


def format_projection_row(projection: Optional[dict], goal_label: Optional[str], weeks_str: str = "") -> str:
    """The 'Projected {goal}' row rendered directly under the CTL row."""
    if not goal_label:
        return "| **Projected Race Time** | `-` | No race distance in goal | - |\n"
    if not projection:
        return f"| **Projected {goal_label}** | `-` | Goal race: {goal_label}{weeks_str} | Insufficient recent run data |\n"
    goal_cell = f"Goal: `{format_seconds_hms(projection['goal_s'])}`" if projection.get("goal_s") else "Goal: -"
    gap = f"Gap (race day): `{_gap(projection['gap_s'])}` · " if projection.get("gap_s") is not None else ""
    lo, hi = projection["range_s"]
    stale = " · ⚠️ stale evidence" if projection.get("stale") else ""
    return (
        f"| **Projected {goal_label}** | Today `{format_seconds_hms(projection['today_s'])}` → "
        f"Race day `{format_seconds_hms(projection['race_day_s'])}` | {goal_cell}{weeks_str} | "
        f"{gap}Range `{format_seconds_hms(lo)}–{format_seconds_hms(hi)}` · "
        f"Confidence: {projection['confidence']} · Readiness {projection['readiness']}{stale} |\n"
    )


def format_drivers_table(projection: Optional[dict]) -> str:
    """The 'Projection drivers' evidence table shown under the metrics table."""
    if not projection:
        return ""
    lines = ["**Projection drivers:**", "", "| Driver | Evidence | Implied pace / effect |", "|---|---|---|"]
    for driver, evidence, implied in projection["drivers"]:
        lines.append(f"| {driver} | {evidence} | {implied} |")
    return "\n".join(lines)
