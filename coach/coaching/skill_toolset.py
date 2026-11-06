import os
from typing import Any

from google.adk.skills import load_skill_from_dir
from google.adk.skills.prompt import format_skills_as_xml
from google.adk.tools import ToolContext
from google.adk.tools.skill_toolset import SkillToolset

from ...integrations import package_paths

SKILL_DIRS = (
    ("nutrition_planner", "nutrition-planner"),
    ("check_in_report", "check-in-report"),
    ("trend_analysis", "trend-analysis"),
    ("workout_analysis", "workout-analysis"),
    ("workout_analysis", "bike-workout-analysis"),
    ("schedule_audit", "schedule-audit"),
    ("workout_creator", "workout-creator"),
)

# Routing (when to load which skill, parallel data call, write-tool rules) lives in the coach
# instruction's SKILL ROUTING section; this line only introduces the catalog.
_SKILL_INSTRUCTION = (
    "Available skills (load with `load_skill` per SKILL ROUTING; follow the loaded protocol exactly):"
)


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
    skills=[
        load_skill_from_dir(os.path.join(package_paths.PACKAGE_DIR, "features", feat, name))
        for feat, name in SKILL_DIRS
    ],
)
