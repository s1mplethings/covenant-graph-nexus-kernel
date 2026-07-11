#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
from typing import Any

try:
    import check_connectivity
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import check_connectivity
    from scripts.pipeline_contracts import base_result


def _legacy() -> Any:
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "run_provider_semantic_review_with_repair"):
        return main
    packaged = sys.modules.get("scripts.run_local_pipeline")
    if packaged is not None and hasattr(packaged, "run_provider_semantic_review_with_repair"):
        return packaged
    try:
        return importlib.import_module("run_local_pipeline")
    except ModuleNotFoundError:
        return importlib.import_module("scripts.run_local_pipeline")


def run(**kwargs: Any) -> dict[str, Any]:
    legacy = _legacy()
    return legacy.run_provider_semantic_review_with_repair(**kwargs)


def choose_model(*args: Any, **kwargs: Any) -> dict[str, Any]:
    legacy = _legacy()
    return legacy.choose_provider_model(*args, **kwargs)


def provider_quota_blocked(error: BaseException | str) -> bool:
    return check_connectivity._provider_error_type(str(error or "")) == "PROVIDER_QUOTA_EXCEEDED"


def should_skip_repeated_live_generation(previous_status: dict[str, Any] | None) -> bool:
    if not isinstance(previous_status, dict):
        return False
    return str(previous_status.get("provider_error_type", "")) == "PROVIDER_QUOTA_EXCEEDED" or bool(previous_status.get("provider_quota_blocked"))


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="replaceable_module",
        metadata={
            "responsibilities": [
                "provider model routing",
                "split component generation",
                "file-level generation",
                "provider transport classification",
                "provider non-JSON handling",
            ],
            "forbidden": ["final zip", "delivery manifest", "Telegram delivered state"],
        },
    )
