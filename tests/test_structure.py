"""Architectural and cross-stack contract tests enforcing rules 1-10."""

from __future__ import annotations

import ast
import pathlib
import re

from google.adk.tools import FunctionTool

from running_coach.coach.coaching.coaching_agent import coaching_agent_tools
from running_coach.coach.coaching.skill_toolset import SKILL_FEATURES, skill_toolset
from running_coach.features.check_in_report.helpers.web_report import (
    CHECKIN_REPORT_STATE_KEY,
)
from running_coach.features.schedule_audit.helpers.web_report import (
    AUDIT_REPORT_STATE_KEY,
)
from running_coach.features.trend_analysis.helpers.web_report import (
    TREND_REPORT_STATE_KEY,
)
from running_coach.shared.session_state import AUTH_EMAIL_STATE_KEY

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]
FEATURES_DIR = PACKAGE_ROOT / "features"
COACH_DIR = PACKAGE_ROOT / "coach"
SHARED_DIR = PACKAGE_ROOT / "shared"
INTEGRATIONS_DIR = PACKAGE_ROOT / "integrations"
WEB_BACKEND_APP_DIR = PACKAGE_ROOT / "webapp" / "backend" / "app"
WEB_FRONTEND_SRC_DIR = PACKAGE_ROOT / "webapp" / "frontend" / "src"

PROD_DIRS = (FEATURES_DIR, COACH_DIR, SHARED_DIR, INTEGRATIONS_DIR)
INTEGRATION_SUBMODULES = {
    "config",
    "package_paths",
    "firestore",
    "session_service",
    "open_meteo",
    "trainingpeaks",
    "credentials",
    "mcp_toolsets",
    "tp_calls",
}


def _iter_prod_py_files() -> list[pathlib.Path]:
    files = [PACKAGE_ROOT / "__init__.py", PACKAGE_ROOT / "agent.py"]
    for d in PROD_DIRS:
        files.extend(sorted(d.rglob("*.py")))
    return files


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(PACKAGE_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(["running_coach", *parts])


def _resolve_import(from_module: str, is_pkg: bool, level: int, module: str | None) -> str:
    if level == 0:
        return module or ""
    parts = from_module.split(".")
    base = parts if is_pkg else parts[:-1]
    up = level - 1
    if up > 0:
        base = base[:-up]
    return ".".join([*base, module]) if module else ".".join(base)


def _eval_dict_literal(py_file: pathlib.Path, var_name: str) -> dict:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == var_name:
                    return ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == var_name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{var_name} not found in {py_file}")


def test_architecture_rules_and_cross_stack_contract():
    prod_files = _iter_prod_py_files()

    # Rule 1: Every SKILL.md lives directly in its feature folder (features/<feature>/SKILL.md),
    # next to that feature's *_tool.py files, and no SKILL.md is nested deeper.
    skill_mds = sorted(FEATURES_DIR.glob("*/SKILL.md"))
    assert {p.parent.name for p in skill_mds} == set(SKILL_FEATURES)
    assert not list(FEATURES_DIR.glob("*/*/SKILL.md")), "SKILL.md must not be nested below features/<feature>/"

    # Rule 2 & 7: Every *_tool.py defines exactly 1 FunctionTool named <tool_name> and is registered.
    tool_files = sorted(FEATURES_DIR.rglob("*_tool.py")) + sorted(COACH_DIR.rglob("*_tool.py"))
    registered_tools = {t.name: t for t in coaching_agent_tools if isinstance(t, FunctionTool)}
    assert len(tool_files) == len(registered_tools)
    for tf in tool_files:
        expected_func_name = tf.stem[: -len("_tool")]
        expected_var_name = f"{expected_func_name}_tool"
        tree = ast.parse(tf.read_text(encoding="utf-8"), filename=str(tf))
        ft_assigns = [
            node.targets[0].id
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "FunctionTool"
        ]
        assert ft_assigns == [expected_var_name], f"{tf} must define only {expected_var_name}"
        assert expected_func_name in registered_tools

    # Rule 7: Every tool referenced in SKILL.md (`fetch_*`, `analyze_workout`, `create_*`) is registered,
    # and every skill folder is loaded in skill_toolset.
    loaded_skill_names = {s.name for s in skill_toolset._list_skills()}
    assert loaded_skill_names == {f.replace("_", "-") for f in SKILL_FEATURES}
    tool_name_re = re.compile(
        r"\b(fetch_checkin_data|fetch_trend_data|analyze_workout|fetch_schedule_audit_data|"
        r"fetch_nutrition_context|create_workout|create_note|get_weather|request_new_goal)\b"
    )
    for smd in skill_mds:
        for match in tool_name_re.findall(smd.read_text(encoding="utf-8")):
            assert match in registered_tools

    # Rule 6: Package __init__.py files are empty (except running_coach/__init__.py and integrations/__init__.py).
    for init_py in sorted(PACKAGE_ROOT.rglob("__init__.py")):
        rel = init_py.relative_to(PACKAGE_ROOT)
        if rel.parts[0] in ("webapp", "tests", ".adk", "trainingpeaks-mcp"):
            continue
        if rel in (pathlib.Path("__init__.py"), pathlib.Path("integrations/__init__.py")):
            continue
        assert init_py.read_text(encoding="utf-8").strip() == "", f"{rel} must be empty"

    # Build AST import graph across production files for Rules 3, 4, 5, 8, 9.
    graph: dict[str, set[str]] = {}
    shared_consumers: dict[str, set[str]] = {}

    for pf in prod_files:
        mod = _module_name(pf)
        is_pkg = pf.name == "__init__.py"
        graph.setdefault(mod, set())
        tree = ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
        rel_parts = pf.relative_to(PACKAGE_ROOT).parts

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Rule 8: No absolute running_coach.* imports inside production modules.
                    assert not alias.name.startswith("running_coach"), f"Absolute import in {pf}: {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    assert not node.module.startswith("running_coach"), f"Absolute import in {pf}: {node.module}"
                    continue
                target_base = _resolve_import(mod, is_pkg, node.level, node.module)
                imported_names = [a.name for a in node.names]

                # Rule 9: Outside integrations/, integrations must be imported as modules, never individual symbols.
                if rel_parts[0] != "integrations" and target_base.startswith("running_coach.integrations"):
                    assert target_base in (
                        "running_coach.integrations",
                        "running_coach.integrations.trainingpeaks",
                    ), f"{pf} imports symbol directly from {target_base}: {imported_names}"
                    for name in imported_names:
                        assert name in INTEGRATION_SUBMODULES, f"{pf} imports non-module {name} from {target_base}"

                for name in imported_names:
                    candidate = f"{target_base}.{name}" if target_base else name
                    resolved = candidate if any(
                        m == candidate or m.startswith(candidate + ".")
                        for m in (_module_name(f) for f in prod_files)
                    ) else target_base
                    if resolved.startswith("running_coach."):
                        graph[mod].add(resolved)

                        # Rule 3 & 4: Feature boundary checks.
                        if rel_parts[0] == "features":
                            feat_name = rel_parts[1]
                            assert not resolved.startswith("running_coach.coach"), f"{pf} imports coach: {resolved}"
                            if resolved.startswith("running_coach.features."):
                                other_feat = resolved.split(".")[2]
                                assert other_feat == feat_name, f"Cross-feature import in {pf}: {resolved}"
                        elif rel_parts[0] == "coach":
                            if resolved.startswith("running_coach.features."):
                                leaf = resolved.split(".")[-1]
                                assert "helpers" not in resolved.split("."), f"coach imports feature helper: {resolved}"
                                assert leaf.endswith("_tool") or leaf.endswith("_callback"), (
                                    f"coach imports non-tool/callback feature module: {resolved}"
                                )
                        elif rel_parts[0] in ("shared", "integrations"):
                            # Rule 5: shared/ and integrations/ never import features/ or coach/.
                            assert not resolved.startswith("running_coach.features"), f"{pf} imports features: {resolved}"
                            assert not resolved.startswith("running_coach.coach"), f"{pf} imports coach: {resolved}"

                        # Track top-level shared/<module_or_subpackage> consumers for Rule 5.
                        if resolved.startswith("running_coach.shared."):
                            parts = resolved.split(".")
                            shared_unit = ".".join(parts[:3])  # e.g. running_coach.shared.dates or training_log
                            consumer_group = (
                                f"feature:{rel_parts[1]}"
                                if rel_parts[0] == "features"
                                else f"{rel_parts[0]}:{rel_parts[1] if len(rel_parts) > 1 else ''}"
                            )
                            if not mod.startswith(shared_unit):
                                shared_consumers.setdefault(shared_unit, set()).add(consumer_group)

    # Rule 5: Every shared/ top-level module or subpackage serves at least 2 distinct consumers.
    shared_units = {
        _module_name(p)
        for p in sorted(SHARED_DIR.iterdir())
        if (p.is_file() and p.suffix == ".py" and p.name != "__init__.py")
        or (p.is_dir() and (p / "__init__.py").exists())
    }
    for s_unit in sorted(shared_units):
        assert len(shared_consumers.get(s_unit, set())) >= 2, (
            f"{s_unit} has fewer than 2 consumers: {shared_consumers.get(s_unit)}"
        )

    # Rule 8: No import cycles in the production module graph.
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> None:
        visiting.add(node)
        for nxt in graph.get(node, ()):
            assert nxt not in visiting, f"Import cycle detected involving {node} -> {nxt}"
            if nxt not in visited:
                dfs(nxt)
        visiting.remove(node)
        visited.add(node)

    for m in list(graph):
        if m not in visited:
            dfs(m)

    # Rule 10 (Frontend): when src/features/ exists, features never cross-import and shared/ never imports app/features.
    fe_features_dir = WEB_FRONTEND_SRC_DIR / "features"
    if fe_features_dir.is_dir():
        import_re = re.compile(r"""from\s+["']([^"']+)["']""")
        for ts_file in sorted(WEB_FRONTEND_SRC_DIR.rglob("*.ts*")):
            rel = ts_file.relative_to(WEB_FRONTEND_SRC_DIR)
            top = rel.parts[0]
            for spec in import_re.findall(ts_file.read_text(encoding="utf-8")):
                if not spec.startswith("."):
                    continue
                target = (ts_file.parent / spec).resolve()
                try:
                    t_rel = target.relative_to(WEB_FRONTEND_SRC_DIR.resolve())
                except ValueError:
                    continue
                t_top = t_rel.parts[0]
                if top == "features":
                    feat = rel.parts[1]
                    assert t_top != "app", f"Frontend feature {rel} imports app/: {spec}"
                    if t_top == "features":
                        assert t_rel.parts[1] == feat, f"Frontend cross-feature import in {rel}: {spec}"
                elif top == "shared":
                    assert t_top not in ("app", "features"), f"Frontend shared {rel} imports {t_top}: {spec}"

    # Cross-stack contract between agent and web backend BFF (parsed via AST so FastAPI isn't imported).
    events_py = WEB_BACKEND_APP_DIR / "events.py"
    agent_client_py = WEB_BACKEND_APP_DIR / "agent_client.py"

    whitelisted = _eval_dict_literal(events_py, "WHITELISTED_REPORT_KEYS")
    assert whitelisted == {
        CHECKIN_REPORT_STATE_KEY: "checkin",
        TREND_REPORT_STATE_KEY: "trend",
        AUDIT_REPORT_STATE_KEY: "audit",
    }

    tool_labels = _eval_dict_literal(events_py, "TOOL_LABELS")
    expected_tool_names = {t.name for t in registered_tools.values()} | {"load_skill"}
    assert set(tool_labels.keys()) == expected_tool_names

    bff_auth_key = _eval_dict_literal(agent_client_py, "AUTH_EMAIL_STATE_KEY")
    assert bff_auth_key == AUTH_EMAIL_STATE_KEY
