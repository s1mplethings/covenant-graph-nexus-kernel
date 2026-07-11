from __future__ import annotations

from scripts.agent_leaf_failure_classifier import FAILURE_TYPES, classify_leaf_failure


def test_classifier_supports_required_failure_types() -> None:
    assert {
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
    } <= FAILURE_TYPES


def test_missing_file_can_repair_then_prune() -> None:
    payload = {
        "leaf_id": "task_service_leaf",
        "checkpoint": {"verdict": "FAIL", "missing_files": ["tests/test_task_service.py"]},
        "repair_attempts": 1,
    }
    first = classify_leaf_failure(payload)
    second = classify_leaf_failure({**payload, "repair_attempts": 2})

    assert first["failure_type"] == "missing_files"
    assert first["can_retry_leaf"] is True
    assert first["should_prune"] is False
    assert second["should_prune"] is True


def test_fake_success_has_precedence_over_generic_failure() -> None:
    result = classify_leaf_failure(
        {
            "leaf_id": "claim_leaf",
            "checkpoint": {"verdict": "FAIL"},
            "delivery_status": "PASS",
        }
    )

    assert result["failure_type"] == "fake_success_detected"
    assert result["severity"] == "fatal"
    assert result["should_prune"] is True


def test_model_unsupported_is_provider_block_not_test_failure() -> None:
    result = classify_leaf_failure(
        {
            "leaf_id": "backend_tests_leaf_v2",
            "checkpoint": {"verdict": "BLOCKED"},
            "provider_status": {
                "provider_ready": False,
                "classification": "provider_unavailable",
                "failure_type": "provider_model_unsupported",
            },
        }
    )

    assert result["failure_type"] == "provider_model_unsupported"
    assert result["severity"] == "blocked"
    assert result["can_retry_leaf"] is False
