from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_agent_fault_injection_suite


def test_fault_injection_suite_classifies_expected_failures(tmp_path: pathlib.Path) -> None:
    report = run_agent_fault_injection_suite.run_fault_injection_suite(tmp_path)

    assert report["status"] == "pass"
    assert report["fault_injection_cases"] == 8
    assert report["fault_injection_pass"] == 8
    actual = {case["case"]: case["actual_problem_type"] for case in report["cases"]}
    assert actual["missing_decision_ledger"] == "AGENT_DECISION_LEDGER_MISSING"
    assert actual["missing_delivery_manifest"] == "DELIVERY_MANIFEST_MISSING"
    assert actual["missing_final_bundle"] == "FINAL_BUNDLE_MISSING"
    assert actual["missing_screenshot"] == "SCREENSHOT_EVIDENCE_MISSING"
    assert actual["complexity_insufficient"] == "COMPLEXITY_INSUFFICIENT"
    assert actual["product_acceptance_pollution"] == "PRODUCT_ACCEPTANCE_POLLUTION"
    assert actual["provider_quota_local_unavailable"] == "PROVIDER_QUOTA_OR_TRANSPORT"
    assert actual["candidate_marker_in_final_zip"] == "ARTIFACT_INTEGRITY_FAILED"
    assert (tmp_path / "agent_fault_injection_report.json").exists()


def test_provider_quota_local_unavailable_is_blocked(tmp_path: pathlib.Path) -> None:
    report = run_agent_fault_injection_suite.run_fault_injection_suite(tmp_path)
    case = next(item for item in report["cases"] if item["case"] == "provider_quota_local_unavailable")

    assert case["actual_status"] == "blocked"
    assert case["remaining_blockers"] == ["WAITING_FOR_PROVIDER_QUOTA_AND_LOCAL_MODEL_UNAVAILABLE"]
