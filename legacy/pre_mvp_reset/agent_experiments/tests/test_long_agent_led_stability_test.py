from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_long_agent_led_stability_test


def verify_record(status: str = "pass") -> dict:
    return {
        "kind": "verify",
        "status": status,
        "report_path": "verify.json",
        "director_loop_used": status == "pass",
        "selected_tools": ["formal_generation:api_first", "formal_generation:local_only", "final_promotion"] if status == "pass" else [],
        "agent_decision_ledger": "agent_decision_ledger.jsonl" if status == "pass" else "",
        "provider_quota_exceeded": True,
        "fallback_used": status == "pass",
        "final_project_exists": status == "pass",
        "delivery_manifest_exists": status == "pass",
        "final_bundle_exists": status == "pass",
        "screenshot_evidence_exists": status == "pass",
        "public_gate_ready": status == "pass",
        "commercial_status": "COMMERCIAL_READY" if status == "pass" else "COMMERCIAL_BETA",
        "remaining_blockers": [],
    }


def benchmark_record(status: str = "pass") -> dict:
    return {
        "kind": "benchmark",
        "status": status,
        "report_path": "benchmark.json",
        "director_loop_used": status == "pass",
        "selected_tools": ["formal_generation:local_first", "final_promotion"] if status == "pass" else [],
        "final_project_exists": status == "pass",
        "delivery_manifest_exists": status == "pass",
        "final_bundle_exists": status == "pass",
        "screenshot_evidence_exists": status == "pass",
        "complexity_status": "pass" if status == "pass" else "fail",
        "page_count": 9 if status == "pass" else 2,
        "module_count": 9 if status == "pass" else 1,
        "product_acceptance_status": "pass" if status == "pass" else "fail",
        "commercial_status": "COMMERCIAL_READY" if status == "pass" else "COMMERCIAL_BETA",
        "remaining_blockers": [],
    }


def diagnosis_record(status: str = "pass") -> dict:
    return {
        "kind": "diagnosis",
        "status": status,
        "report_path": "diagnosis.json",
        "problem_type": "NO_ISSUE_DETECTED" if status == "pass" else "UNKNOWN",
        "selected_tool": "stability_rerun",
        "remaining_blockers": [],
        "commercial_status": "COMMERCIAL_READY" if status == "pass" else "COMMERCIAL_BETA",
    }


def fault_report(status: str = "pass") -> dict:
    cases = [{"case": "missing_decision_ledger", "status": status, "actual_problem_type": "AGENT_DECISION_LEDGER_MISSING"}]
    return {
        "status": status,
        "fault_injection_cases": len(cases),
        "fault_injection_pass": sum(1 for case in cases if case["status"] == "pass"),
        "cases": cases,
        "output_dir": "faults",
    }


def test_component_stability_scoring_marks_flaky() -> None:
    scores = run_long_agent_led_stability_test.score_components(
        {
            "provider_fallback": [
                {"passed": True, "evidence_ref": "a", "note": ""},
                {"passed": False, "evidence_ref": "b", "note": "intermittent"},
            ]
        }
    )
    provider = next(item for item in scores if item["component"] == "provider_fallback")

    assert provider["status"] == "flaky"
    assert provider["pass_count"] == 1
    assert provider["fail_count"] == 1


def test_aggregate_report_schema_and_counts(tmp_path: pathlib.Path) -> None:
    records = [verify_record(), benchmark_record(), diagnosis_record()]
    report = run_long_agent_led_stability_test.aggregate_report(
        records,
        fault_report(),
        report_path=tmp_path / "long_agent_led_stability_report.json",
        runs_ledger=tmp_path / "long_agent_led_stability_runs.jsonl",
    )

    assert report["status"] == "pass"
    assert report["total_runs"] == 4
    assert report["verify_pass"] == 1
    assert report["benchmark_pass"] == 1
    assert report["diagnosis_pass"] == 1
    assert report["commercial_ready_count"] == 3
    assert report["fallback_used_count"] == 1
    assert report["quota_detected_count"] == 1
    assert "component_scores" in report
    assert "stable_components" in report
    assert "unstable_components" in report


def test_jsonl_run_ledger_write(tmp_path: pathlib.Path) -> None:
    ledger = tmp_path / "long_agent_led_stability_runs.jsonl"

    run_long_agent_led_stability_test.append_jsonl(ledger, {"kind": "verify", "status": "pass"})
    run_long_agent_led_stability_test.append_jsonl(ledger, {"kind": "diagnosis", "status": "pass"})

    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in rows] == ["verify", "diagnosis"]


def test_flaky_failure_statistics_surface_recommended_fix(tmp_path: pathlib.Path) -> None:
    records = [verify_record("pass"), verify_record("fail"), benchmark_record(), diagnosis_record()]
    report = run_long_agent_led_stability_test.aggregate_report(
        records,
        fault_report(),
        report_path=tmp_path / "report.json",
        runs_ledger=tmp_path / "runs.jsonl",
    )

    assert report["status"] == "partial"
    assert report["flaky_failures"]
    assert report["recommended_next_fixes"]
