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
QUICK_ACTION_SKILLS = ("check-in-report", "trend-analysis", "schedule-audit", "workout-analysis")

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
    skill: Literal["schedule-audit"]
    start_date: Optional[IsoDate] = None
    end_date: Optional[IsoDate] = None


class WorkoutAction(_Action):
    skill: Literal["workout-analysis"]
    date_str: Union[Literal["today"], IsoDate] = "today"
    sport: Literal["run", "bike"] = "run"


QuickAction = Annotated[
    Union[CheckinAction, TrendAction, AuditAction, WorkoutAction],
    Field(discriminator="skill"),
]
