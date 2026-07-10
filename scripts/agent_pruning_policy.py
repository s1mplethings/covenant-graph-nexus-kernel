from __future__ import annotations

from typing import Any


def decide_pruning(
    classification: dict[str, Any],
    *,
    parent_agent: str | None = None,
    consecutive_provider_failures: int | None = None,
) -> dict[str, Any]:
    failure_type = str(classification.get("failure_type", "repeated_failure"))
    attempts = int(classification.get("repair_attempts") or 0)
    parent = parent_agent or classification.get("parent_agent")
    provider_failures = int(
        consecutive_provider_failures
        if consecutive_provider_failures is not None
        else classification.get("consecutive_provider_failures") or attempts
    )

    decision = "PRUNE"
    upward = True
    next_action = "spawn_replacement_leaf"
    reason = str(classification.get("reason") or failure_type)
    if failure_type in {"provider_unavailable", "provider_model_unsupported"}:
        if provider_failures <= 1:
            decision, upward, next_action = "BLOCKED", False, "resume_later"
        else:
            decision, upward, next_action = "PRUNE", True, "switch_provider_mode_or_delay"
    elif failure_type in {"missing_files", "test_failed", "quality_insufficient"} and attempts < 2:
        decision, upward, next_action = "REPAIR", False, "repair_leaf"
    elif failure_type == "needs_split":
        decision, upward, next_action = "SPLIT", True, "split_leaf_into_smaller_leaves"
    elif failure_type == "context_pollution":
        decision, upward, next_action = "PRUNE", True, "reduce_context_and_spawn_replacement"
    elif failure_type == "fake_success_detected":
        decision, upward, next_action = "PRUNE", True, "stop_branch"
    elif failure_type == "scope_violation":
        decision, upward, next_action = "PRUNE", True, "spawn_replacement_leaf"

    return {
        "leaf_id": classification.get("leaf_id", ""),
        "decision": decision,
        "upward_signal": upward,
        "target_parent": parent,
        "reason": reason,
        "next_action": next_action,
        "failure_type": failure_type,
    }


apply_pruning_policy = decide_pruning
