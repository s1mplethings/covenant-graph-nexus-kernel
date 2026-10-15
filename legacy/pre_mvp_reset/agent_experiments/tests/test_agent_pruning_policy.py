from __future__ import annotations

from scripts.agent_pruning_policy import decide_pruning


def _classification(failure_type: str, attempts: int = 0) -> dict[str, object]:
    return {
        "leaf_id": "leaf",
        "failure_type": failure_type,
        "repair_attempts": attempts,
        "reason": "injected",
    }


def test_repairable_failure_escalates_after_second_attempt() -> None:
    first = decide_pruning(_classification("test_failed", 1), parent_agent="branch")
    second = decide_pruning(_classification("test_failed", 2), parent_agent="branch")

    assert first["decision"] == "REPAIR"
    assert first["upward_signal"] is False
    assert second["decision"] == "PRUNE"
    assert second["upward_signal"] is True


def test_immediate_pruning_rules() -> None:
    assert decide_pruning(_classification("scope_violation"), parent_agent="branch")["decision"] == "PRUNE"
    assert decide_pruning(_classification("needs_split"), parent_agent="branch")["decision"] == "SPLIT"
    assert decide_pruning(_classification("context_pollution"), parent_agent="branch")["decision"] == "PRUNE"
    assert decide_pruning(_classification("fake_success_detected"), parent_agent="branch")["decision"] == "PRUNE"


def test_provider_unavailable_blocks_then_escalates() -> None:
    classification = _classification("provider_unavailable", 1)
    first = decide_pruning(classification, parent_agent="branch", consecutive_provider_failures=1)
    repeated = decide_pruning(classification, parent_agent="branch", consecutive_provider_failures=2)

    assert first["decision"] == "BLOCKED"
    assert first["next_action"] == "resume_later"
    assert first["upward_signal"] is False
    assert repeated["decision"] == "PRUNE"
    assert repeated["next_action"] == "switch_provider_mode_or_delay"


def test_provider_model_unsupported_uses_provider_block_policy() -> None:
    classification = _classification("provider_model_unsupported", 1)
    first = decide_pruning(classification, parent_agent="branch", consecutive_provider_failures=1)
    repeated = decide_pruning(classification, parent_agent="branch", consecutive_provider_failures=2)

    assert first["decision"] == "BLOCKED"
    assert first["next_action"] == "resume_later"
    assert repeated["decision"] == "PRUNE"
    assert repeated["next_action"] == "switch_provider_mode_or_delay"
