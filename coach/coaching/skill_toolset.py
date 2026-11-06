import os
from typing import Any

import yaml
from google.adk.skills import Frontmatter, Resources, Skill
from google.adk.skills.prompt import format_skills_as_xml
from google.adk.tools import ToolContext
from google.adk.tools.skill_toolset import SkillToolset

from ...integrations import package_paths

# Feature folders that ship a SKILL.md, in catalog order (order is part of the prompt).
SKILL_FEATURES = (
    "nutrition_planner",
    "check_in_report",
    "trend_analysis",
    "workout_analysis",
    "bike_workout_analysis",
    "schedule_audit",
    "workout_creator",
)

# Routing (when to load which skill, parallel data call, write-tool rules) lives in the coach
# instruction's SKILL ROUTING section; this line only introduces the catalog.
_SKILL_INSTRUCTION = (
    "Available skills (load with `load_skill` per SKILL ROUTING; follow the loaded protocol exactly):"
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


class CompactSkillToolset(SkillToolset):
    """Exposes only `load_skill`, with a compact prompt and the pre-rendered skill catalog.

    ADK's default skill prompt (~300 words, sent on every model call) documents
    list_skills / load_skill_resource / run_skill_script and references/assets/scripts
    folders; no skill here ships any of those, so they are dropped.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tools = [t for t in self._tools if t.name == "load_skill"]

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: Any) -> None:
        llm_request.append_instructions(
            [_SKILL_INSTRUCTION, format_skills_as_xml(self._list_skills())]
        )


skill_toolset = CompactSkillToolset(
    skills=[load_feature_skill(feature) for feature in SKILL_FEATURES],
)
