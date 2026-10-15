from __future__ import annotations

import ast
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PACKAGES = ("agent", "artifacts", "capabilities", "compiler", "component", "execution", "executors", "governance", "growth", "orchestration", "providers", "runtime", "state", "telemetry")
VALID_COMPLETENESS = {"MISSING", "PARTIAL", "COMPLETE", "BLOCKED"}
P0_CLASSES = {"happy_path", "negative", "boundary"}


def load_json(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def source_files() -> set[str]:
    values: set[str] = set()
    for package in CORE_PACKAGES:
        directory = ROOT / "cgkn" / package
        if directory.exists():
            values.update(path.relative_to(ROOT).as_posix() for path in directory.glob("*.py") if path.name != "__init__.py")
    return values


def module_file(reference: str) -> pathlib.Path:
    module = reference.split(":", 1)[0]
    return ROOT / (module.replace(".", "/") + ".py")


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def result(kind: str, errors: list[str], **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "status": "PASS" if not errors else "FAIL", "errors": sorted(set(errors)), **extra}
