"""Deploy contract: the container registers the firestore:// session scheme before ADK creates the session service."""

import pathlib
import re
import subprocess
import sys

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]

_CHECK = (
    "import sys\n"
    "from google.adk.cli.service_registry import get_service_registry, load_services_module\n"
    "load_services_module(sys.argv[1])\n"
    "print('firestore' in get_service_registry()._session_factories)\n"
)


def test_container_agents_dir_registers_firestore_sessions_at_startup(tmp_path):
    # The Dockerfile installs the ADK services.py next to the agent package (adk api_server /app/agents).
    dockerfile = (PACKAGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY .*agents_dir_services\.py /app/agents/services\.py$", dockerfile, re.MULTILINE)
    assert "/app/agents" in dockerfile.split("CMD", 1)[1]

    # Same layout as the container, in a fresh interpreter (no test imports registering the scheme first).
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "running_coach").symlink_to(PACKAGE_ROOT, target_is_directory=True)
    (agents / "services.py").write_text((PACKAGE_ROOT / "agents_dir_services.py").read_text(encoding="utf-8"))
    out = subprocess.run([sys.executable, "-c", _CHECK, str(agents)], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "True", out.stderr[-2000:]
