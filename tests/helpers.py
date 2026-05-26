from __future__ import annotations

import copy
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def cloned_flow(registry, ref: str) -> dict:
    return copy.deepcopy(registry.resolve_flow(ref))


def codes(result_or_diags) -> set[str]:
    if isinstance(result_or_diags, dict):
        diags = result_or_diags["diagnostics"]
    else:
        diags = result_or_diags
    return {d["code"] if isinstance(d, dict) else d.code for d in diags}
