"""Weekly load capacity: how much running the runner has proven to tolerate.

Pure functions over the weekly rows of utils.trends. Capacity is never extrapolated above
the highest weekly volume actually run; higher targets are 'untested' with a build estimate.
"""

from statistics import mean, median
from typing import Optional

from .trends import spearman

# Load ratio: weekly TSS / mean of the previous 4 weeks.
RATIO_WEEKS = 4
DELOAD_BELOW, OVERLOAD_ABOVE = 0.9, 1.1
# Negative health markers (same thresholds as race_readiness.health_readiness).
HRV_DROP_PCT, RHR_RISE_BPM, SLEEP_DROP_MIN = -7.0, 3.0, -45.0
EF_DROP_PCT = -3.0
# Proven capacity.
LEVEL_STEP_KM = 10
MIN_STREAK_WEEKS = 3
MIN_TOLERATED_SHARE = 0.75
WITHIN_REACH_FACTOR = 1.15
BUILD_RATE = 1.10                   # max weekly growth while building
CUTBACK_EVERY = 4                   # every 4th build week is a cutback (no growth)
DEFAULT_TARGETS_KM = (50, 60, 70, 80, 100)


def add_load_ratio(rows: list[dict]) -> list[dict]:
    """Adds `load_ratio` and `load_band` (deload / steady / overload); None for the first 4 weeks."""
    for i, r in enumerate(rows):
        prior = [p["tss"] for p in rows[max(0, i - RATIO_WEEKS):i]]
        base = mean(prior) if len(prior) == RATIO_WEEKS else None
        r["load_ratio"] = round(r["tss"] / base, 2) if base else None
        r["load_band"] = (None if r["load_ratio"] is None else "deload" if r["load_ratio"] < DELOAD_BELOW
                          else "overload" if r["load_ratio"] > OVERLOAD_ABOVE else "steady")
    return rows


def health_markers(row: dict) -> int:
    return sum((
        row.get("hrv_delta_pct") is not None and row["hrv_delta_pct"] <= HRV_DROP_PCT,
        row.get("rhr_delta") is not None and row["rhr_delta"] >= RHR_RISE_BPM,
        row.get("sleep_delta_min") is not None and row["sleep_delta_min"] <= SLEEP_DROP_MIN,
    ))


def week_tolerated(row: dict, next_row: Optional[dict]) -> bool:
    """< 2 health markers and no niggle in the week and the next; easy EF not down > 3% next week."""
    for r in (row, next_row):
        if r is not None and (health_markers(r) >= 2 or r.get("niggle")):
            return False
    if next_row and row.get("easy_ef") and next_row.get("easy_ef"):
        if (next_row["easy_ef"] / row["easy_ef"] - 1) * 100 < EF_DROP_PCT:
            return False
    return True


def _longest_streak(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def volume_levels(rows: list[dict]) -> list[dict]:
    """Per 10-km level L: weeks >= L, longest consecutive streak >= L, tolerated share, medians."""
    weeks = [r for r in rows if r["complete"]]
    if not weeks:
        return []
    for i, r in enumerate(weeks):
        r["tolerated"] = week_tolerated(r, weeks[i + 1] if i + 1 < len(weeks) else None)
    top = int(max(r["km"] for r in weeks) // LEVEL_STEP_KM) * LEVEL_STEP_KM
    levels = []
    for level in range(LEVEL_STEP_KM, top + 1, LEVEL_STEP_KM):
        at = [r for r in weeks if r["km"] >= level]
        if not at:
            continue
        tolerated = sum(r["tolerated"] for r in at) / len(at)
        streak = _longest_streak([r["km"] >= level for r in weeks])

        def med(key):
            vals = [r[key] for r in at if r.get(key) is not None]
            return median(vals) if vals else None

        levels.append({"level": level, "weeks": len(at), "streak": streak, "tolerated_share": round(tolerated, 2),
                       "hrv_delta_pct": med("hrv_delta_pct"), "rhr_delta": med("rhr_delta"), "rpe": med("rpe"),
                       "proven": streak >= MIN_STREAK_WEEKS and tolerated >= MIN_TOLERATED_SHARE})
    return levels


def build_weeks(current_km: float, target_km: float) -> int:
    """Weeks to grow from current to target at <= 10%/week with every 4th week a cutback."""
    if current_km <= 0:
        return -1
    km, weeks = current_km, 0
    while km < target_km:
        weeks += 1
        if weeks % CUTBACK_EVERY:
            km *= BUILD_RATE
    return weeks


def capacity_outlook(rows: list[dict], levels: list[dict], targets=DEFAULT_TARGETS_KM) -> dict:
    complete = [r for r in rows if r["complete"]]
    proven = max((lv["level"] for lv in levels if lv["proven"]), default=None)
    max_km = max((r["km"] for r in complete), default=0.0)
    recent = [r["km"] for r in complete[-3:]]
    current = round(mean(recent), 1) if recent else 0.0
    out = []
    for t in targets:
        if proven and t <= proven:
            status = "proven"
        elif proven and t <= proven * WITHIN_REACH_FACTOR:
            status = "within reach"
        elif t > max_km:
            status = "untested"
        else:
            status = "run, not proven"
        out.append({"target": t, "status": status,
                    "build_weeks": 0 if current >= t else build_weeks(current, t)})
    return {"proven_km": proven, "max_km": max_km, "current_km": current, "targets": out}


def ratio_vs_next_hrv(rows: list[dict]) -> tuple[Optional[float], int]:
    pairs = [(r["load_ratio"], n["hrv_delta_pct"]) for r, n in zip(rows, rows[1:])
             if r.get("load_ratio") is not None and n.get("hrv_delta_pct") is not None]
    return spearman([p[0] for p in pairs], [p[1] for p in pairs]), len(pairs)


def _f(value, fmt="{:.0f}", suffix=""):
    return fmt.format(value) + suffix if value is not None else "-"


def format_levels_table(levels: list[dict]) -> str:
    if not levels:
        return ""
    lines = ["**Weekly volume levels** (complete weeks; tolerated = no 2+ negative health markers, no niggle, "
             "easy EF held, in that week and the next):", "",
             "| Level | Weeks | Longest streak | Tolerated | HRV Δ | RHR Δ | RPE | Proven |",
             "|---|---|---|---|---|---|---|---|"]
    for lv in levels:
        lines.append(f"| >= {lv['level']} km | {lv['weeks']} | {lv['streak']} | {lv['tolerated_share'] * 100:.0f}% "
                     f"| {_f(lv['hrv_delta_pct'], '{:+.0f}', '%')} | {_f(lv['rhr_delta'], '{:+.0f}')} "
                     f"| {_f(lv['rpe'], '{:.1f}')} | {'yes' if lv['proven'] else 'no'} |")
    return "\n".join(lines)


def format_outlook(outlook: dict, rho: Optional[float], n_pairs: int) -> str:
    proven = f"{outlook['proven_km']} km/week" if outlook["proven_km"] else "none yet"
    lines = [f"Load capacity: proven {proven}; highest week {outlook['max_km']:.0f} km; "
             f"current (last 3 complete weeks) {outlook['current_km']:.0f} km/week."]
    for t in outlook["targets"]:
        weeks = f", ~{t['build_weeks']} build weeks from current" if t["build_weeks"] > 0 else ""
        lines.append(f"- {t['target']} km/week: {t['status']}{weeks}")
    lines.append(f"Load ratio (weekly TSS / prior 4-week mean) vs next-week HRV: "
                 f"{'rho ' + str(rho) if rho is not None else 'insufficient'} (n={n_pairs})")
    return "\n".join(lines)
