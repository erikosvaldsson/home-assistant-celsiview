"""Make the integration importable as `celsiview_api` in tests.

The custom component lives under `custom_components/celsiview/` which is
not on ``sys.path`` by default. Tests exercise the API client in
isolation (no Home Assistant runtime), so we load `api.py` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "celsiview"))
