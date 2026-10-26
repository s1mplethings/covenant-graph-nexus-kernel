#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import pathlib
import sys
from typing import Any


PRODUCTION_ROOTS = ("cgkn/application", "cgkn/agent", "cgkn/executors")
DIRECT_COMPLETE_ALLOWLIST = {
    "cgkn/application/learning/integration.py",
    "cgkn/application/requirements/comparison.py",  # recording-only benchmark delegate
    "cgkn/application/capability_routing/formal.py",  # bounded decision benchmark; never project generation
    "cgkn/application/project_campaign/provider.py",  # transparent route guard and usage ledger
    "cgkn/application/conversation/service.py",  # read-only grounded answer, not project/capability generation
}


def check(repository: pathlib.Path | str = ".") -> dict[str, Any]:
    root = pathlib.Path(repository).resolve(); violations: list[str] = []
    for relative_root in PRODUCTION_ROOTS:
        for path in sorted((root / relative_root).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "complete":
                    if relative not in DIRECT_COMPLETE_ALLOWLIST:
                        violations.append(f"PRODUCTION_GENERATION_BYPASS:{relative}:{node.lineno}")
            if relative.endswith("extractor.py"):
                text = path.read_text(encoding="utf-8")
                if ".complete(" in text or "ProductionGenerationClient" in text:
                    violations.append("LESSON_EXTRACTOR_PROVIDER_CALL:" + relative)
    legacy = (root / "scripts/run_local_pipeline_impl.py").read_text(encoding="utf-8")
    if "lesson_aware_messages(" not in legacy or '"lesson_context_frozen"' not in legacy:
        violations.append("COMPATIBILITY_PRODUCTION_GENERATION_BYPASS:scripts/run_local_pipeline_impl.py")
    status = "PASS" if not violations else "FAIL"
    return {"kind": "LessonGenerationArchitectureGate", "schema_version": "1.0", "status": status, "violations": violations, "contains_credentials": False}


def main() -> int:
    result = check(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

