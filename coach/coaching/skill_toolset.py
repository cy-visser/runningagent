import os
from typing import Any

import yaml
from google.adk.skills import Frontmatter, Resources, Skill
from google.adk.tools import ToolContext
from google.adk.tools.skill_toolset import LoadSkillTool, SkillToolset
from google.genai import types

from ...integrations import package_paths
from ...shared.session_state import APPLIED_PLAN_STATE_KEY, STAGED_PLAN_STATE_KEY
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

SKILL_CATALOG_END = "</available_skills>"

# Routing (when to load which skill, parallel data call, write-tool rules) lives in the coach
# instruction's SKILL ROUTING section; this line only introduces the catalog.
_SKILL_INSTRUCTION = (
    "Available skills (load with `load_skill` per SKILL ROUTING; follow the loaded protocol):"
)
_PRELOADED_PLAN_BUILDER_NOTE = (
    "PLAN CONTEXT and the `plan-builder` protocol are already loaded for this conversation. "
    "Stage or revise the plan with `stage_training_plan` directly (when revising an unapplied staged plan, "
    "pass its `staged_id` as `base_staged_id` with ONLY the changed weeks and a brief delta-only `### Plan Update` "
    "`message`) — do NOT call `load_skill(\"plan-builder\")` unless the runner asked for a different `start_date`, "
    "`end_date`, or `mode`."
)


def has_active_plan_context(contents: list[types.Content] | None) -> bool:
    """True when `contents` has a usable `fetch_plan_context` result with no calendar apply after it."""
    active = False
    for content in contents or []:
        for part in content.parts or []:
            resp = part.function_response
            if not resp:
                continue
            payload = resp.response if isinstance(resp.response, dict) else {}
            result = payload.get("result", payload)
            text = result if isinstance(result, str) else ""
            if resp.name == "fetch_plan_context":
                active = text.lstrip().startswith("PLAN CONTEXT")
            elif resp.name in ("apply_training_plan", "apply_staged_changes"):
                active = False
    return active


has_unconsumed_plan_context = has_active_plan_context


def unapplied_staged_plan_id(state: Any) -> str | None:
    """`staged_id` of an unapplied `staged_training_plan` in session state, or None."""
    if not state:
        return None
    staged = state.get(STAGED_PLAN_STATE_KEY)
    staged_id = staged.get("staged_id") if isinstance(staged, dict) else None
    if not staged_id:
        return None
    applied = state.get(APPLIED_PLAN_STATE_KEY)
    if isinstance(applied, dict) and applied.get("staged_id") == staged_id and applied.get("done"):
        return None
    return staged_id


def _loaded_plan_builder_this_turn(contents: list[types.Content] | None) -> bool:
    items = contents or []
    cut = max(
        (i for i, c in enumerate(items) if c.role == "user" and any(not p.function_response for p in c.parts or [])),
        default=0,
    )
    return any(
        p.function_call
        and p.function_call.name == "load_skill"
        and (p.function_call.args or {}).get("skill_name") == PLAN_BUILDER_SKILL
        for c in items[cut:]
        for p in c.parts or []
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


def _staged_id_in_contents(contents: list[types.Content] | None, staged_id: str) -> bool:
    for content in contents or []:
        for part in content.parts or []:
            if part.text and staged_id in part.text:
                return True
            resp = part.function_response
            if resp and staged_id in str(resp.response or ""):
                return True
    return False


class CompactSkillToolset(SkillToolset):
    """Exposes only `load_skill`, with a compact one-line-per-skill catalog."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tools = [CoachLoadSkillTool(self)]

    async def process_llm_request(self, *, tool_context: ToolContext, llm_request: Any) -> None:
        # A web quick action's report call already holds its skill and cannot call tools.
        if is_quick_action_report(tool_context.state, tool_context.invocation_id):
            return
        skills = self._list_skills()
        extra = [_SKILL_INSTRUCTION, format_skill_catalog(skills)]
        contents = getattr(llm_request, "contents", None)
        staged_id = unapplied_staged_plan_id(tool_context.state)
        if (has_active_plan_context(contents) or staged_id) and not _loaded_plan_builder_this_turn(contents):
            pb = next((s for s in skills if s.name == PLAN_BUILDER_SKILL), None)
            if pb:
                extra.append(
                    f"{_PRELOADED_PLAN_BUILDER_NOTE}\n<plan_builder_protocol>\n{pb.instructions}\n</plan_builder_protocol>"
                )
                if staged_id and not _staged_id_in_contents(contents, staged_id):
                    insert = getattr(llm_request, "_insert_transient_user_content", None)
                    note = f'[Active unapplied staged plan: staged_id="{staged_id}"]'
                    if callable(insert):
                        insert([types.Content(role="user", parts=[types.Part.from_text(text=note)])])
        llm_request.append_instructions(extra)


skill_toolset = CompactSkillToolset(
    skills=[load_feature_skill(feature) for feature in SKILL_FEATURES],
)
