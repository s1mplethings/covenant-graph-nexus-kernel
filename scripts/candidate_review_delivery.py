#!/usr/bin/env python3
from __future__ import annotations

import pathlib
from typing import Any

try:
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import base_result


def evaluate(candidate_dir: pathlib.Path, candidate_bundle: pathlib.Path, **kwargs: Any) -> dict[str, Any]:
    import codex_conversation as bridge

    return bridge.evaluate_candidate_review_delivery(candidate_dir, candidate_bundle, **kwargs)


def emit(*args: Any, **kwargs: Any) -> dict[str, Any]:
    import codex_conversation as bridge

    return bridge.emit_candidate_review_delivery(*args, **kwargs)


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="replaceable_module",
        metadata={
            "responsibilities": ["ASK_USER_REVIEW candidate delivery", "candidate_diagnostic_bundle", "review message", "ask_user_review_sent"],
            "forbidden": ["delivered", "final_delivered", "PASS_FINAL", "delivery_manifest_sent"],
        },
    )
