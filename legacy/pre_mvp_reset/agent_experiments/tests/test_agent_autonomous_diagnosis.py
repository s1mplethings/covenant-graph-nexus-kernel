from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_agent_autonomous_diagnosis


def passing_observed_state() -> dict:
    return {
        "latest_reports": {"agent_led_verify": "verify.json", "large_project_benchmark": "benchmark.json"},
        "latest_report_status": {"agent_led_verify": "pass", "large_project_benchmark": "pass"},
        "agent_led": {"director_loop_used": True, "decision_ledger_exists": True, "selected_tools": ["formal_generation:local_only"]},
        "provider": {"provider_available": False, "provider_error_type": "PROVIDER_QUOTA_EXCEEDED", "provider_quota_exceeded": True, "local_model_available": True},
        "generation": {
            "formal_generation_materialized": True,
            "writable_project_files_exist": True,
            "candidate_exists": True,
            "final_project_exists": True,
            "semantic_review_status": "pass",
        },
        "delivery": {
            "delivery_manifest_exists": True,
            "delivery_manifest": "delivery_manifest.json",
            "final_bundle_exists": True,
            "screenshot_evidence_exists": True,
            "public_gate_status": "READY",
        },
        "quality": {
            "complexity_status": "pass",
            "product_acceptance_status": "pass",
            "commercial_status": "COMMERCIAL_READY",
            "remaining_blockers": [],
            "model_participation_status": "pass",
        },
        "tests": {"last_pytest_status": "pass", "failed_tests": []},
        "ledgers": {"agent_decision_ledger": "agent_decision_ledger.jsonl", "model_call_ledger": "model_call_ledger.jsonl"},
    }


def test_autonomous_diagnosis_no_issue_writes_report_and_ledger(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(run_agent_autonomous_diagnosis.agent_state_observer, "observe_repository_state", lambda repo: passing_observed_state())
    args = argparse.Namespace(repo=str(tmp_path), output_root=str(tmp_path / "diagnosis"), timeout=60)

    report = run_agent_autonomous_diagnosis.run_diagnosis(args)

    report_path = pathlib.Path(report["report_path"])
    ledger = pathlib.Path(report["decision_ledger"])
    assert report_path.exists()
    assert ledger.exists()
    assert report["status"] == "pass"
    assert report["problem_type"] == "NO_ISSUE_DETECTED"
    assert report["actions_taken"] == []
    assert report["files_modified"] == []
