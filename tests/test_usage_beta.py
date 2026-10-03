from __future__ import annotations

import pytest

from scripts import usage_beta


def all_pass() -> dict[str, str]:
    return {name: "PASS" for name in usage_beta.GATE_ORDER}


def evaluate(**overrides):
    values = {
        "gates": all_pass(),
        "execution_mode": "codex_surrogate",
        "repository_global_verdict": "NEEDS_REWORK",
        "global_limitations": ["formal_quick_timeout", "live_provider_blocked", "external_executor_not_frozen"],
    }
    values.update(overrides)
    return usage_beta.evaluate_usage_beta(**values)


def test_global_needs_rework_and_formal_quick_timeout_do_not_block_project() -> None:
    result = evaluate()
    assert result["status"] == "PASS"
    assert result["repository_global_verdict"] == "NEEDS_REWORK"
    assert "formal_quick_timeout" in result["global_limitations"]


def test_core_failure_needs_rework() -> None:
    gates = all_pass()
    gates["core_capability"] = "FAIL"
    result = evaluate(gates=gates)
    assert result["status"] == "NEEDS_REWORK"
    assert result["primary_blocker"] == "CORE_CAPABILITY_FAILED"


def test_runtime_not_evaluated_blocks() -> None:
    gates = all_pass()
    gates["runnable"] = "NOT_EVALUATED"
    result = evaluate(gates=gates)
    assert result["status"] == "BLOCKED"
    assert result["primary_blocker"] == "RUNNABLE_NOT_EVALUATED"


def test_delivery_failure_needs_rework() -> None:
    gates = all_pass()
    gates["delivery"] = "FAIL"
    assert evaluate(gates=gates)["status"] == "NEEDS_REWORK"


def test_primary_blocker_uses_pipeline_order() -> None:
    gates = all_pass()
    gates["runnable"] = "FAIL"
    gates["delivery"] = "FAIL"
    result = evaluate(gates=gates)
    assert result["primary_blocker"] == "RUNNABLE_FAILED"
    assert result["secondary_findings"] == ["DELIVERY_FAILED"]


def test_external_executor_global_state_is_not_a_gate() -> None:
    assert evaluate()["status"] == "PASS"


def test_project_external_executor_failure_blocks() -> None:
    result = evaluate(external_executor_required=True, external_executor_project_status="FAIL")
    assert result["status"] == "NEEDS_REWORK"
    assert result["primary_blocker"] == "PROJECT_EXTERNAL_EXECUTOR_INTEGRATION_FAILED"


def test_project_external_executor_failure_keeps_core_pipeline_priority() -> None:
    gates = all_pass()
    gates["delivery"] = "FAIL"
    result = evaluate(
        gates=gates,
        external_executor_required=True,
        external_executor_project_status="FAIL",
    )
    assert result["primary_blocker"] == "PROJECT_EXTERNAL_EXECUTOR_INTEGRATION_FAILED"
    assert result["secondary_findings"] == ["DELIVERY_FAILED"]


def test_usage_pass_cannot_promote_release() -> None:
    result = evaluate()
    assert result["release_ready"] is False
    assert result["commercial_ready"] is False
    assert result["formal_release_verdict"] == "NOT_EVALUATED"
    assert result["formal_acceptance_authority"] is False


def test_usage_beta_defaults_surrogate_but_explicit_live_is_preserved() -> None:
    assert usage_beta.resolve_usage_beta_mode(requested_mode=None, usage_beta=True) == "codex_surrogate"
    assert usage_beta.resolve_usage_beta_mode(requested_mode="live", usage_beta=True) == "live"
    assert usage_beta.resolve_usage_beta_mode(requested_mode=None, usage_beta=False) == "live"
    with pytest.raises(ValueError):
        usage_beta.resolve_usage_beta_mode(requested_mode="other", usage_beta=True)
