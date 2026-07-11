from __future__ import annotations

from typing import Any


FAILURE_TYPES = {
    "provider_unavailable",
    "provider_model_unsupported",
    "missing_files",
    "test_failed",
    "scope_violation",
    "quality_insufficient",
    "needs_split",
    "repeated_failure",
    "context_pollution",
    "fake_success_detected",
}


def classify_leaf_failure(payload: dict[str, Any]) -> dict[str, Any]:
    leaf_id = str(payload.get("leaf_id") or payload.get("checkpoint", {}).get("agent_id") or "")
    checkpoint = payload.get("checkpoint") or {}
    test_execution = payload.get("test_execution") or {}
    provider = payload.get("provider_status") or {}
    scope = payload.get("scope_enforcement") or {}
    attempts = int(payload.get("repair_attempts") or 0)

    claimed_pass = any(
        str(value).upper() == "PASS"
        for value in (payload.get("delivery_status"), payload.get("claimed_verdict"))
        if value is not None
    )
    checkpoint_failed = str(checkpoint.get("verdict", "")).upper() in {"FAIL", "BLOCKED", "NEEDS_SPLIT"}
    if claimed_pass and checkpoint_failed:
        failure_type, severity, reason = (
            "fake_success_detected",
            "fatal",
            "Leaf claimed PASS while its checkpoint did not pass.",
        )
    elif str(provider.get("failure_type", "")).lower() == "provider_model_unsupported":
        failure_type, severity, reason = (
            "provider_model_unsupported",
            "blocked",
            "Provider/model invocation is unsupported in the current environment; no output may be fabricated.",
        )
    elif provider.get("provider_ready") is False or str(provider.get("classification", "")).lower() == "provider_unavailable":
        failure_type, severity, reason = (
            str(provider.get("failure_type") or "provider_unavailable"),
            "blocked",
            "Provider is unavailable; no output may be fabricated.",
        )
    elif scope.get("blocked_files") or scope.get("violations") or scope.get("ok") is False:
        failure_type, severity, reason = (
            "scope_violation",
            "fatal",
            "Leaf attempted to write outside its scope contract.",
        )
    elif str(checkpoint.get("verdict", "")).upper() == "NEEDS_SPLIT" or payload.get("needs_split"):
        failure_type, severity, reason = (
            "needs_split",
            "recoverable",
            "Leaf scope exceeds the configured leaf budget.",
        )
    elif payload.get("context_pollution"):
        failure_type, severity, reason = (
            "context_pollution",
            "recoverable",
            "Leaf context contains unrelated or forbidden material.",
        )
    elif checkpoint.get("missing_files"):
        failure_type, severity, reason = (
            "missing_files",
            "recoverable",
            "Leaf checkpoint is missing required files.",
        )
    elif str(test_execution.get("verdict", "")).upper() == "FAIL" or test_execution.get("exit_code") not in (None, 0):
        failure_type, severity, reason = (
            "test_failed",
            "recoverable",
            "Leaf tests failed.",
        )
    elif payload.get("quality_insufficient") or str(checkpoint.get("quality_verdict", "")).upper() == "FAIL":
        failure_type, severity, reason = (
            "quality_insufficient",
            "recoverable",
            "Leaf output did not meet the quality threshold.",
        )
    elif attempts >= 2 or payload.get("repeated_failure"):
        failure_type, severity, reason = (
            "repeated_failure",
            "fatal",
            "Leaf repeated the same failure after repair attempts.",
        )
    else:
        failure_type, severity, reason = (
            "test_failed",
            "recoverable",
            "Leaf failed without a more specific failure signal.",
        )

    return {
        "leaf_id": leaf_id,
        "failure_type": failure_type,
        "severity": severity,
        "can_retry_leaf": failure_type in {"missing_files", "test_failed", "quality_insufficient"} and attempts < 2,
        "should_prune": failure_type
        in {"scope_violation", "needs_split", "context_pollution", "fake_success_detected", "repeated_failure"}
        or (failure_type in {"missing_files", "test_failed", "quality_insufficient"} and attempts >= 2),
        "reason": reason,
        "repair_attempts": attempts,
    }


classify_failure = classify_leaf_failure
