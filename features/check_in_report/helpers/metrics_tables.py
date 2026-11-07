from typing import Optional

from ....shared.goal_distance import DEFAULT_PEAK_CTL, DEFAULT_PEAK_RANGE
from ....shared.hr_pace_fit import LT_FIT_WEEKS
from ....shared.units import fmt_clock
from ....shared.goal_projection.goal_trajectory import TAPER_WEEKS
from ....shared.goal_projection.race_projection import format_drivers_table, format_projection_row


def _lt_change(now_s: float, prev_s: float) -> str:
    """'-6 s/km (-1.4%) vs previous 4 wk' (negative = faster)."""
    delta = now_s - prev_s
    pct = f" ({delta / prev_s * 100:+.1f}%)" if prev_s else ""
    return f"`{delta:+.0f} s/km`{pct} vs previous {LT_FIT_WEEKS} wk"


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
            trend = _lt_change(now_s, prev_s)
        else:
            ref, trend = f"no prior {LT_FIT_WEEKS}-wk fit", "n/a"
        if now.get(f"{key}_extrapolated"):
            trend += " (HR outside the fitted HR range: extrapolated)"
        rows += f"| **{label}** ({hr_label}) | `{fmt_clock(now_s)}/km` | {ref} | {trend} |\n"
    return rows


def format_fitness_pmc(
    fitness_data: Optional[dict], race_projection: Optional[dict] = None, lt: Optional[dict] = None,
) -> str:
    """Renders the CTL + LT1/LT2 + goal-race projection evidence for LLM trajectory reasoning (never shown verbatim).

    Facts only: the coach draws every conclusion. ATL/TSB are not displayed as table rows; they
    are kept as an analysis-only line so recovery reasoning (TSB vs HRV/RHR) remains possible.
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
    build_weeks = trajectory_info.get("build_weeks")
    taper_weeks = trajectory_info.get("taper_weeks", TAPER_WEEKS)
    in_taper = trajectory_info.get("phase") == "taper"
    pre_taper_ctl = trajectory_info.get("pre_taper_ctl")

    # In the taper CTL declines by design, so progress is measured on the peak
    # fitness banked before the taper (static for the whole taper).
    progress_ctl = round(pre_taper_ctl, 1) if in_taper and pre_taper_ctl is not None else ctl_end
    pct = min(100, max(0, int((progress_ctl / target_peak) * 100))) if target_peak > 0 else 100

    if in_taper:
        to_race = f", {weeks_rem:g} wk to race" if weeks_rem is not None else ""
        ramp_str = (
            f" | taper phase ({taper_weeks:g} wk taper{to_race}): peak CTL banked `{progress_ctl}`, "
            f"now `{ctl_end}`; TSB `{tsb_end:+.1f}`, ATL `{atl_end}`"
        )
    elif req_ramp is not None and req_ramp <= 0:
        ramp_str = " | required CTL build `0 pts/wk` (CTL already at or above target)"
    elif req_ramp is not None:
        over = f" over {build_weeks:.1f} build weeks" if build_weeks is not None else ""
        ramp_str = f" | required CTL build `+{req_ramp} pts/wk`{over} (to taper start)"
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
        f"| **CTL (Fitness)** | `{ctl_end}` | Target: `{target_peak}`{range_str}{weeks_str} | **{pct}%** of target{ramp_str} |\n"
        f"{format_lt_rows(lt)}"
        f"{projection_row}"
        f"{drivers_str}"
        f"\nLoad context (analysis only, not displayed): ATL `{atl_end}` | TSB `{tsb_end:+.1f}`\n"
    )
