#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import json
from typing import Any

try:
    from pipeline_contracts import CandidateMaterializationResult, base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import CandidateMaterializationResult, base_result


def run(*, candidate_dir: pathlib.Path, files: list[dict[str, str]], semantic_classes: dict[str, Any] | None = None, sanitize_result: dict[str, Any] | None = None) -> dict[str, Any]:
    root = pathlib.Path(candidate_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    generated_files: list[str] = []
    for item in files:
        relative = pathlib.PurePosixPath(str(item.get("path", "")).replace("\\", "/"))
        if not relative.parts or relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"unsafe candidate path: {relative}")
        target = (root / pathlib.Path(*relative.parts)).resolve()
        target.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content", "")), encoding="utf-8")
        generated_files.append(relative.as_posix())
    marker = {
        "kind": "CGKNCandidateOnlyMarker",
        "status": "needs_rework",
        "semantic_classes": semantic_classes or {},
        "sanitize_result": sanitize_result or {},
    }
    (root / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    result = CandidateMaterializationResult(
        status="pass",
        verdict="candidate_materialized",
        candidate_dir=str(candidate_dir),
        artifacts=[str(candidate_dir / rel) for rel in generated_files],
        metadata={"generated_files": generated_files, "candidate_only": True},
    )
    data = result.to_dict()
    data["candidate_dir"] = result.candidate_dir
    return data


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="module_contract",
        metadata={
            "responsibilities": ["write candidate_project_dir", "candidate marker", "candidate snapshot manifest", "runnable candidate validation"],
            "forbidden": ["final_project_bundle.zip", "delivery_manifest.json"],
        },
    )
