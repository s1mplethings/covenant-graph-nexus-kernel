from __future__ import annotations

import pathlib
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import customer_status


def render(internal: dict[str, Any]) -> dict[str, Any]:
    return customer_status.render_from_internal(internal)
