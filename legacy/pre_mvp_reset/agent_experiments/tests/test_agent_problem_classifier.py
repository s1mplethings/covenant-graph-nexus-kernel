from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import agent_problem_classifier


def base_state() -> dict:
    return {
        "latest_reports": {"agent_led_verify": "verify.json", "large_project_benchmark": "benchmark.json"},
        "latest_report_status": {"agent_led_verify": "pass", "large_project_benchmark": "pass"},
        "agent_led": {"director_loop_used": True, "decision_ledger_exists": True, "selected_tools": ["formal_generation:local_only"]},
        "provider": {"provider_available": True, "provider_error_type": None, "provider_quota_exceeded": False, "local_model_available": True},
        "generation": {
            "formal_generation_materialized": True,
            "writable_project_files_exist": True,
            "candidate_exists": True,
            "final_project_exists": True,
            "semantic_review_status": "pass",
        },
        "delivery": {
            "delivery_manifest_exists": True,
            "final_bundle_exists": True,
            "screenshot_evidence_exists": True,
            "public_gate_status": "READY",
            "delivery_manifest": "delivery_manifest.json",
        },
        "quality": {
            "complexity_status": "pass",
            "product_acceptance_status": "pass",
            "commercial_status": "COMMERCIAL_READY",
            "remaining_blockers": [],
            "missing_core_features": [],
            "ux_score": 85,
            "model_participation_status": "pass",
        },
        "tests": {"last_pytest_status": "pass", "failed_tests": []},
        "ledgers": {"agent_decision_ledger": "agent_decision_ledger.jsonl", "model_call_ledger": "model_call_ledger.jsonl"},
    }


def test_all_green_classifies_no_issue() -> None:
    diagnosis = agent_problem_classifier.classify_problem(base_state())

    assert diagnosis["problem_type"] == "NO_ISSUE_DETECTED"
    assert diagnosis["status"] == "pass"


def test_provider_quota_with_local_available_selects_verify_fallback() -> None:
    state = base_state()
    state["latest_report_status"]["agent_led_verify"] = "blocked"
    state["generation"]["formal_generation_materialized"] = False
    state["delivery"]["final_bundle_exists"] = False
    state["provider"]["provider_error_type"] = "PROVIDER_QUOTA_EXCEEDED"
    state["provider"]["provider_quota_exceeded"] = True

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "PROVIDER_QUOTA_OR_TRANSPORT"
    assert diagnosis["selected_tool"] == "run_agent_led_verify"


def test_provider_quota_without_local_model_blocks() -> None:
    state = base_state()
    state["latest_report_status"]["agent_led_verify"] = "blocked"
    state["generation"]["formal_generation_materialized"] = False
    state["provider"]["provider_error_type"] = "PROVIDER_QUOTA_EXCEEDED"
    state["provider"]["provider_quota_exceeded"] = True
    state["provider"]["local_model_available"] = False

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["status"] == "blocked"
    assert diagnosis["remaining_blockers"] == ["WAITING_FOR_PROVIDER_QUOTA_AND_LOCAL_MODEL_UNAVAILABLE"]


def test_missing_decision_ledger_is_not_agent_led_pass() -> None:
    state = base_state()
    state["agent_led"]["decision_ledger_exists"] = False

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "AGENT_DECISION_LEDGER_MISSING"


def test_candidate_rework_rejects_final_promotion() -> None:
    state = base_state()
    state["latest_report_status"]["agent_led_verify"] = "needs_rework"
    state["generation"]["semantic_review_status"] = "needs_rework"
    state["generation"]["final_project_exists"] = False
    state["delivery"]["final_bundle_exists"] = False

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "CANDIDATE_NEEDS_REWORK"
    assert diagnosis["selected_tool"] == "repair_candidate"
    assert "final_promotion" in diagnosis["rejected_tools"]


def test_missing_final_bundle_repairs_delivery_evidence() -> None:
    state = base_state()
    state["latest_report_status"]["agent_led_verify"] = "fail"
    state["delivery"]["final_bundle_exists"] = False

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "FINAL_BUNDLE_MISSING"
    assert diagnosis["selected_tool"] == "repair_delivery_evidence"


def test_complexity_insufficient_does_not_pass_commercial_ready() -> None:
    state = base_state()
    state["latest_report_status"]["large_project_benchmark"] = "needs_rework"
    state["quality"]["complexity_status"] = "fail"

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "COMPLEXITY_INSUFFICIENT"
    assert diagnosis["selected_tool"] == "repair_complexity_generation"
    assert diagnosis["problem_type"] != "NO_ISSUE_DETECTED"


def test_product_acceptance_pollution_repairs_acceptance_not_provider() -> None:
    state = base_state()
    state["latest_report_status"]["large_project_benchmark"] = "needs_rework"
    state["quality"]["product_acceptance_status"] = "fail"
    state["quality"]["missing_core_features"] = ["commercial", "readiness"]

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "PRODUCT_ACCEPTANCE_POLLUTION"
    assert diagnosis["selected_tool"] == "repair_product_acceptance"
    assert "repair_provider_fallback" in diagnosis["rejected_tools"]


def test_test_failure_has_priority() -> None:
    state = base_state()
    state["tests"]["last_pytest_status"] = "fail"
    state["tests"]["failed_tests"] = ["tests/test_x.py::test_y"]
    state["provider"]["provider_error_type"] = "PROVIDER_QUOTA_EXCEEDED"
    state["provider"]["provider_quota_exceeded"] = True

    diagnosis = agent_problem_classifier.classify_problem(state)

    assert diagnosis["problem_type"] == "TEST_REGRESSION"
    assert diagnosis["selected_tool"] == "run_targeted_tests"
