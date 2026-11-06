from datetime import date
from typing import Any, Optional

from ....shared.dates import parse_date
from ....shared.goal_distance import DISTANCE_PROFILES
from ....shared.hr_pace_fit import (
    MAX_EXTRAPOLATION,
    THRESHOLD_AGREEMENT,
    evidence_date,
    fit_speed_vs_hr,
    pct_of_lthr,
    steady_lap_points,
    threshold_lap_stats,
)
from ....shared.race_equivalents import riegel_predict
from ....shared.units import format_seconds_hms
from .goal_trajectory import SAFE_RAMP_PER_WEEK
from .health_flag import (
    _fmt_day,
    ctl_on,
    detraining_factor,
    health_readiness,
    recent_hard_effort,
)
from .projection_evidence import _num, classify_run

# Durability tiers: (strong_min_longest_km, weak_below_longest_km) per distance.
DURABILITY_LONGEST_KM = {
    "5K": (10.0, 6.0), "10K": (14.0, 10.0), "10 Mile": (19.0, 14.0),
    "Half Marathon": (20.0, 16.0), "Marathon": (30.0, 24.0),
}
DECOUPLING_OK = 5.0       # % Pa:Hr considered aerobically stable
DECOUPLING_WEAK = 8.0     # % Pa:Hr indicating poor durability

# S2 goal-pace segments
GOAL_PACE_TOLERANCE = 0.05
SUPPORT_HR_MARGIN = 0.02
HR_ELASTICITY = 2.0          # relative speed change per unit of %LTHR
MAX_HR_ADJUST = 0.05
DECOUPLING_PENALTY_PER_PCT = 0.005
MAX_DECOUPLING_PENALTY = 0.03
LATE_SEGMENT_WEIGHT = 1.5

# S5 load
FITNESS_EXPONENT = 0.15
MAX_RACE_DAY_GAIN = 0.04

# Blend
SIGNAL_WEIGHTS = {"threshold": 0.35, "goal_pace": 0.30, "hr_efficiency": 0.20, "race": 0.15}
STALE_EVIDENCE_DAYS = 21

_CONFIDENCE = ("Low", "Medium", "High")


def format_pace(speed_ms: Optional[float]) -> str:
    """m/s -> 'M:SS/km'."""
    if not speed_ms or speed_ms <= 0:
        return "-"
    return f"{format_seconds_hms(1000.0 / speed_ms)}/km"


def threshold_anchor(
    summaries: list[dict], goal_label: str, lthr: Optional[float], tp_speed: Optional[float]
) -> Optional[dict]:
    """S1: observed threshold speed from quality/race laps, reconciled with the TP setting."""
    quality = [
        s for s in summaries
        if classify_run(s | {"distance_actual_km": s.get("distance_km")}, goal_label) in ("quality", "race")
    ]
    stats = threshold_lap_stats(quality, lthr, tp_speed)

    tp_str = f"TP setting {format_pace(tp_speed)}" if tp_speed else "no TP threshold pace"
    if stats:
        observed, latest = stats["speed"], stats["latest"]
        evidence = (f"{round(stats['total_s'] / 60)}' of threshold laps @ {format_pace(observed)}, "
                    f"{round(stats['pct'] * 100)}% LTHR (latest {_fmt_day(latest)}); {tp_str}")
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
            pct = pct_of_lthr(lap.get("hr"), lthr)
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
                "date": evidence_date(s),
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
    pts = steady_lap_points(summaries, lthr)
    fit = fit_speed_vs_hr(pts, lthr)
    if not fit:
        return None
    target_hr = DISTANCE_PROFILES[goal_label]["race_hr"] * lthr
    capped_hr = min(target_hr, fit["hr_max"] + MAX_EXTRAPOLATION * lthr)
    speed = fit["my"] + fit["slope"] * (capped_hr - fit["mx"])
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


def race_effort_candidate(runs: list[dict], goal_label: str) -> Optional[dict]:
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
    goal_minutes: Optional[float],
    runs: list[dict],
    summaries: list[dict],
    thresholds: dict,
    daily_pmc: Optional[list[dict]],
    fitness: dict,
    trajectory_info: Optional[dict],
    dated_metrics: Optional[dict],
    today: date,
    block_start: Any = None,
    race_dates: Any = (),
) -> Optional[dict]:
    """Blends all signals into 'today' and 'race-day' projections with drivers and confidence."""
    prof = DISTANCE_PROFILES[goal_label]
    km = prof["km"]
    lthr = thresholds.get("lthr")
    ctl_now, atl_now, tsb_now = fitness.get("ctl_end"), fitness.get("atl_end"), fitness.get("tsb_end")
    info = trajectory_info or {}
    in_taper = info.get("phase") == "taper"
    # In the taper CTL falls by design (fatigue sheds faster than fitness): judge evidence and
    # race-day load against the fitness banked before the taper, not today's declining CTL.
    ctl_ref = max(ctl_now or 0.0, info.get("pre_taper_ctl") or 0.0) if in_taper else ctl_now

    dur = durability(runs, summaries, goal_label)
    anchor = threshold_anchor(summaries, goal_label, lthr, thresholds.get("threshold_speed"))
    candidates: dict[str, Optional[dict]] = {}
    if anchor:
        candidates["threshold"] = _fitness_adjust(
            {"speed": anchor["speed"] * dur["ratio"], "date": anchor["date"],
             "evidence": anchor["evidence"]}, daily_pmc, ctl_ref)

    goal_speed = km * 1000 / (goal_minutes * 60) if goal_minutes else None
    refs = [goal_speed, candidates.get("threshold", {}).get("speed") if candidates.get("threshold") else None]
    segments = goal_pace_segments(summaries, goal_label, [r for r in refs if r], lthr)
    candidates["goal_pace"] = _fitness_adjust(goal_pace_candidate(segments), daily_pmc, ctl_ref)
    candidates["hr_efficiency"] = _fitness_adjust(hr_efficiency_candidate(summaries, goal_label, lthr), daily_pmc, ctl_ref)
    candidates["race"] = _fitness_adjust(race_effort_candidate(runs, goal_label), daily_pmc, ctl_ref)
    active = {k: c for k, c in candidates.items() if c and c.get("speed")}
    if not active:
        return None

    w_total = sum(SIGNAL_WEIGHTS[k] for k in active)
    speed_today = sum(c["speed"] * SIGNAL_WEIGHTS[k] for k, c in active.items()) / w_total
    today_s = km * 1000 / speed_today
    cand_times = [km * 1000 / c["speed"] for c in active.values()]

    weeks_remaining = info.get("weeks_remaining")
    days_to_race = weeks_remaining * 7 if weeks_remaining is not None else None
    load = load_projection(ctl_ref, trajectory_info)
    effort = recent_hard_effort(runs, today, daily_pmc, race_dates)
    health = health_readiness(dated_metrics, today, days_to_race, tsb_now, atl_now, ctl_now, effort)
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
        load_evidence = (
            f"Taper: peak CTL {ctl_ref:.0f} banked (now {ctl_now:.0f}){tsb_str}" if in_taper
            else f"CTL {ctl_now:.0f} → ~{load['ctl_race']:.0f} race day{tsb_str}"
        )
        drivers.append(("Load", load_evidence, f"race-day {(load['time_factor'] - 1) * 100:+.1f}%"))
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
