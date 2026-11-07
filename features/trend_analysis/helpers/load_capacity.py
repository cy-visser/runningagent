from statistics import mean, median
from typing import Optional

# Load ratio: weekly TSS / mean of the previous 4 weeks.
RATIO_WEEKS = 4
# Negative health markers (same thresholds as health_readiness).
HRV_DROP_PCT, RHR_RISE_BPM, SLEEP_DROP_MIN = -7.0, 3.0, -45.0
EF_DROP_PCT = -3.0
# Proven capacity (web-report badges only; the LLM text shows the underlying facts).
LEVEL_STEP_KM = 10
MIN_STREAK_WEEKS = 3
MIN_TOLERATED_SHARE = 0.75
WITHIN_REACH_FACTOR = 1.15
DEFAULT_TARGETS_KM = (50, 60, 70, 80, 100)


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


def add_load_ratio(rows: list[dict]) -> list[dict]:
    """Adds `load_ratio` (weekly TSS / prior 4-week mean); None for the first 4 weeks."""
    for i, r in enumerate(rows):
        prior = [p["tss"] for p in rows[max(0, i - RATIO_WEEKS):i]]
        base = mean(prior) if len(prior) == RATIO_WEEKS else None
        r["load_ratio"] = round(r["tss"] / base, 2) if base else None
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
    """Per 10-km level L: weeks >= L, longest consecutive streak >= L, niggle weeks, tolerated share, medians."""
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

        levels.append({"level": level, "weeks": len(at), "streak": streak,
                       "niggle_weeks": sum(1 for r in at if r.get("niggle")), "tolerated_share": round(tolerated, 2),
                       "hrv_delta_pct": med("hrv_delta_pct"), "rhr_delta": med("rhr_delta"), "rpe": med("rpe"),
                       "proven": streak >= MIN_STREAK_WEEKS and tolerated >= MIN_TOLERATED_SHARE})
    return levels


def capacity_outlook(rows: list[dict], levels: list[dict], targets=DEFAULT_TARGETS_KM) -> dict:
    """Per weekly-km target: weeks at or above it, longest streak and the km gap from the current level.

    `status` and `proven_km` feed the web badges only. No build-time estimate: how fast this runner can safely close the gap is the coach's judgement.
    """
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
        out.append({"target": t, "status": status, "gap_km": round(max(0.0, t - current), 1),
                    "weeks_at": sum(1 for r in complete if r["km"] >= t),
                    "streak": _longest_streak([r["km"] >= t for r in complete])})
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
    lines = ["**Weekly volume levels** (complete weeks at or above each level; HRV Δ / RHR Δ / RPE are medians "
             "of those weeks vs the 28-day baseline; niggle weeks = weeks with a niggle in the athlete comments):", "",
             "| Level | Weeks | Longest streak | Niggle weeks | HRV Δ | RHR Δ | RPE |",
             "|---|---|---|---|---|---|---|"]
    for lv in levels:
        lines.append(f"| >= {lv['level']} km | {lv['weeks']} | {lv['streak']} | {lv['niggle_weeks']} "
                     f"| {_f(lv['hrv_delta_pct'], '{:+.0f}', '%')} | {_f(lv['rhr_delta'], '{:+.0f}')} "
                     f"| {_f(lv['rpe'], '{:.1f}')} |")
    return "\n".join(lines)


def format_outlook(outlook: dict, rho: Optional[float], n_pairs: int) -> str:
    lines = [f"Load capacity: highest week {outlook['max_km']:.0f} km; "
             f"current (last 3 complete weeks) {outlook['current_km']:.0f} km/week."]
    for t in outlook["targets"]:
        gap = f", +{t['gap_km']:.1f} km/week above current" if t["gap_km"] > 0 else ""
        lines.append(f"- {t['target']} km/week: {t['weeks_at']} weeks at or above "
                     f"(longest streak {t['streak']}){gap}")
    lines.append(f"Load ratio (weekly TSS / prior 4-week mean) vs next-week HRV: "
                 f"{'rho ' + str(rho) if rho is not None else 'insufficient'} (n={n_pairs})")
    return "\n".join(lines)
