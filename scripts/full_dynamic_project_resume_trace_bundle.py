from __future__ import annotations

import pathlib
import zipfile
from typing import Any


REQUIRED = [
    "00_INDEX.md",
    "previous_run_analysis.json",
    "resume_plan.json",
    "passed_leaf_cache_manifest.json",
    "failure_classifications.jsonl",
    "pruning_events.jsonl",
    "upward_signals.jsonl",
    "branch_replans.jsonl",
    "leaf_resume",
    "resume_merge",
    "failure_injection",
    "final_verdict.json",
]


def create_resume_trace_bundle(root_dir: str | pathlib.Path) -> dict[str, Any]:
    root = pathlib.Path(root_dir)
    target = root / "full_dynamic_resume_trace_bundle.zip"
    missing = [item for item in REQUIRED if not (root / item).exists()]
    if missing:
        return {"verdict": "FAIL", "classification": "trace_incomplete", "missing": missing, "path": str(target)}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.resolve() != target.resolve():
                archive.write(path, path.relative_to(root).as_posix())
    return {
        "verdict": "PASS",
        "missing": [],
        "path": str(target),
        "size": target.stat().st_size,
        "sections": REQUIRED,
    }
