#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import importlib
import sys
from typing import Any

try:
    from pipeline_contracts import CandidateMaterializationResult, base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import CandidateMaterializationResult, base_result


def _legacy() -> Any:
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "write_provider_files"):
        return main
    packaged = sys.modules.get("scripts.run_local_pipeline")
    if packaged is not None and hasattr(packaged, "write_provider_files"):
        return packaged
    try:
        return importlib.import_module("run_local_pipeline")
    except ModuleNotFoundError:
        return importlib.import_module("scripts.run_local_pipeline")


def run(*, candidate_dir: pathlib.Path, files: list[dict[str, str]], semantic_classes: dict[str, Any] | None = None, sanitize_result: dict[str, Any] | None = None) -> dict[str, Any]:
    legacy = _legacy()
    generated_files = legacy.write_provider_files(candidate_dir, files)
    legacy.write_candidate_marker(candidate_dir, "needs_rework", semantic_classes or {}, sanitize_result or {})
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
