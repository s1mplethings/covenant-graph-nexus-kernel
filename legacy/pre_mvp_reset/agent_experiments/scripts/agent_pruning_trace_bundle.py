from __future__ import annotations

import pathlib
import zipfile
from typing import Any


REQUIRED_TRACE_ENTRIES = [
    "00_INDEX.md",
    "failure_classifications.jsonl",
    "pruning_events.jsonl",
    "upward_signals.jsonl",
    "branch_replans.jsonl",
    "agent_tree_registry_before.json",
    "agent_tree_registry_after.json",
    "feedback_tasks.jsonl",
    "final_verdict.json",
]


def create_pruning_trace_bundle(
    out_dir: str | pathlib.Path,
    bundle_path: str | pathlib.Path | None = None,
) -> dict[str, Any]:
    root = pathlib.Path(out_dir)
    target = pathlib.Path(bundle_path) if bundle_path else root.parent / "agent_tree_pruning_trace_bundle.zip"
    missing = [name for name in REQUIRED_TRACE_ENTRIES if not (root / name).exists()]
    if missing:
        return {"verdict": "FAIL", "missing": missing, "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.resolve() != target.resolve():
                archive.write(path, path.relative_to(root).as_posix())
    return {
        "verdict": "PASS",
        "missing": [],
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "sections": REQUIRED_TRACE_ENTRIES,
    }
