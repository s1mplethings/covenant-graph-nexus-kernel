#!/usr/bin/env python3
from __future__ import annotations

import pathlib
from typing import Any, Callable

try:
    import agent_decision_ledger
    import agent_state_observer
    import agent_tool_registry
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import agent_decision_ledger  # type: ignore[no-redef]
    from scripts import agent_state_observer  # type: ignore[no-redef]
    from scripts import agent_tool_registry  # type: ignore[no-redef]


Director = Callable[[str, dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
Executor = Callable[[str, dict[str, Any], dict[str, Any], pathlib.Path], dict[str, Any]]


CONDITION_CHECKS = {
    "has_project_spec": lambda state: bool(state.get("has_project_spec")),
    "candidate_materialized": lambda state: bool(state.get("candidate_exists")),
    "semantic_review_needs_rework": lambda state: state.get("semantic_review_status") == "needs_rework",
    "semantic_review_passed": lambda state: state.get("semantic_review_status") == "pass",
    "final_project_materialized": lambda state: bool(state.get("final_project_exists")),
    "delivery_manifest_exists": lambda state: bool(state.get("delivery_manifest_exists")),
    "final_bundle_exists": lambda state: bool(state.get("final_bundle_exists")),
    "screenshot_evidence_exists": lambda state: bool(state.get("screenshot_evidence_exists")),
    "public_gate_ready": lambda state: state.get("public_gate_status") == "READY",
}


def final_delivery_ready(state: dict[str, Any]) -> bool:
    return (
        bool(state.get("final_project_exists"))
        and bool(state.get("delivery_manifest_exists"))
        and bool(state.get("final_bundle_exists"))
        and state.get("public_gate_status") == "READY"
    )


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "candidate_exists",
        "semantic_review_status",
        "final_project_exists",
        "delivery_manifest_exists",
        "final_bundle_exists",
        "screenshot_evidence_exists",
        "public_gate_status",
        "commercial_status",
        "model_participation_status",
        "fallback_reverify_status",
        "provider_error_type",
        "provider_quota_exceeded",
        "local_model_available",
        "formal_generation_materialized",
        "writable_project_files_exist",
    ]
    return {key: state.get(key) for key in keys}


def deterministic_director_decide(goal: str, state: dict[str, Any], registry: list[dict[str, Any]]) -> dict[str, Any]:
    rejected: list[str] = []
    provider_strategy = "api_first"
    if state.get("provider_quota_exceeded") and state.get("local_model_available") and not state.get("formal_generation_materialized"):
        selected = "formal_generation"
        provider_strategy = "local_only"
        rejected = ["formal_live_delivery_closure", "final_promotion", "delivery_manifest_build", "commercial_readiness"]
        reason = "API provider quota is exceeded and local model is available, so formal generation must use local_model_router"
    elif state.get("provider_quota_exceeded") and not state.get("local_model_available") and not state.get("formal_generation_materialized"):
        return {
            "agent_role": "Project Director",
            "observed_state_hash": agent_decision_ledger.observed_state_hash(state),
            "observed_state_summary": state_summary(state),
            "goal": goal,
            "decision": "blocked_waiting_for_provider_quota",
            "selected_tool": "BLOCKED",
            "rejected_tools": ["formal_generation", "final_promotion", "delivery_manifest_build", "commercial_readiness"],
            "reason": "WAITING_FOR_PROVIDER_QUOTA",
            "expected_outputs": [],
            "status": "planned",
            "result_refs": [],
        }
    elif state.get("candidate_exists") and state.get("writable_project_files_exist", True) is False:
        selected = "formal_generation"
        provider_strategy = "local_first" if state.get("local_model_available") else "api_first"
        rejected = ["final_promotion", "delivery_manifest_build", "screenshot_capture", "commercial_readiness"]
        reason = "candidate directory exists but no writable project files were materialized"
    elif state.get("candidate_exists") and state.get("semantic_review_status") == "needs_rework":
        selected = "candidate_repair"
        rejected = ["final_promotion", "delivery_manifest_build", "commercial_readiness"]
        reason = "candidate exists but semantic review needs rework, so promotion is not allowed"
    elif state.get("candidate_exists") and state.get("semantic_review_status") == "pass" and not state.get("final_project_exists"):
        selected = "final_promotion"
        rejected = ["candidate_repair", "commercial_readiness"]
        reason = "candidate passed semantic review and final project does not exist yet"
    elif state.get("final_project_exists") and not state.get("screenshot_evidence_exists"):
        selected = "screenshot_capture"
        rejected = ["public_delivery_gate", "commercial_readiness"]
        reason = "final project exists but visual evidence is missing"
    elif state.get("final_project_exists") and (not state.get("delivery_manifest_exists") or not state.get("final_bundle_exists")):
        selected = "delivery_manifest_build"
        rejected = ["commercial_readiness"]
        reason = "final project exists but delivery manifest or final bundle is missing"
    elif state.get("delivery_manifest_exists") and state.get("final_bundle_exists") and state.get("public_gate_status") != "READY":
        selected = "public_delivery_gate"
        rejected = ["commercial_readiness"]
        reason = "delivery artifacts exist but public gate is not READY"
    elif final_delivery_ready(state):
        selected = "commercial_readiness"
        rejected = []
        reason = "final delivery evidence is ready, so release readiness can be assessed"
    else:
        selected = "formal_generation"
        rejected = ["final_promotion", "commercial_readiness"]
        reason = "candidate or final delivery evidence is missing, so formal generation is the next available tool"
    return {
        "agent_role": "Project Director",
        "observed_state_hash": agent_decision_ledger.observed_state_hash(state),
        "observed_state_summary": state_summary(state),
        "goal": goal,
        "decision": "run_" + selected,
        "selected_tool": selected,
        "provider_strategy": provider_strategy if selected == "formal_generation" else "",
        "rejected_tools": rejected,
        "reason": reason,
        "expected_outputs": next((tool.get("outputs", []) for tool in registry if tool.get("name") == selected), []),
        "status": "planned",
        "result_refs": [],
    }


def validate_decision(decision: dict[str, Any], state: dict[str, Any], registry: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tools = {str(tool["name"]): tool for tool in (registry or agent_tool_registry.get_tool_registry())}
    selected = str(decision.get("selected_tool") or "")
    if selected not in tools:
        if selected == "BLOCKED" and decision.get("reason") == "WAITING_FOR_PROVIDER_QUOTA":
            return {"status": "blocked", "reason": "WAITING_FOR_PROVIDER_QUOTA", "selected_tool": selected}
        return {"status": "fail", "reason": "unknown_tool", "selected_tool": selected}
    tool = tools[selected]
    missing = [condition for condition in tool.get("allowed_when", []) if not CONDITION_CHECKS.get(str(condition), lambda _state: False)(state)]
    if missing:
        return {"status": "fail", "reason": "tool_not_allowed_for_state", "selected_tool": selected, "missing_conditions": missing}
    if selected in {"commercial_readiness", "public_delivery_gate"}:
        hard_missing = [
            name
            for name in ("delivery_manifest_exists", "final_bundle_exists")
            if not bool(state.get(name))
        ]
        if hard_missing:
            return {"status": "fail", "reason": "evidence_gate_missing", "selected_tool": selected, "missing_conditions": hard_missing}
    if selected == "final_promotion" and state.get("semantic_review_status") != "pass":
        return {"status": "fail", "reason": "semantic_review_not_passed", "selected_tool": selected}
    if selected in {"final_promotion", "delivery_manifest_build", "screenshot_capture", "public_delivery_gate", "commercial_readiness"} and state.get("writable_project_files_exist", True) is False:
        return {"status": "fail", "reason": "writable_project_files_missing", "selected_tool": selected}
    if selected == "formal_generation":
        strategy = str(decision.get("provider_strategy") or "api_first")
        allowed = set(tool.get("provider_strategies", []))
        if strategy not in allowed:
            return {"status": "fail", "reason": "unknown_provider_strategy", "selected_tool": selected, "provider_strategy": strategy}
        if strategy in {"local_only", "local_first"} and not state.get("local_model_available"):
            return {"status": "fail", "reason": "local_model_unavailable", "selected_tool": selected, "provider_strategy": strategy}
    if state.get("fallback_reverify_status") == "fail" and selected in {"final_promotion", "public_delivery_gate", "commercial_readiness"}:
        return {"status": "fail", "reason": "fallback_reverify_failed", "selected_tool": selected}
    return {"status": "pass", "selected_tool": selected}


def default_execute_tool(selected_tool: str, decision: dict[str, Any], state: dict[str, Any], run_dir: pathlib.Path) -> dict[str, Any]:
    return {
        "status": "executed",
        "tool": selected_tool,
        "artifacts": [],
        "metadata": {"run_dir": str(run_dir), "dry_run_adapter": True},
    }


def run_director_loop(
    run_dir: str | pathlib.Path,
    *,
    goal: str,
    max_steps: int = 5,
    director: Director | None = None,
    executor: Executor | None = None,
) -> dict[str, Any]:
    run = pathlib.Path(run_dir)
    registry = agent_tool_registry.get_tool_registry()
    decide = director or deterministic_director_decide
    execute = executor or default_execute_tool
    decisions: list[dict[str, Any]] = []
    for _ in range(max_steps):
        state = agent_state_observer.observe_run_state(run)
        if final_delivery_ready(state):
            return {"status": "ready", "state": state, "decisions": decisions}
        decision = decide(goal, state, registry)
        validation = validate_decision(decision, state, registry)
        if validation.get("status") == "blocked":
            decision["status"] = "blocked"
            decision["validation"] = validation
            agent_decision_ledger.append_decision(run, decision, {"status": "blocked", "blockers": [validation.get("reason", "blocked")]})
            decisions.append(decision)
            return {"status": "blocked", "reason": validation.get("reason"), "state": state, "decisions": decisions}
        if validation.get("status") != "pass":
            decision["status"] = "failed"
            decision["validation"] = validation
            agent_decision_ledger.append_decision(run, decision, {"status": "failed", "blockers": [validation.get("reason", "validation_failed")]})
            decisions.append(decision)
            return {"status": "blocked", "reason": validation.get("reason"), "state": state, "decisions": decisions}
        result = execute(str(decision["selected_tool"]), decision, state, run)
        agent_decision_ledger.append_decision(run, decision, result)
        decisions.append({**decision, "execution_result": result})
        if result.get("blocked"):
            return {"status": "blocked", "reason": result.get("reason", "tool_blocked"), "state": state, "decisions": decisions}
    return {"status": "max_steps", "state": agent_state_observer.observe_run_state(run), "decisions": decisions}
