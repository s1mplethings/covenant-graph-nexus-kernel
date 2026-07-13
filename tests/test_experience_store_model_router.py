from __future__ import annotations

import pathlib

import pytest

from scripts.experience_store import ExperienceStore, signature
from scripts.model_router import provider_consumption_status, route_task


def test_proposed_or_unverified_experience_cannot_be_confirmed(tmp_path: pathlib.Path) -> None:
    store = ExperienceStore(tmp_path / "experience.sqlite")

    with pytest.raises(ValueError):
        store.record_candidate(
            {
                "status": "confirmed",
                "project_type": "web",
                "task_type": "ui_journey",
                "stage": "acceptance",
                "symptoms": ["api-only journey"],
                "action": "add UI journey",
                "verification": "",
                "evidence_refs": [],
            }
        )


def test_verified_repair_can_be_confirmed_and_retrieved_top_k(tmp_path: pathlib.Path) -> None:
    store = ExperienceStore(tmp_path / "experience.sqlite")
    exp = store.record_candidate(
        {
            "project_type": "web",
            "task_type": "ui_journey",
            "stage": "acceptance",
            "symptoms": ["api-only journey"],
            "root_cause": "UI gate missing",
            "action": "require public user_action evidence",
            "verification": "pytest",
            "outcome": "candidate",
            "confidence": 0.4,
            "source_run_id": "run_a",
            "source_task_id": "task_a",
            "applicable_versions": ["v1"],
        }
    )

    confirmed = store.confirm_from_verified_repair(exp["experience_id"], evidence_refs=["evidence_ledger.jsonl"], verification="reverify passed")
    result = store.retrieve({"project_type": "web", "task_type": "ui_journey", "stage": "acceptance", "symptoms": ["api-only journey"], "version": "v1"}, top_k=3)

    assert confirmed["status"] == "confirmed"
    assert result["selected_experiences"][0]["experience_id"] == exp["experience_id"]
    assert result["injection_token_estimate"] > 0


def test_failed_reuse_lowers_confidence_and_records_negative_condition(tmp_path: pathlib.Path) -> None:
    store = ExperienceStore(tmp_path / "experience.sqlite")
    exp = store.record_candidate(
        {
            "status": "confirmed",
            "project_type": "web",
            "task_type": "screenshot",
            "stage": "acceptance",
            "symptoms": ["duplicate screenshot"],
            "root_cause": "hash not checked",
            "action": "dedupe screenshot hashes",
            "verification": "pytest",
            "outcome": "verified",
            "confidence": 0.8,
            "evidence_refs": ["test"],
            "verified_execution": True,
            "test_result": "PASS",
        }
    )

    updated = store.update_reuse_outcome(exp["experience_id"], success=False, negative_condition="different screenshot backend")

    assert updated["failure_count"] == 1
    assert updated["confidence"] < exp["confidence"]
    assert "different screenshot backend" in updated["negative_conditions"]


def test_conflicting_experiences_are_not_auto_selected(tmp_path: pathlib.Path) -> None:
    store = ExperienceStore(tmp_path / "experience.sqlite")
    sig = signature({"project_type": "web", "task_type": "package", "stage": "delivery", "symptoms": ["missing evidence"]})
    for suffix, action in [("a", "package immediately"), ("b", "delay package until screenshots")]:
        store.record_candidate(
            {
                "experience_id": f"exp_{suffix}",
                "problem_signature": sig,
                "status": "confirmed",
                "project_type": "web",
                "task_type": "package",
                "stage": "delivery",
                "symptoms": ["missing evidence"],
                "root_cause": "delivery order",
                "action": action,
                "verification": "pytest",
                "outcome": "verified",
                "confidence": 0.9,
                "evidence_refs": ["test"],
                "verified_execution": True,
                "test_result": "PASS",
            }
        )

    result = store.retrieve({"project_type": "web", "task_type": "package", "stage": "delivery", "symptoms": ["missing evidence"]})

    assert result["selected_experiences"] == []
    assert set(result["conflicts"]["conflicted_ids"]) == {"exp_a", "exp_b"}


def test_model_router_keeps_stable_rules_deterministic() -> None:
    decision = route_task({"task_type": "secret_scan", "risk": "high", "api_readiness": True, "api_budget": "high"})

    assert decision["selected_route"] == "deterministic"
    assert "stable_rule_task" in decision["reason_codes"]


def test_model_router_uses_local_for_low_risk_suitable_task() -> None:
    decision = route_task({"task_type": "context_compression", "risk": "low", "local_model_readiness": True, "local_model_confidence": 0.8})

    assert decision["selected_route"] == "local_model"
    assert decision["selected_model"] == "local"


def test_model_router_blocks_local_and_api_without_silent_upgrade() -> None:
    local = route_task({"task_type": "failure_classification", "local_model_readiness": False, "api_readiness": True, "api_budget": "high"})
    api = route_task({"task_type": "architecture", "risk": "high", "api_readiness": False, "api_budget": "high"})
    budget = route_task({"task_type": "architecture", "risk": "high", "api_readiness": True, "api_budget": "off"})

    assert local["selected_route"] == "deterministic"
    assert local["fallback"] == "BLOCKED_LOCAL_MODEL"
    assert api["fallback"] == "BLOCKED_PROVIDER"
    assert budget["fallback"] == "BLOCKED_API_BUDGET"


def test_high_risk_task_uses_api_when_available() -> None:
    decision = route_task({"task_type": "complex_repair", "risk": "high", "api_readiness": True, "api_budget": "high", "api_model": "gpt-test"})

    assert decision["selected_route"] == "api_model"
    assert decision["selected_model"] == "gpt-test"
    assert decision["context_budget"] > 0


def test_provider_output_must_be_consumed_or_marked_unused() -> None:
    provider_events = [
        {"request_id": "req_used", "response_hash": "a", "produced_artifacts": ["file.py"]},
        {"request_id": "req_unused", "response_hash": "b", "produced_artifacts": []},
    ]
    evidence_events = [{"provider_request_ids": ["req_used"], "data": {}}]

    report = provider_consumption_status(provider_events, evidence_events)

    assert report["status"] == "PASS_WITH_LIMITS"
    assert report["unused_count"] == 1
    assert report["unused_provider_outputs"][0]["request_id"] == "req_unused"
