"""Goal-plan summary block for the coach instruction (sent once per model call; tools do not repeat it)."""

from datetime import date
from typing import Optional

from ...shared.dates import get_today_date, iso_date
from ...shared.goal_distance import resolve_target_peak_ctl
from ...shared.goal_plan import (
    KIND_NORTH_STAR,
    KIND_SUB_GOAL,
    blocks,
    current_goal,
    next_unplanned_goal,
    north_star,
    race_day,
)
from ...shared.race_equivalents import format_gap, goal_target_s, north_star_equivalent
from ...shared.units import as_float, format_seconds_hms


def _present(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _block_details(block: dict, include_taper: bool = False) -> str:
    parts = []
    if _present(block.get("race_name")):
        parts.append(str(block["race_name"]).strip())
    if include_taper and _present(block.get("taper_weeks")):
        taper = as_float(block.get("taper_weeks"))
        parts.append(f"taper {taper:g}w" if taper is not None else f"taper {block['taper_weeks']}w")
    return f" ({', '.join(parts)})" if parts else ""


def _equiv_target(goal: Optional[str], ns_goal: Optional[str]) -> str:
    target_s = goal_target_s(goal)
    if not target_s:
        return ""
    equiv = north_star_equivalent(target_s, goal, ns_goal)
    return f"->{format_seconds_hms(equiv)}" if equiv else format_seconds_hms(target_s)


def _result_clause(result_s: Optional[float], goal: Optional[str], ns_goal: Optional[str], ns_target_s: Optional[float]) -> str:
    if not result_s:
        return ""
    equiv = north_star_equivalent(result_s, goal, ns_goal)
    rendered = f"{format_seconds_hms(result_s)}->{format_seconds_hms(equiv)}" if equiv else format_seconds_hms(result_s)
    gap = format_gap(equiv - ns_target_s) if equiv and ns_target_s else ""
    return f"result {rendered}" + (f" ({gap})" if gap else "")


def _unplanned_tag(nxt: Optional[dict], block: dict) -> Optional[str]:
    if not nxt or nxt["kind"] != block["kind"] or nxt.get("index") != block.get("index"):
        return None
    if block["kind"] == KIND_SUB_GOAL:
        return "NEXT UNPLANNED GOAL"
    return f"NEXT UNPLANNED GOAL (window {iso_date(nxt['window_start'])}..{iso_date(nxt['window_end'])})"


def format_goal_plan(profile: Optional[dict], today: Optional[date] = None) -> str:
    """Compact goal-plan block for the coach instruction. '' for single goals."""
    ns = north_star(profile)
    if not ns:
        return ""
    today = today or get_today_date()
    current = current_goal(profile, today)
    nxt = next_unplanned_goal(profile, today)
    ns_goal = ns["training_goal"]
    ns_target_s = goal_target_s(ns_goal)
    ns_race = race_day(ns)

    _, (lo, hi) = resolve_target_peak_ctl(ns_goal)
    header_meta = ["equiv->NS", f"NS peak CTL {lo:.0f}-{hi:.0f}"]
    if current["before_start"] and current.get("goal_set_date"):
        header_meta.append(f"recovery until {current['goal_set_date']}")
    lines = [f"GOAL PLAN ({'; '.join(header_meta)}):"]

    ns_active = current["kind"] == KIND_NORTH_STAR
    ns_meta = []
    if ns_race:
        ns_meta.append(f"{max(0, (ns_race - today).days) / 7:.0f}w")
    if ns.get("goal_set_date"):
        ns_meta.append(f"start {ns['goal_set_date']}")
    if ns_active:
        ns_meta.append("next" if current["before_start"] else "active")
    ns_unplanned = _unplanned_tag(nxt, ns)
    ns_meta.append(ns_unplanned if ns_unplanned else ("planned" if ns["planned"] else "unplanned"))
    lines.append(
        f"- North star: {ns_goal}{_block_details(ns, include_taper=ns_active)} "
        f"{ns['timeline']} ({', '.join(ns_meta)})"
    )

    for b in blocks(profile):
        if b["kind"] != KIND_SUB_GOAL:
            continue
        r_day = race_day(b)
        is_current = b["index"] == current["index"] and current["kind"] == KIND_SUB_GOAL
        unplanned = _unplanned_tag(nxt, b)
        tags = []
        if is_current:
            tags.append("next" if current["before_start"] else "active")
        elif r_day and r_day < today:
            tags.append("done")
        if unplanned:
            tags.append(unplanned)
        elif not (r_day and r_day < today):
            tags.append("planned" if b["planned"] else "unplanned")

        weeks = f" ({max(0, (r_day - today).days) / 7:.0f}w)" if is_current and r_day else ""
        if unplanned and nxt is not None:
            start_str, end_str = iso_date(nxt["window_start"]), iso_date(nxt["window_end"])
            window = f"{start_str}..{end_str}{weeks}"
        elif b.get("goal_set_date"):
            window = f"{b['goal_set_date']}..{b['timeline']}{weeks}"
        else:
            window = f"{b['timeline']}{weeks}"
        parts = [f"- {b['training_goal']}{_block_details(b, include_taper=is_current)}: {window}"]
        if tags:
            parts.append(", ".join(tags))
        equiv = _equiv_target(b["training_goal"], ns_goal)
        if equiv:
            parts.append(equiv)
        result_s = as_float((b["result"] or {}).get("time_s"))
        if result_s:
            parts.append(_result_clause(result_s, b["training_goal"], ns_goal, ns_target_s))
        elif r_day and r_day < today:
            parts.append("result missing: ask runner")
        lines.append(" | ".join(parts))

    return "\n".join(lines)
