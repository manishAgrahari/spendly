"""
Ensures the project root (parent of tests/) is importable as `app`,
`database.db`, etc. when running plain `pytest` from the project root.

There is no root-level conftest.py / pytest.ini / pyproject.toml in this
project to trigger pytest's usual rootdir-on-sys.path behaviour, and
tests/ has no __init__.py, so without this the test modules' `from app
import app` would fail with ModuleNotFoundError depending on how pytest
is invoked. This file contains no test logic.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
