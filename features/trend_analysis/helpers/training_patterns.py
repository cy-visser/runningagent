from statistics import mean, median
from typing import Optional

LONG_RUN_PATTERN_SHARE = 0.30      # long-run week: longest run >= 30% of the week's running km
MIN_GROUP_N = 4


def _avg(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def _f(value: Optional[float], fmt: str = "{:.0f}", suffix: str = "") -> str:
    return fmt.format(value) + suffix if value is not None else "-"


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


def format_patterns(patterns: list[dict]) -> str:
    lines = ["Training patterns (associations, not causes; outcome = next-week easy-EF change and HRV vs 28d "
             "baseline; same-week RPE):"]
    for p in patterns:
        parts = []
        for label, o in ((p["a"], p["a_out"]), (p["b"], p["b_out"])):
            parts.append(f"{label}: n={o['n']}, EF {_f(o['ef_change_pct'], '{:+.1f}', '%')}, "
                         f"HRV {_f(o['next_hrv_pct'], '{:+.0f}', '%')}, RPE {_f(o['rpe'], '{:.1f}')}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)
