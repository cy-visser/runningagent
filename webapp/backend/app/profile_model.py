"""Pydantic models and deterministic update rules for runner profiles."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


def _parse_iso_date(raw: Optional[str], field_label: str) -> date:
    if not raw or not str(raw).strip():
        raise ValueError(f"{field_label} is required (YYYY-MM-DD).")
    text = str(raw).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_label} must be an ISO date (YYYY-MM-DD), got {raw!r}.") from exc


def _opt_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    clean = value.strip()
    return clean if clean else None


class SubGoalInput(BaseModel):
    goal: str = Field(..., min_length=2, max_length=120)
    race_name: Optional[str] = Field(default=None, max_length=160)
    start_date: str
    race_date: str
    taper_weeks: Optional[float] = Field(default=None, ge=0.5, le=6.0)

    @model_validator(mode="after")
    def _validate_dates(self) -> "SubGoalInput":
        self.goal = self.goal.strip()
        self.race_name = _opt_str(self.race_name)
        s = _parse_iso_date(self.start_date, "Sub-goal start_date")
        r = _parse_iso_date(self.race_date, "Sub-goal race_date")
        if s > r:
            raise ValueError(f"Sub-goal '{self.goal}' start_date ({s}) cannot be after race_date ({r}).")
        self.start_date = s.isoformat()
        self.race_date = r.isoformat()
        return self


class NorthStarInput(BaseModel):
    goal: str = Field(..., min_length=2, max_length=120)
    race_name: Optional[str] = Field(default=None, max_length=160)
    start_date: Optional[str] = None
    race_date: str
    taper_weeks: Optional[float] = Field(default=None, ge=0.5, le=6.0)

    @model_validator(mode="after")
    def _validate_dates(self) -> "NorthStarInput":
        self.goal = self.goal.strip()
        self.race_name = _opt_str(self.race_name)
        r = _parse_iso_date(self.race_date, "North-star race_date")
        self.race_date = r.isoformat()
        if self.start_date and self.start_date.strip():
            s = _parse_iso_date(self.start_date, "North-star start_date")
            if s > r:
                raise ValueError("North-star start_date cannot be after race_date.")
            self.start_date = s.isoformat()
        else:
            self.start_date = None
        return self


class ProfileUpdatePayload(BaseModel):
    age: Optional[str] = Field(default=None, max_length=40)
    height: Optional[str] = Field(default=None, max_length=40)
    weight: Optional[str] = Field(default=None, max_length=40)
    location: Optional[str] = Field(default=None, max_length=120)
    goal_type: Literal["single", "plan"]
    training_goal: Optional[str] = Field(default=None, max_length=160)
    timeline: Optional[str] = None
    taper_weeks: Optional[float] = Field(default=None, ge=0.5, le=6.0)
    north_star: Optional[NorthStarInput] = None
    sub_goals: list[SubGoalInput] = Field(default_factory=list)
    recent_race_times: Optional[str] = Field(default=None, max_length=500)
    injuries: Optional[str] = Field(default=None, max_length=800)
    cross_training_strength: Optional[str] = Field(default=None, max_length=800)
    shoe_rotation: Optional[str] = Field(default=None, max_length=800)

    @model_validator(mode="after")
    def _validate_goal_mode(self) -> "ProfileUpdatePayload":
        for attr in ("age", "height", "weight", "location", "recent_race_times", "injuries", "cross_training_strength", "shoe_rotation"):
            setattr(self, attr, _opt_str(getattr(self, attr)))

        if self.goal_type == "single":
            self.training_goal = _opt_str(self.training_goal)
            if not self.training_goal:
                raise ValueError("training_goal is required for a single goal.")
            tl = _parse_iso_date(self.timeline, "Goal timeline")
            self.timeline = tl.isoformat()
            self.north_star = None
            self.sub_goals = []
        else:
            if self.north_star is None:
                raise ValueError("north_star is required for a goal plan.")
            if not self.sub_goals:
                raise ValueError("At least one sub-goal is required for a goal plan.")
            ns_race = date.fromisoformat(self.north_star.race_date)
            for sg in self.sub_goals:
                if date.fromisoformat(sg.race_date) >= ns_race:
                    raise ValueError(
                        f"Sub-goal '{sg.goal}' ({sg.race_date}) must finish before the north-star race ({ns_race})."
                    )
            self.training_goal = None
            self.timeline = None
        return self


def _sub_goal_key(goal: Optional[str], race_date: Optional[str]) -> tuple[str, str]:
    return ((goal or "").strip().lower(), (race_date or "").strip()[:10])


def apply_profile_edit(
    existing: dict[str, Any],
    edit: ProfileUpdatePayload,
    today_iso: Optional[str] = None,
) -> tuple[dict[str, Any], list[str]]:
    """Computes `(updates, deleted_fields)` for a profile edit without touching name or email.

    - Name (`firstname`, `lastname`) and `email` are immutable.
    - Saved `sub_goals[i].result` entries survive goal-plan edits when `(goal, race_date)` matches.
    - Changing `location` deletes `latitude` and `longitude` so the agent re-geocodes.
    - Changing a single goal's target or date updates `goal_set_date` to `today_iso`.
    """
    today_str = today_iso or date.today().isoformat()
    delete_fields: list[str] = []
    if "onboarding_pending" in existing:
        delete_fields.append("onboarding_pending")

    old_loc = str(existing.get("location") or "").strip()
    new_loc = edit.location or ""
    if old_loc.lower() != new_loc.lower():
        for coord in ("latitude", "longitude"):
            if coord in existing:
                delete_fields.append(coord)

    updates: dict[str, Any] = {
        "age": edit.age,
        "height": edit.height,
        "weight": edit.weight,
        "location": new_loc,
        "recent_race_times": edit.recent_race_times,
        "injuries": edit.injuries,
        "cross_training_strength": edit.cross_training_strength,
        "shoe_rotation": edit.shoe_rotation,
        "goal_type": edit.goal_type,
    }

    if edit.goal_type == "single":
        goal_changed = (
            existing.get("goal_type") != "single"
            or (existing.get("training_goal") or "").strip() != (edit.training_goal or "").strip()
            or (existing.get("timeline") or "").strip()[:10] != (edit.timeline or "").strip()[:10]
        )
        updates["training_goal"] = edit.training_goal
        updates["timeline"] = edit.timeline
        updates["taper_weeks"] = edit.taper_weeks
        if goal_changed or not existing.get("goal_set_date"):
            updates["goal_set_date"] = today_str
        for plan_key in ("north_star", "sub_goals"):
            if plan_key in existing:
                delete_fields.append(plan_key)
    else:
        assert edit.north_star is not None
        saved_results = {
            _sub_goal_key(s.get("goal"), s.get("race_date")): s.get("result")
            for s in (existing.get("sub_goals") or [])
            if isinstance(s, dict) and s.get("result")
        }
        sorted_sub_goals = sorted(edit.sub_goals, key=lambda s: s.race_date)
        sub_goal_docs = [
            {
                "goal": sg.goal,
                "race_name": sg.race_name,
                "start_date": sg.start_date,
                "race_date": sg.race_date,
                "taper_weeks": sg.taper_weeks,
                "result": saved_results.get(_sub_goal_key(sg.goal, sg.race_date)),
            }
            for sg in sorted_sub_goals
        ]
        updates["north_star"] = {
            "goal": edit.north_star.goal,
            "race_name": edit.north_star.race_name,
            "start_date": edit.north_star.start_date,
            "race_date": edit.north_star.race_date,
            "taper_weeks": edit.north_star.taper_weeks if edit.north_star.taper_weeks is not None else edit.taper_weeks,
        }
        updates["sub_goals"] = sub_goal_docs
        updates["training_goal"] = None
        updates["timeline"] = None
        updates["taper_weeks"] = None
        if not existing.get("goal_set_date"):
            updates["goal_set_date"] = today_str

    return updates, delete_fields


def profile_state_for(profile: Optional[dict[str, Any]]) -> Literal["none", "needs_onboarding", "ready"]:
    if not profile:
        return "none"
    if profile.get("onboarding_pending"):
        return "needs_onboarding"
    has_single = bool(profile.get("training_goal") or profile.get("timeline"))
    has_plan = bool((profile.get("north_star") or {}).get("goal"))
    return "ready" if (has_single or has_plan) else "needs_onboarding"


def summarize_profile(profile: Optional[dict[str, Any]], today: Optional[date] = None) -> Optional[dict[str, Any]]:
    """Compact summary for dashboard chips and header greeting."""
    if not profile:
        return None
    ref = today or date.today()
    fn = str(profile.get("firstname") or "").strip()
    ln = str(profile.get("lastname") or "").strip()
    goal_type = "plan" if profile.get("goal_type") == "plan" and isinstance(profile.get("north_star"), dict) else "single"

    active_goal = profile.get("training_goal")
    active_race_name = None
    active_date = profile.get("timeline")
    north_star_summary = None

    if goal_type == "plan":
        ns = profile.get("north_star") or {}
        north_star_summary = {
            "goal": ns.get("goal"),
            "race_name": ns.get("race_name"),
            "race_date": ns.get("race_date"),
        }
        chosen = None
        for sg in profile.get("sub_goals") or []:
            if not isinstance(sg, dict):
                continue
            try:
                rd = date.fromisoformat(str(sg.get("race_date") or "")[:10])
            except ValueError:
                continue
            if rd >= ref:
                chosen = sg
                break
        if chosen:
            active_goal = chosen.get("goal")
            active_race_name = chosen.get("race_name")
            active_date = chosen.get("race_date")
        else:
            active_goal = ns.get("goal")
            active_race_name = ns.get("race_name")
            active_date = ns.get("race_date")

    weeks_remaining: Optional[float] = None
    if active_date:
        try:
            days = (date.fromisoformat(str(active_date)[:10]) - ref).days
            weeks_remaining = max(0.0, round(days / 7.0, 1))
        except ValueError:
            weeks_remaining = None

    return {
        "firstname": fn,
        "lastname": ln,
        "full_name": f"{fn} {ln}".strip(),
        "location": profile.get("location"),
        "goal_type": goal_type,
        "active_goal": active_goal,
        "active_race_name": active_race_name,
        "active_date": active_date,
        "weeks_remaining": weeks_remaining,
        "north_star": north_star_summary,
    }
