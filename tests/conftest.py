"""Pytest configuration for the running_coach agent tests.

Adds the repository's parent directory to sys.path so `running_coach` is
importable as a package without requiring an editable install.
"""

import os
import sys

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_PARENT = os.path.dirname(PACKAGE_ROOT)

if REPO_PARENT not in sys.path:
    sys.path.insert(0, REPO_PARENT)
