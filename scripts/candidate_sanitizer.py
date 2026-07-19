#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
from typing import Any

try:
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import base_result


def _legacy() -> Any:
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "sanitize_candidate_files_before_materialization"):
        return main
    packaged = sys.modules.get("scripts.run_local_pipeline")
    if packaged is not None and hasattr(packaged, "sanitize_candidate_files_before_materialization"):
        return packaged
    implementation = sys.modules.get("scripts.run_local_pipeline_impl")
    if implementation is not None:
        return implementation
    try:
        return importlib.import_module("scripts.run_local_pipeline_impl")
    except ModuleNotFoundError:
        return importlib.import_module("run_local_pipeline_impl")


def run(files: list[dict[str, str]], repairable_fact_blockers: list[Any]) -> dict[str, Any]:
    legacy = _legacy()
    return legacy.sanitize_candidate_files_before_materialization(files, repairable_fact_blockers)


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="module_contract",
        metadata={
            "responsibilities": [
                "fake zip script sanitizer",
                "fake manifest claim sanitizer",
                "fake screenshot/video claim sanitizer",
                "inaccurate TEST_REPORT claim sanitizer",
            ],
            "forbidden": ["claiming final delivery", "creating final package", "creating delivery manifest"],
        },
    )
