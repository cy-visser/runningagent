import os
from typing import Any

import yaml
from google.adk.skills import Frontmatter, Resources, Skill
from google.adk.tools import ToolContext
from google.adk.tools.skill_toolset import LoadSkillTool, SkillToolset
from google.genai import types

from ...integrations import package_paths
from .quick_actions import is_quick_action_report

# Feature folders that ship a SKILL.md, in catalog order (order is part of the prompt).
SKILL_FEATURES = (
    "nutrition_planner",
    "check_in_report",
    "trend_analysis",
    "workout_analysis",
    "bike_workout_analysis",
    "plan_audit",
    "workout_creator",
    "plan_builder",
)

PLAN_BUILDER_SKILL = "plan-builder"
PLAN_BUILDER_CONTEXT_ARGS = ("start_date", "end_date", "mode")

# Routing (when to load which skill, parallel data call, write-tool rules) lives in the coach
# instruction's SKILL ROUTING section; this line only introduces the catalog.
_SKILL_INSTRUCTION = (
    "Available skills (load with `load_skill` per SKILL ROUTING; follow the loaded protocol):"
)


def load_feature_skill(feature: str) -> Skill:
    """Loads features/<feature>/SKILL.md; the skill name is the kebab-case form of the folder."""
    path = os.path.join(package_paths.PACKAGE_DIR, "features", feature, "SKILL.md")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    _, frontmatter_str, body = content.split("---", 2)
    frontmatter = Frontmatter.model_validate(yaml.safe_load(frontmatter_str))
    expected_name = feature.replace("_", "-")
    if frontmatter.name != expected_name:
        raise ValueError(f"{path}: skill name '{frontmatter.name}' must be '{expected_name}'")
    return Skill(frontmatter=frontmatter, instructions=body.strip(), resources=Resources())


def format_skill_catalog(skills: list[Skill]) -> str:
    """Compact one-line-per-skill catalog."""
    lines = [f"- {s.name}: {s.description}" for s in skills]
    return "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>"


class CoachLoadSkillTool(LoadSkillTool):
    """`load_skill` with lean output and optional window/mode pass-through for `plan-builder`."""

    def _get_declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name,
            description=(
                "Loads a skill's instructions. When `skill_name` is 'plan-builder', optional `start_date`, "
                "`end_date` and `mode` also load the plan context in the same step."
            ),
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "Skill name from <available_skills>."},
                    "start_date": {"type": "string", "description": "plan-builder only: YYYY-MM-DD first day."},
                    "end_date": {"type": "string", "description": "plan-builder only: YYYY-MM-DD last day."},
                    "mode": {
                        "type": "string",
                        "enum": ["new", "overhaul"],
                        "description": "plan-builder only: 'new' (default) or 'overhaul'.",
                    },
                },
                "required": ["skill_name"],
            },
        )

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        result = await super().run_async(args={"skill_name": args.get("skill_name")}, tool_context=tool_context)
        if isinstance(result, dict) and "instructions" in result:
            return {"skill_name": result["skill_name"], "instructions": result["instructions"]}
        return result


class CompactSkillToolset(SkillToolset):
    """Exposes only `load_skill`, with a compact one-line-per-skill catalog."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tools = [CoachLoadSkillTool(self)]

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: Any) -> None:
        # A web quick action's report call already holds its skill and cannot call tools.
        if is_quick_action_report(tool_context.state, tool_context.invocation_id):
            return
        llm_request.append_instructions(
            [_SKILL_INSTRUCTION, format_skill_catalog(self._list_skills())]
        )


skill_toolset = CompactSkillToolset(
    skills=[load_feature_skill(feature) for feature in SKILL_FEATURES],
)
