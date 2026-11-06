from datetime import date, timedelta
from statistics import median
from typing import Optional

from ....shared.hr_pace_fit import (
    THRESHOLD_AGREEMENT,
    fit_speed_vs_hr,
    is_hot,
    steady_lap_points,
    threshold_lap_stats,
)
from ....shared.units import fmt_pace

PACING_WEEKS = 6
MAX_EXTRAPOLATION_LTHR = 0.05       # zone-2 paces further outside the fitted HR range are flagged

# Intent bands by the step target midpoint (% of threshold pace).
BANDS = (("easy", 0, 80), ("steady", 80, 87), ("marathon", 87, 93), ("threshold", 93, 102), ("vo2", 102, 1000))
WORKOUT_BANDS = ("marathon", "threshold", "vo2")
HR_CEILING = {"marathon": 0.87, "threshold": 0.92}   # max median %LTHR for "room to go faster"
MIN_SESSIONS = 3
MIN_REP_S = 60                      # shorter reps (strides) are neuromuscular, not pace work
HIT_RATE_ROOM = 0.8
DECOUPLING_ROOM = 3.0
DECOUPLING_TOO_HARD = 5.0
MAX_SPEEDUP = 0.03                  # suggested speed-up is capped at 3%
PACE_RATIOS = (("Marathon", 0.91), ("Threshold", 1.00), ("VO2max", 1.07))
# LTHR evidence (Friel): a sustained effort of >= 20 min at >= 97% LTHR confirms the setting.
LTHR_EVIDENCE_MIN_S = 20 * 60
LTHR_CONFIRMED_PCT = 0.97


def recent_runs(records: list[dict], today: date, weeks: int = PACING_WEEKS) -> list[dict]:
    start = (today - timedelta(weeks=weeks)).isoformat()
    return [r for r in records if r.get("kind") and r.get("laps") and (r.get("date") or "") >= start]


def _pace(speed: Optional[float]) -> Optional[float]:
    return 1000.0 / speed if speed and speed > 0 else None


def hr_pace_model(runs: list[dict], lthr: Optional[float]) -> Optional[dict]:
    """Weighted speed-vs-HR fit over steady laps of non-hot runs (shared S3 math)."""
    if not lthr:
        return None
    return fit_speed_vs_hr(steady_lap_points([r for r in runs if not is_hot(r)], lthr), lthr)


def pace_at_hr(model: dict, hr: float) -> Optional[float]:
    return _pace(model["my"] + model["slope"] * (hr - model["mx"]))


def easy_pace_range(model: Optional[dict], zones: list[dict], lthr: Optional[float]) -> Optional[dict]:
    """Pace range for TP HR zone 2 via the model (fast end at the zone-2 ceiling)."""
    if not model or len(zones) < 2 or not zones[1]["min"] or not zones[1]["max"] or not lthr:
        return None
    z2 = zones[1]
    fast, slow = pace_at_hr(model, z2["max"]), pace_at_hr(model, z2["min"])
    if not fast or not slow:
        return None
    margin = MAX_EXTRAPOLATION_LTHR * lthr
    extrapolated = z2["min"] < model["hr_min"] - margin or z2["max"] > model["hr_max"] + margin
    return {"hr_lo": z2["min"], "hr_hi": z2["max"], "fast_s": fast, "slow_s": slow,
            "extrapolated": extrapolated, "laps": model["n"]}


def easy_discipline(runs: list[dict], zones: list[dict], lthr: Optional[float]) -> Optional[dict]:
    """Share of easy-run lap time above the zone-2 ceiling, and median easy-run HR as %LTHR."""
    if len(zones) < 2 or not zones[1]["max"]:
        return None
    easy = [r for r in runs if r.get("kind") == "easy"]
    total = above = 0.0
    for r in easy:
        for lap in r["laps"]:
            d = lap.get("duration_s") or 0
            total += d
            above += d if (lap.get("hr") or 0) > zones[1]["max"] else 0
    pcts = [r["pct_lthr"] for r in easy if r.get("pct_lthr")]
    if not total:
        return None
    return {"runs": len(easy), "above_z2_pct": round(above / total * 100, 1),
            "median_pct_lthr": round(median(pcts) * 100, 1) if pcts else None}


def threshold_estimate(runs: list[dict], lthr: Optional[float], tp_speed: Optional[float]) -> Optional[dict]:
    """Observed threshold laps (quality/race runs) vs the TP threshold pace; reconciled speed."""
    stats = threshold_lap_stats([r for r in runs if r.get("kind") in ("quality", "race")], lthr, tp_speed)
    if not stats and not tp_speed:
        return None
    observed = stats["speed"] if stats else None
    if observed and tp_speed:
        diff = observed / tp_speed - 1
        speed = (observed + tp_speed) / 2 if abs(diff) <= THRESHOLD_AGREEMENT else observed
    else:
        diff, speed = None, observed or tp_speed
    return {"speed": speed, "observed_speed": observed, "tp_speed": tp_speed, "diff_pct": diff,
            "minutes": round(stats["total_s"] / 60) if stats else 0,
            "latest": stats["latest"].isoformat() if stats and stats["latest"] else None}


def lthr_evidence(runs: list[dict], lthr: Optional[float]) -> Optional[dict]:
    """Highest average HR over any lap or structured step >= 20 min, compared with the TP LTHR.

    Sustained training efforts are a lower bound for LTHR: 'confirmed' when one reached
    >= 97% LTHR, otherwise 'unconfirmed' (the setting may be too high; test to be sure).
    """
    if not lthr:
        return None
    best = None
    for r in runs:
        for item in [*(r.get("laps") or []), *(r.get("work_intervals") or [])]:
            hr, d = item.get("hr"), item.get("duration_s") or 0
            if hr and d >= LTHR_EVIDENCE_MIN_S and (best is None or hr > best["best_hr"]):
                best = {"best_hr": hr, "duration_s": d, "date": r.get("date"), "title": r.get("title") or ""}
    if best is None:
        return {"lthr": lthr, "best_hr": None, "best_pct": None, "status": "unconfirmed"}
    pct = best["best_hr"] / lthr
    return {"lthr": lthr, **best, "best_pct": pct,
            "status": "confirmed" if pct >= LTHR_CONFIRMED_PCT else "unconfirmed"}


def intent_band(pct: Optional[float]) -> Optional[str]:
    if pct is None:
        return None
    return next(name for name, lo, hi in BANDS if lo <= pct < hi)


def _target_slow_end(interval: dict, threshold_speed: Optional[float]) -> Optional[float]:
    """Slowest pace (s/km) that still hits a % threshold-pace target, using the threshold in use then."""
    lo = (interval.get("target") or {}).get("lo")
    return 1000.0 / threshold_speed / (lo / 100.0) if lo and threshold_speed else None


def workout_calibration(runs: list[dict]) -> dict[str, dict]:
    """Per workout band: sessions, reps, pace hit rate, median %LTHR / decoupling / pace / HR."""
    groups: dict[str, list[tuple[str, dict, Optional[float]]]] = {}
    for r in runs:
        thr_speed = (r.get("thresholds") or {}).get("threshold_speed")
        for iv in r.get("work_intervals") or []:
            target = iv.get("target") or {}
            if (target.get("metric") != "percentOfThresholdPace" or target.get("lo") is None
                    or (iv.get("duration_s") or 0) < MIN_REP_S):
                continue
            band = intent_band((target["lo"] + target["hi"]) / 2)
            if band in WORKOUT_BANDS:
                groups.setdefault(band, []).append((r["workout_id"], iv, _target_slow_end(iv, thr_speed)))
    out = {}
    for band, items in groups.items():
        judged = [(iv, slow) for _, iv, slow in items if iv.get("pace_s") and slow]
        pcts = [iv["pct_lthr"] for _, iv, _ in items if iv.get("pct_lthr")]
        decs = [iv["decoupling"] for _, iv, _ in items if iv.get("decoupling") is not None]
        paces = [iv["pace_s"] for _, iv, _ in items if iv.get("pace_s")]
        hrs = [iv["hr"] for _, iv, _ in items if iv.get("hr")]
        out[band] = {
            "sessions": len({wid for wid, _, _ in items}),
            "reps": len(items),
            "hit_rate": round(sum(iv["pace_s"] <= slow + 0.5 for iv, slow in judged) / len(judged), 2) if judged else None,
            "median_pct_lthr": median(pcts) if pcts else None,
            "median_decoupling": median(decs) if decs else None,
            "median_pace_s": median(paces) if paces else None,
            "median_hr": median(hrs) if hrs else None,
        }
    return out


def headroom(band: str, cal: dict, model: Optional[dict], lthr: Optional[float]) -> dict:
    """Deterministic verdict: 'room to go faster' / 'on target' / 'too hard' / 'insufficient' / 'n/a'."""
    ceiling = HR_CEILING.get(band)
    if ceiling is None:
        return {"verdict": "n/a (no HR rule for short reps)"}
    pct, dec, hit = cal.get("median_pct_lthr"), cal.get("median_decoupling"), cal.get("hit_rate")
    if cal["sessions"] < MIN_SESSIONS or pct is None:
        return {"verdict": "insufficient"}
    if pct > ceiling or (dec is not None and dec > DECOUPLING_TOO_HARD):
        return {"verdict": "too hard"}
    if hit is not None and hit >= HIT_RATE_ROOM and (dec is None or dec < DECOUPLING_ROOM):
        suggestion = None
        if model and lthr and cal.get("median_pace_s") and cal.get("median_hr"):
            speed = 1000.0 / cal["median_pace_s"]
            gain = min(MAX_SPEEDUP * speed, max(0.0, model["slope"] * (ceiling * lthr - cal["median_hr"])))
            suggestion = round(cal["median_pace_s"] - 1000.0 / (speed + gain))
        return {"verdict": "room to go faster", "faster_s_per_km": suggestion}
    return {"verdict": "on target"}


def training_paces(threshold_speed: Optional[float], easy: Optional[dict]) -> list[tuple[str, str]]:
    """(name, pace) rows: easy range from the HR model, the rest from the threshold estimate."""
    rows = []
    if easy:
        rows.append((f"Easy (Z2 {int(easy['hr_lo'])}-{int(easy['hr_hi'])} bpm)",
                     f"{fmt_pace(easy['fast_s'])[:-3]}–{fmt_pace(easy['slow_s'])}"))
    if threshold_speed:
        rows += [(name, fmt_pace(1000.0 / (threshold_speed * ratio))) for name, ratio in PACE_RATIOS]
    return rows


def analyse_pacing(records: list[dict], thresholds: dict, zones: list[dict], today: date) -> dict:
    runs = recent_runs(records, today)
    lthr, tp_speed = thresholds.get("lthr"), thresholds.get("threshold_speed")
    model = hr_pace_model(runs, lthr)
    easy = easy_pace_range(model, zones, lthr)
    thr = threshold_estimate(runs, lthr, tp_speed)
    cal = workout_calibration(runs)
    lthr_check = lthr_evidence([r for r in records if r.get("kind") and r.get("laps")], lthr)
    verdicts = {b: {**c, **headroom(b, c, model, lthr)} for b, c in cal.items()}
    if lthr_check and lthr_check["status"] == "unconfirmed":
        for v in verdicts.values():
            if v["verdict"] == "room to go faster":
                v["verdict"] = "room to go faster (LTHR unconfirmed)"
    return {
        "runs": len(runs),
        "model": model,
        "easy": easy,
        "discipline": easy_discipline(runs, zones, lthr),
        "threshold": thr,
        "lthr_check": lthr_check,
        "calibration": verdicts,
        "paces": training_paces(thr["speed"] if thr else None, easy),
    }


def _pct(v: Optional[float]) -> str:
    return f"{v * 100:.0f}%" if v is not None else "-"


def format_pacing_tables(p: dict) -> str:
    lines = []
    if p["paces"]:
        lines += ["**Training paces** (threshold estimate + HR model, last 6 weeks):", "",
                  "| Pace | Target |", "|---|---|"]
        lines += [f"| {name} | {pace} |" for name, pace in p["paces"]]
    if p["calibration"]:
        lines += ["", "**Workout calibration** (structured steps by target, last 6 weeks):", "",
                  "| Band | Sessions (reps) | Pace hit | Median %LTHR | Median Pa:Hr | Verdict |",
                  "|---|---|---|---|---|---|"]
        for band in WORKOUT_BANDS:
            c = p["calibration"].get(band)
            if not c:
                continue
            verdict = c["verdict"] + (f" (~{c['faster_s_per_km']} s/km)" if c.get("faster_s_per_km") else "")
            dec = f"{c['median_decoupling']:.1f}%" if c["median_decoupling"] is not None else "-"
            lines.append(f"| {band.capitalize()} | {c['sessions']} ({c['reps']}) | {_pct(c['hit_rate'])} "
                         f"| {_pct(c['median_pct_lthr'])} | {dec} | {verdict} |")
    return "\n".join(lines)


def format_pacing_details(p: dict) -> str:
    lines = [f"Pacing evidence: {p['runs']} runs with laps in the last {PACING_WEEKS} weeks."]
    e = p["easy"]
    if e:
        flag = " (extrapolated beyond the fitted HR range)" if e["extrapolated"] else ""
        lines.append(f"- Easy pace (TP zone 2 {int(e['hr_lo'])}-{int(e['hr_hi'])} bpm, {e['laps']} steady laps, "
                     f"hot runs excluded): {fmt_pace(e['fast_s'])} to {fmt_pace(e['slow_s'])}{flag}")
    else:
        lines.append("- Easy pace: not enough steady laps with HR spread for a reliable HR->pace model")
    d = p["discipline"]
    if d:
        lines.append(f"- Easy-run discipline: {d['runs']} easy runs, {d['above_z2_pct']}% of lap time above zone 2, "
                     f"median avg HR {d['median_pct_lthr']}% LTHR")
    lc = p.get("lthr_check")
    if lc:
        if lc["best_hr"]:
            evidence = (f"highest 20+ min effort {lc['best_hr']:.0f} bpm ({lc['best_pct'] * 100:.0f}%) on "
                        f"{lc['date']} '{lc['title']}'")
        else:
            evidence = "no lap or step of 20+ min with HR"
        advice = "" if lc["status"] == "confirmed" else (
            f"; no sustained effort >= {LTHR_CONFIRMED_PCT * 100:.0f}%: confirm with a 30-min time trial or a 10K race")
        lines.append(f"- LTHR check: TP LTHR {lc['lthr']:.0f} bpm; {evidence} -> {lc['status']}{advice}")
    t = p["threshold"]
    if t:
        if t["observed_speed"] and t["tp_speed"]:
            direction = "too fast" if t["diff_pct"] < 0 else "too slow"
            agree = "agrees" if abs(t["diff_pct"]) <= THRESHOLD_AGREEMENT else f"TP setting ~{abs(t['diff_pct']) * 100:.0f}% {direction}"
            lines.append(f"- Threshold: observed {fmt_pace(1000 / t['observed_speed'])} over {t['minutes']} min of "
                         f"threshold laps (latest {t['latest']}) vs TP setting {fmt_pace(1000 / t['tp_speed'])} -> {agree}")
        elif t["tp_speed"]:
            lines.append(f"- Threshold: TP setting {fmt_pace(1000 / t['tp_speed'])}; no threshold laps in the window to confirm it")
    return "\n".join(lines)
