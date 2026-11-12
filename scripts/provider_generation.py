#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

try:
    import check_connectivity
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import check_connectivity
    from scripts.pipeline_contracts import base_result








def provider_quota_blocked(error: BaseException | str) -> bool:
    return check_connectivity._provider_error_type(str(error or "")) == "PROVIDER_QUOTA_EXCEEDED"


def should_skip_repeated_live_generation(previous_status: dict[str, Any] | None) -> bool:
    if not isinstance(previous_status, dict):
        return False
    return str(previous_status.get("provider_error_type", "")) == "PROVIDER_QUOTA_EXCEEDED" or bool(previous_status.get("provider_quota_blocked"))


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="read_only_failure_classification",
        metadata={
            "responsibilities": ["read existing Provider quota and failure state"],
            "forbidden": ["final zip", "delivery manifest", "Codex conversation delivered state"],
        },
    )
