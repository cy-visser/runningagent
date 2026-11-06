from typing import Optional

from ....shared.goal_distance import DEFAULT_PEAK_CTL, DEFAULT_PEAK_RANGE
from ....shared.hr_pace_fit import LT_FIT_WEEKS
from ....shared.units import fmt_clock
from .goal_trajectory import TAPER_WEEKS, ramp_status
from .lt_paces import lt_verdict
from .race_projection import format_drivers_table, format_projection_row

PROGRESS_BAR_SEGMENTS = 10
# Typical race-day form (TSB) after a good taper; shown in the CTL row during the taper.
RACE_DAY_TSB_TARGET = (5, 15)


def format_lt_rows(lt: Optional[dict]) -> str:
    """Pace @ LT1 / LT2 rows (current 4-week HR->pace fit vs the previous 4 weeks)."""
    if not lt:
        return ""
    now, prev = lt.get("now") or {}, lt.get("prev") or {}
    rows = ""
    for key, label, hr_label in (
        ("lt1", "Pace @ LT1", f"top Z2, {round(lt['lt1_hr'])} bpm" if lt.get("lt1_hr") else "top Z2"),
        ("lt2", "Pace @ LT2", f"LTHR {round(lt['lthr'])} bpm" if lt.get("lthr") else "LTHR"),
    ):
        now_s, prev_s = now.get(f"{key}_pace_s"), prev.get(f"{key}_pace_s")
        if now_s is None:
            continue
        if prev_s is not None:
            ref = f"prev {LT_FIT_WEEKS} wks `{fmt_clock(prev_s)}/km`"
            trend = f"{lt_verdict(now_s, prev_s)} `{now_s - prev_s:+.0f} s/km`"
        else:
            ref, trend = f"no prior {LT_FIT_WEEKS}-wk fit", "n/a"
        if now.get(f"{key}_extrapolated"):
            trend += " ⚠️ extrapolated"
        rows += f"| **{label}** ({hr_label}) | `{fmt_clock(now_s)}/km` | {ref} | {trend} |\n"
    return rows


def format_fitness_pmc(
    fitness_data: Optional[dict], race_projection: Optional[dict] = None, lt: Optional[dict] = None,
) -> str:
    """Renders the CTL + LT1/LT2 + goal-race projection table for LLM trajectory reasoning.

    ATL/TSB are not displayed as table rows; they are kept as an analysis-only
    line so recovery reasoning (TSB vs HRV/RHR) remains possible.
    lt: checkin_lt_paces output (LT rows omitted when None).
    """
    if fitness_data is None:
        return ""

    trajectory_info = fitness_data.get("trajectory_info", {})
    ctl_end = round(fitness_data.get("ctl_end", 0.0), 1)
    atl_end = round(fitness_data.get("atl_end", 0.0), 1)
    tsb_end = round(fitness_data.get("tsb_end", 0.0), 1)

    target_peak = trajectory_info.get("target_peak_ctl", DEFAULT_PEAK_CTL)
    ref_range = trajectory_info.get("reference_range", list(DEFAULT_PEAK_RANGE))
    req_ramp = trajectory_info.get("required_ramp_rate")
    weeks_rem = trajectory_info.get("weeks_remaining")
    taper_label = f"{trajectory_info.get('taper_weeks', TAPER_WEEKS):g}-week taper"
    in_taper = trajectory_info.get("phase") == "taper"
    pre_taper_ctl = trajectory_info.get("pre_taper_ctl")

    # In the taper CTL is expected to decline, so progress is judged on the peak
    # fitness banked before the taper (static for the whole taper).
    progress_ctl = round(pre_taper_ctl, 1) if in_taper and pre_taper_ctl is not None else ctl_end
    pct = min(100, max(0, int((progress_ctl / target_peak) * 100))) if target_peak > 0 else 100
    filled = pct // PROGRESS_BAR_SEGMENTS
    bar = "█" * filled + "░" * (PROGRESS_BAR_SEGMENTS - filled)

    if in_taper:
        lo, hi = RACE_DAY_TSB_TARGET
        ramp_str = (
            f" (peak CTL banked `{progress_ctl}`) | 🏁 **Taper phase** ({taper_label}): "
            f"hold fitness, shed fatigue; no CTL build required | "
            f"TSB `{tsb_end:+.1f}` (race-day target +{lo} to +{hi})"
        )
    elif req_ramp is not None:
        ramp_str = f" | Req. Ramp: `+{req_ramp} pts/wk` {ramp_status(req_ramp)} (build to {taper_label})"
    else:
        ramp_str = ""
    weeks_str = f" ({weeks_rem}w out)" if weeks_rem is not None else ""
    range_str = f" (Range: `{ref_range[0]}-{ref_range[1]}`)" if ref_range and len(ref_range) == 2 else ""

    race_projection = race_projection or {}
    projection_row = format_projection_row(
        race_projection.get("projection"), race_projection.get("goal_label"), weeks_str
    )
    drivers = format_drivers_table(race_projection.get("projection"))
    drivers_str = f"\n{drivers}\n" if drivers else ""

    return (
        "| Metric | Current Value | Target / Reference | Progress & Trajectory |\n"
        "|---|---|---|---|\n"
        f"| **CTL (Fitness)** | `{ctl_end}` | Target: `{target_peak}`{range_str}{weeks_str} | `[{bar}]` **{pct}%**{ramp_str} |\n"
        f"{format_lt_rows(lt)}"
        f"{projection_row}"
        f"{drivers_str}"
        f"\nLoad context (analysis only, not displayed): ATL `{atl_end}` | TSB `{tsb_end:+.1f}`\n"
    )
