"""Validated dashboard quick actions forwarded to the agent as per-turn `temp:` state.

Only these feature buttons send an action; typed chat messages never do, so they keep the agent's
full routing and tool calling. Contract with `coach/coaching/quick_actions.py` is checked in
`tests/test_structure.py`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

QUICK_ACTION_STATE_KEY = "temp:quick_action"
# Message part carrying the action (Agent Runtime's /api/run_sse drops state_delta): prefix + JSON.
QUICK_ACTION_PART_PREFIX = "[[running_coach:quick_action]]"
QUICK_ACTION_SKILLS = (
    "check-in-report", "trend-analysis", "plan-audit", "workout-analysis", "workout-creator",
    "plan-builder:intake", "plan-builder:apply",
)

IsoDate = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def to_state(self) -> dict[str, Any]:
        """`{"skill", "args"}` with only the arguments that were set."""
        args = self.model_dump(exclude={"skill"}, exclude_none=True)
        return {"skill": self.skill, "args": args}  # type: ignore[attr-defined]


class CheckinAction(_Action):
    skill: Literal["check-in-report"]


class TrendAction(_Action):
    skill: Literal["trend-analysis"]
    weeks: int = Field(26, ge=6, le=52)


class AuditAction(_Action):
    skill: Literal["plan-audit"]
    start_date: Optional[IsoDate] = None
    end_date: Optional[IsoDate] = None


class WorkoutAction(_Action):
    skill: Literal["workout-analysis"]
    date_str: Union[Literal["today"], IsoDate] = "today"
    sport: Literal["run", "bike"] = "run"


class ApplyStagedAction(_Action):
    """'Update TrainingPeaks' button: applies the staged workout changes in code (no LLM call)."""

    skill: Literal["workout-creator"]
    staged_id: str = Field(..., pattern=r"^[0-9a-f-]{36}$")


class PlanIntakeAction(_Action):
    """'Build Plan' button: the agent reads the next unplanned goal's plan context in code and writes a short
    block proposal (never a plan). No arguments: the agent computes the window from the profile."""

    skill: Literal["plan-builder:intake"]


class PlanApplyAction(_Action):
    """One week of the staged plan written to TrainingPeaks in code (silent per-week apply loop, no LLM)."""

    skill: Literal["plan-builder:apply"]
    staged_id: str = Field(..., pattern=r"^[0-9a-f-]{36}$")
    week: int = Field(..., ge=1, le=52)


QuickAction = Annotated[
    Union[CheckinAction, TrendAction, AuditAction, WorkoutAction, ApplyStagedAction, PlanIntakeAction,
          PlanApplyAction],
    Field(discriminator="skill"),
]
