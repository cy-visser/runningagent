"""Filesystem locations resolved relative to the installed agent package."""

import os

# Root of the `running_coach` package (the directory containing agent.py).
PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKILLS_DIR = os.path.join(PACKAGE_DIR, "skills")
DOTENV_PATH = os.path.join(PACKAGE_DIR, ".env")
