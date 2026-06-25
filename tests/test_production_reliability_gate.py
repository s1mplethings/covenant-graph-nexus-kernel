from __future__ import annotations

import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import production_reliability_gate


def passing_records(count: int = 3) -> list[dict]:
    return [
        {
            "status": "PASS",
            "timed_out": False,
            "invalid_output": False,
            "artifact_integrity_status": "PASS",
            "runtime_seconds": 0.5 + index * 0.1,
            "output_hash": "stable-output-hash",
        }
        for index in range(count)
    ]


def test_empty_reliability_evidence_is_not_ready(tmp_path: pathlib.Path) -> None:
    report = production_reliability_gate.empty_report(tmp_path / "report.json")

    assert report["reliability_status"] == "not_ready"
    assert report["run_count"] == 0
    assert "reliability_run_count_below_minimum" in report["blockers"]


def test_repeat_runs_pass_with_deterministic_outputs(tmp_path: pathlib.Path) -> None:
    report = production_reliability_gate.evaluate(
        run_records=passing_records(),
        output_path=tmp_path / "report.json",
        gate_test_only=True,
    )

    assert report["reliability_status"] == "pass"
    assert report["run_count"] == report["successful_runs"] == 3
    assert report["failed_runs"] == report["timeout_runs"] == report["invalid_output_runs"] == 0
    assert report["deterministic_outputs"] is True
    assert report["average_runtime_seconds"] == 0.6
    assert report["max_runtime_seconds"] == 0.7


def test_run_count_below_threshold_fails() -> None:
    report = production_reliability_gate.evaluate(run_records=passing_records(2))

    assert report["reliability_status"] == "fail"
    assert "reliability_run_count_below_minimum" in report["blockers"]


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("status", "FAIL", "reliability_failed_runs_above_threshold"),
        ("timed_out", True, "reliability_timeout_runs_above_threshold"),
        ("invalid_output", True, "reliability_invalid_output_runs_above_threshold"),
        ("artifact_integrity_status", "FAIL", "reliability_artifact_integrity_failures_above_threshold"),
    ],
)
def test_repeat_failure_modes_are_counted(field: str, value, blocker: str) -> None:
    records = passing_records()
    records[1][field] = value

    report = production_reliability_gate.evaluate(run_records=records)

    assert report["reliability_status"] == "fail"
    assert blocker in report["blockers"]


def test_non_deterministic_output_hashes_fail() -> None:
    records = passing_records()
    records[2]["output_hash"] = "different"

    report = production_reliability_gate.evaluate(run_records=records)

    assert report["deterministic_outputs"] is False
    assert "reliability_outputs_not_deterministic" in report["blockers"]
