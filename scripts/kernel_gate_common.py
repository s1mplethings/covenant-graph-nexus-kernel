from __future__ import annotations

import ast
import json
import pathlib
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PACKAGES = ("agent", "artifacts", "capabilities", "compiler", "component", "execution", "executors", "governance", "growth", "orchestration", "providers", "runtime", "state", "telemetry", "protocol", "adapters")
VALID_COMPLETENESS = {"MISSING", "PARTIAL", "COMPLETE", "BLOCKED"}
P0_CLASSES = {"happy_path", "negative", "boundary"}


def load_json(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def source_files() -> set[str]:
    values: set[str] = set()
    for package in CORE_PACKAGES:
        directory = ROOT / "cgkn" / package
        if directory.exists():
            values.update(path.relative_to(ROOT).as_posix() for path in directory.rglob("*.py"))
    return values


def module_file(reference: str) -> pathlib.Path:
    module = reference.split(":", 1)[0]
    return ROOT / (module.replace(".", "/") + ".py")


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    parts = list(path.parts)
    package = parts[parts.index('cgkn'):-1] if 'cgkn' in parts else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                prefix = package[:len(package) - node.level + 1]
                module = '.'.join(prefix + ([node.module] if node.module else []))
            else:
                module = node.module or ''
            if module:
                result.add(module)
                result.update(module + '.' + alias.name for alias in node.names if alias.name != '*')
    return result


def result(kind: str, errors: list[str], **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "status": "PASS" if not errors else "FAIL", "errors": sorted(set(errors)), **extra}
