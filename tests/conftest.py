"""Make the integration importable at module level in tests.

Tests exercise the API client and bucketing helper in isolation (no
Home Assistant runtime), so we add `custom_components/celsiview/` to
``sys.path`` and import modules directly. We deliberately avoid loading
the package as ``celsiview`` because ``celsiview/__init__.py`` imports
Home Assistant modules which are not installed in this test environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "celsiview"))
