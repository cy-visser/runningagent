"""Session-state payloads of the plan builder (contract with the web app: plan_builder_contract.md).

`staged_training_plan` holds the card (weeks with rows) plus the spec and zones, so each week is re-expanded
at apply time: no native builders are stored for 150 sessions (keeps the Firestore session small).
`applied_training_plan` tracks the per-week apply loop (weeks_done, failed_weeks, totals, done).
"""

from typing import Optional

from ....shared.session_state import APPLIED_PLAN_STATE_KEY, STAGED_PLAN_STATE_KEY
from .plan_diff import ROW_FIELDS, counts
from .plan_expand import effective_plan_end, plan_window

PLAN_VERSION = 1


def week_payload(week: dict, changes: list[dict]) -> dict:
    """One card week: phase, totals of the planned sessions, action counts and rows (sorted by date)."""
    sessions = week["sessions"]

    def total(sport: str, field: str) -> float:
        return sum(s.get(field) or 0 for s in sessions if s["sport"] == sport)

    return {
        "week": week["week"], "start": week["start"], "phase": week["phase"], "focus": week["focus"],
        "run_km": round(total("Run", "distance_km"), 1),
        "bike_minutes": round(total("Bike", "duration_minutes")),
        "strength_sessions": sum(1 for s in sessions if s["sport"] == "Strength"),
        "tss": round(sum(s.get("tss_planned") or 0 for s in sessions)),
        "sessions": len(sessions),
        "skipped": week["skipped"],
        "counts": counts(changes),
        "rows": [{k: c.get(k) for k in ROW_FIELDS} for c in changes],
    }


def staged_plan_payload(staged_id: str, spec: dict, zones: dict, weeks: list[dict], title: str) -> dict:
    start, _ = plan_window(spec)
    end = effective_plan_end(spec)
    totals = {"weeks": len(weeks), "sessions": sum(w["sessions"] for w in weeks)}
    for action in ("create", "update", "delete", "keep"):
        totals[action] = sum(w["counts"][action] for w in weeks)
    return {
        "version": PLAN_VERSION, "staged_id": staged_id, "title": title, "mode": spec["mode"],
        "start_date": spec["start_date"] or start.isoformat(), "end_date": end.isoformat(),
        "totals": totals, "weeks": weeks, "spec": spec, "zones": zones,
    }


def new_applied(staged: dict) -> dict:
    return {"staged_id": staged["staged_id"], "total_weeks": len(staged["weeks"]), "weeks_done": [],
            "created": 0, "updated": 0, "deleted": 0, "failed": 0, "failed_weeks": [], "done": False}


def applied_after_week(applied: dict, staged: dict, week: int, ok: dict[str, int], failed: int) -> dict:
    """The apply state after one week: a week with failures goes to failed_weeks (Resume re-applies it)."""
    out = {**applied, "weeks_done": list(applied["weeks_done"]), "failed_weeks": list(applied["failed_weeks"])}
    for action, key in (("create", "created"), ("update", "updated"), ("delete", "deleted")):
        out[key] += ok.get(action, 0)
    out["failed"] += failed
    if failed:
        out["failed_weeks"] = sorted(set(out["failed_weeks"]) | {week})
    else:
        out["weeks_done"] = sorted(set(out["weeks_done"]) | {week})
        out["failed_weeks"] = [w for w in out["failed_weeks"] if w != week]
    out["done"] = set(out["weeks_done"]) >= {w["week"] for w in staged["weeks"]}
    return out


def staged_week(staged: dict, week: int) -> Optional[dict]:
    return next((w for w in staged.get("weeks") or [] if w["week"] == week), None)
