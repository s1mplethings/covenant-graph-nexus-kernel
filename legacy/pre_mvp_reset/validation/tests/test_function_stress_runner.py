from __future__ import annotations

import copy
import hashlib

import pytest

from scripts import run_function_stress_pass


def test_validator_stress_runner_uses_canonical_contracts_without_errors() -> None:
    rows = run_function_stress_pass.validator_measurements([1500])

    assert [row["case"] for row in rows] == [
        "work_nodes_forward_chain_1500",
        "provider_jobs_forward_chain_1500",
    ]
    assert {row["status"] for row in rows} == {"PASS"}
    assert {row["error_count"] for row in rows} == {0}


def test_arrival_load_uses_real_provider_job_scheduler_and_keeps_denominator(tmp_path) -> None:
    report = run_function_stress_pass.provider_job_arrival_load(
        tmp_path, planned_tasks=9, project_workers=2, overload_limit=2, arrival_interval=0.0
    )
    counts = report["accounting"]
    assert report["denominator_balanced"] is True
    assert counts["planned"] == sum(counts[key] for key in ("rejected", "cancelled", "failed", "timed_out", "execution_completed"))
    assert counts["actual_submitted"] == counts["failed"] + counts["timed_out"] + counts["execution_completed"]
    assert report["overload_fallback_observed"] is True
    assert report["verdict_sections"]["independent_acceptance"]["status"] == "PASS"
    assert report["verdict_sections"]["required_fault_coverage"]["status"] == "NOT_EVALUATED"
    assert (tmp_path / "arrival_events.jsonl").is_file()


def _valid_result_and_manifest():
    source = run_function_stress_pass._deterministic_load_source(7)
    path = "src/arbitrary_name.py"
    manifest = [{
        "path": path,
        "expected_content_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }]
    unsigned = {
        "kind": "CGKNLeafBoundaryCheckReceipt",
        "schema_version": 1,
        "component_id": "backend",
        "target_file": path,
        "status": "PASS",
        "checks": ["python_syntax"],
        "blockers": [],
    }
    receipt = {**unsigned, "receipt_sha256": run_function_stress_pass._canonical_receipt_sha256(unsigned)}
    return {"files": [{"path": path, "content": source}], "boundary_check_receipts": [receipt]}, manifest


@pytest.mark.parametrize("mutation", ["empty_receipts", "forged_receipt", "corrupt_content", "missing_file", "duplicate_file"])
def test_arrival_result_negative_controls_fail_independent_of_names(mutation: str) -> None:
    result, manifest = _valid_result_and_manifest()
    candidate = copy.deepcopy(result)
    if mutation == "empty_receipts":
        candidate["boundary_check_receipts"] = []
    elif mutation == "forged_receipt":
        candidate["boundary_check_receipts"][0]["checks"] = []
    elif mutation == "corrupt_content":
        candidate["files"][0]["content"] += "\nCORRUPTED = True\n"
    elif mutation == "missing_file":
        candidate["files"] = []
    elif mutation == "duplicate_file":
        candidate["files"].append(copy.deepcopy(candidate["files"][0]))

    verdict = run_function_stress_pass.evaluate_arrival_task_result(candidate, manifest)

    assert verdict["status"] == "FAIL"
    assert verdict["accepted"] is False


def test_arrival_result_accepts_only_complete_content_and_receipt_integrity() -> None:
    result, manifest = _valid_result_and_manifest()

    verdict = run_function_stress_pass.evaluate_arrival_task_result(result, manifest)

    assert verdict["status"] == "PASS"
    assert verdict["errors"] == []


def test_required_fault_coverage_cannot_pass_when_fault_was_not_observed(tmp_path) -> None:
    report = run_function_stress_pass.provider_job_arrival_load(
        tmp_path,
        planned_tasks=1,
        project_workers=1,
        overload_limit=1,
        arrival_interval=0.0,
        required_faults=("duplicate_callback",),
    )

    assert report["status"] == "FAIL"
    assert report["verdict_sections"]["required_fault_coverage"]["status"] == "FAIL"
    assert report["verdict_sections"]["required_fault_coverage"]["missing"] == ["duplicate_callback"]
