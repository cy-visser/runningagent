"""Goal-plan summary block for the coach instruction (sent once per model call; tools do not repeat it)."""

from datetime import date
from typing import Optional

from ...shared.dates import get_today_date
from ...shared.goal_distance import resolve_target_peak_ctl
from ...shared.goal_plan import KIND_NORTH_STAR, KIND_SUB_GOAL, blocks, current_goal, north_star, race_day
from ...shared.race_equivalents import format_gap, goal_target_s, north_star_equivalent
from ...shared.units import as_float, format_seconds_hms


def _equivalent_cell(time_s: Optional[float], goal: Optional[str], ns_goal: Optional[str]) -> str:
    if not time_s:
        return "-"
    equiv = north_star_equivalent(time_s, goal, ns_goal)
    return f"{format_seconds_hms(time_s)} -> {format_seconds_hms(equiv)}" if equiv else format_seconds_hms(time_s)


def _gap_cell(time_s: Optional[float], goal: Optional[str], ns_goal: Optional[str], ns_target_s: Optional[float]) -> str:
    equiv = north_star_equivalent(time_s, goal, ns_goal)
    return format_gap(equiv - ns_target_s) if equiv and ns_target_s else "-"


def format_goal_plan(profile: Optional[dict], today: Optional[date] = None) -> str:
    """Goal-plan block for the coach instruction and the check-in. '' for single goals."""
    ns = north_star(profile)
    if not ns:
        return ""
    today = today or get_today_date()
    current = current_goal(profile, today)
    ns_goal = ns["training_goal"]
    ns_target_s = goal_target_s(ns_goal)
    ns_race = race_day(ns)

    weeks = f", {max(0, (ns_race - today).days) / 7:.0f} weeks away" if ns_race else ""
    race_name = f" ({ns['race_name']})" if ns.get("race_name") else ""
    lines = [
        "GOAL PLAN (north star with sub goals):",
        f"- North star: {ns_goal}{race_name}, race {ns['timeline']}{weeks}; "
        f"marathon-block start {ns['goal_set_date'] or 'not set'}; planned: {'yes' if ns['planned'] else 'no'}.",
        "- Sub goals (each a full training block; results are progress toward the north star, "
        "never pass/fail). Times shown as 'time -> north-star equivalent' (Riegel). Planned = its training "
        "plan is already in TrainingPeaks:",
        "",
        "| Sub goal | Block | Status | Planned | Target | Result | Result gap to north star |",
        "|---|---|---|---|---|---|---|",
    ]
    for b in blocks(profile):
        if b["kind"] != KIND_SUB_GOAL:
            continue
        r_day = race_day(b)
        if b["index"] == current["index"] and current["kind"] == KIND_SUB_GOAL:
            status = "upcoming (next block)" if current["before_start"] else "active"
        elif r_day and r_day < today:
            status = "done"
        else:
            status = "upcoming"
        result_s = as_float((b["result"] or {}).get("time_s"))
        if result_s:
            result = _equivalent_cell(result_s, b["training_goal"], ns_goal)
        elif status == "done":
            result = "missing: ask the runner"
        else:
            result = "-"
        lines.append(
            f"| {b['training_goal']} | {b['goal_set_date']} -> {b['timeline']} | {status} | "
            f"{'yes' if b['planned'] else 'no'} | "
            f"{_equivalent_cell(goal_target_s(b['training_goal']), b['training_goal'], ns_goal)} | "
            f"{result} | {_gap_cell(result_s, b['training_goal'], ns_goal, ns_target_s)} |"
        )

    lines.append("")
    if current["kind"] == KIND_NORTH_STAR:
        lines.append(f"- Current block: the north-star block ({ns_goal}).")
    else:
        lines.append(f"- Current block: {current['training_goal']}, race {current['timeline']}.")
    if current["before_start"]:
        lines.append(
            f"- Between blocks: the next block starts {current['goal_set_date']}; "
            "treat this period as recovery/transition."
        )
    _, (lo, hi) = resolve_target_peak_ctl(ns_goal)
    lines.append(f"- North-star peak CTL reference range: {lo:.0f}-{hi:.0f} (context for aerobic base).")
    return "\n".join(lines)
