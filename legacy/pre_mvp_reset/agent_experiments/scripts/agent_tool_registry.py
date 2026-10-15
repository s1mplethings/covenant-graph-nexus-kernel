#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
from typing import Any


TOOL_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "formal_generation",
        "description": "generate a candidate project through a director-selected formal provider strategy",
        "inputs": ["goal", "run_dir", "project_spec", "provider_strategy"],
        "outputs": ["candidate_project_dir", "model_call_ledger", "formal_generation_report"],
        "risk_level": "high",
        "allowed_when": ["has_project_spec"],
        "provider_strategies": ["api_first", "local_first", "local_only"],
        "formal_providers": ["api_provider", "local_model_router"],
    },
    {
        "name": "semantic_review",
        "description": "review a materialized candidate against the project spec and acceptance matrix",
        "inputs": ["candidate_project_dir", "project_spec", "acceptance_matrix"],
        "outputs": ["semantic_review_report"],
        "risk_level": "medium",
        "allowed_when": ["candidate_materialized"],
    },
    {
        "name": "candidate_repair",
        "description": "repair candidate project based on semantic review issues",
        "inputs": ["candidate_project_dir", "semantic_review_report"],
        "outputs": ["repair_report", "updated_candidate_project_dir"],
        "risk_level": "medium",
        "allowed_when": ["semantic_review_needs_rework", "candidate_materialized"],
    },
    {
        "name": "local_model_semantic_reverify",
        "description": "reverify a repaired candidate with formal local model evidence",
        "inputs": ["candidate_project_dir", "repair_report", "model_call_ledger"],
        "outputs": ["reverify_report", "model_call_ledger"],
        "risk_level": "medium",
        "allowed_when": ["candidate_materialized"],
    },
    {
        "name": "final_promotion",
        "description": "promote a reviewed candidate to final project through final promotion rules",
        "inputs": ["candidate_project_dir", "semantic_review_report", "candidate_bundle"],
        "outputs": ["final_project_dir", "final_project_manifest"],
        "risk_level": "high",
        "allowed_when": ["candidate_materialized", "semantic_review_passed"],
    },
    {
        "name": "artifact_integrity_check",
        "description": "validate package, manifest, visual evidence, and fake-artifact risks",
        "inputs": ["final_project_dir", "final_project_bundle", "delivery_manifest"],
        "outputs": ["artifact_integrity_report"],
        "risk_level": "low",
        "allowed_when": ["final_project_materialized"],
    },
    {
        "name": "screenshot_capture",
        "description": "capture visual evidence for a runnable candidate or final project",
        "inputs": ["project_dir", "startup_command"],
        "outputs": ["screenshot_evidence"],
        "risk_level": "medium",
        "allowed_when": ["candidate_materialized"],
    },
    {
        "name": "delivery_manifest_build",
        "description": "build delivery_manifest.json through local_packager for a final project",
        "inputs": ["final_project_dir", "screenshot_evidence"],
        "outputs": ["delivery_manifest", "final_project_bundle"],
        "risk_level": "high",
        "allowed_when": ["final_project_materialized", "screenshot_evidence_exists"],
    },
    {
        "name": "public_delivery_gate",
        "description": "evaluate whether final delivery artifacts may be publicly delivered",
        "inputs": ["final_project_dir", "delivery_manifest", "final_project_bundle"],
        "outputs": ["public_delivery_gate_report"],
        "risk_level": "high",
        "allowed_when": ["final_project_materialized", "delivery_manifest_exists", "final_bundle_exists"],
    },
    {
        "name": "product_acceptance",
        "description": "score product completeness, UX evidence, and customer-visible limitations",
        "inputs": ["project_dir", "project_spec", "acceptance_matrix"],
        "outputs": ["product_acceptance_report"],
        "risk_level": "medium",
        "allowed_when": ["candidate_materialized"],
    },
    {
        "name": "commercial_readiness",
        "description": "assess release readiness without minting delivery artifacts",
        "inputs": ["final_project_dir", "delivery_manifest", "final_project_bundle", "product_acceptance_report"],
        "outputs": ["commercial_readiness_report"],
        "risk_level": "high",
        "allowed_when": ["final_project_materialized", "delivery_manifest_exists", "final_bundle_exists", "public_gate_ready"],
    },
    {
        "name": "formal_live_delivery_closure",
        "description": "high-level final closure tool that runs formal generation and final safety gates",
        "inputs": ["goal", "model", "run_dir"],
        "outputs": ["formal_live_delivery_closure_report", "delivery_manifest", "final_project_bundle"],
        "risk_level": "high",
        "allowed_when": ["has_project_spec"],
    },
    {
        "name": "inspect_latest_reports",
        "description": "read latest verify, benchmark, closure, commercial, product acceptance, and delivery reports",
        "inputs": ["repo_root"],
        "outputs": ["diagnosis_observed_state", "latest_reports"],
        "risk_level": "low",
        "allowed_when": [],
    },
    {
        "name": "inspect_decision_ledger",
        "description": "inspect agent decision ledger presence and recent decisions",
        "inputs": ["run_dir"],
        "outputs": ["agent_decision_ledger_summary"],
        "risk_level": "low",
        "allowed_when": [],
    },
    {
        "name": "inspect_model_ledger",
        "description": "inspect formal model call ledger and model participation evidence",
        "inputs": ["run_dir"],
        "outputs": ["model_call_ledger_summary"],
        "risk_level": "low",
        "allowed_when": [],
    },
    {
        "name": "run_agent_led_verify",
        "description": "run verify_repo through the agent-led director entrypoint",
        "inputs": ["repo_root"],
        "outputs": ["agent_led_verify_report", "agent_decision_ledger"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "run_large_project_benchmark",
        "description": "run the large project agent-led benchmark",
        "inputs": ["repo_root"],
        "outputs": ["large_project_agent_led_benchmark_report"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "run_targeted_tests",
        "description": "run the smallest relevant pytest target for a diagnosed regression",
        "inputs": ["test_selector"],
        "outputs": ["pytest_result", "failed_test_summary"],
        "risk_level": "low",
        "allowed_when": [],
    },
    {
        "name": "repair_verify_entry",
        "description": "repair verify entrypoint when it bypasses the agent director loop",
        "inputs": ["verify_script"],
        "outputs": ["updated_verify_entry", "agent_led_verify_report"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "repair_provider_fallback",
        "description": "repair provider quota or transport fallback routing without changing product acceptance",
        "inputs": ["provider_status", "local_model_status"],
        "outputs": ["provider_fallback_report"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "repair_candidate",
        "description": "repair a candidate project that failed semantic review or UX acceptance",
        "inputs": ["candidate_project_dir", "semantic_review_report"],
        "outputs": ["repair_report", "updated_candidate_project_dir"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "repair_final_promotion",
        "description": "repair final promotion without weakening evidence gates",
        "inputs": ["candidate_project_dir", "promotion_report"],
        "outputs": ["final_project_dir", "final_project_manifest"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "repair_delivery_evidence",
        "description": "repair manifest, bundle, screenshot, or public gate evidence for an existing final project",
        "inputs": ["final_project_dir"],
        "outputs": ["delivery_manifest", "final_project_bundle", "public_delivery_gate_report"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "repair_product_acceptance",
        "description": "repair product acceptance feature-source or product completeness issues",
        "inputs": ["product_acceptance_report", "project_spec"],
        "outputs": ["product_acceptance_report"],
        "risk_level": "medium",
        "allowed_when": [],
    },
    {
        "name": "repair_complexity_generation",
        "description": "repair project generation when complexity audit is insufficient without weakening the audit",
        "inputs": ["complexity_audit_report", "project_spec"],
        "outputs": ["expanded_project", "complexity_audit_report"],
        "risk_level": "high",
        "allowed_when": [],
    },
    {
        "name": "stability_rerun",
        "description": "optional lightweight stability rerun when no issue is detected",
        "inputs": ["repo_root"],
        "outputs": ["diagnosis_report"],
        "risk_level": "low",
        "allowed_when": [],
    },
]


def get_tool_registry() -> list[dict[str, Any]]:
    return deepcopy(TOOL_REGISTRY)


def registry_by_name() -> dict[str, dict[str, Any]]:
    return {str(tool["name"]): deepcopy(tool) for tool in TOOL_REGISTRY}


def get_tool(name: str) -> dict[str, Any] | None:
    return registry_by_name().get(str(name))


def tool_names() -> list[str]:
    return [str(tool["name"]) for tool in TOOL_REGISTRY]
