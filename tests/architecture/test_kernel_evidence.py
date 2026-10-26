from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_kernel_test_receipt import _canonical_hash
from kernel_source_identity import identity
from run_kernel_profiles import _profile_status
from verify_kernel_test_receipt import verify


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary, pytest.mark.determinism]


def test_source_identity_is_stable_and_bound_to_git_tree() -> None:
    first = identity("HEAD")
    second = identity(first["source_commit"])
    assert first == second
    assert len(first["source_commit"]) == len(first["source_tree_sha"]) == 40
    assert first["core_source_hash"].startswith("sha256:")


@pytest.mark.negative
def test_source_identity_rejects_unknown_commit() -> None:
    with pytest.raises(RuntimeError):
        identity("not-a-real-commit")


@pytest.mark.security
def test_receipt_verifier_rejects_tamper_and_source_mismatch(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = identity("HEAD")
    coverage = ROOT / "governance" / "kernel_coverage_report.json"
    value = {
        "kind": "CGKNKernelTestReceipt", "schema_version": "1.0", **{key: source[key] for key in ("source_commit", "source_tree_sha", "core_source_hash")},
        "commands": [], "totals": {"passed": 1, "failed": 0, "errors": 0, "skipped": 0, "duration_seconds": 0},
        "test_node_ids": ["tests/x.py::test_x"], "profile_results": [],
        "coverage_file_hash": "sha256:" + hashlib.sha256(coverage.read_bytes()).hexdigest(), "generated_at": "2026-10-15T00:00:00+00:00",
        "environment": {}, "provider_network_usage": {"live_provider_executed": False, "secret_persisted": False}, "final_verdict": "PASS",
    }
    value["receipt_hash"] = _canonical_hash(value)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert verify(path)["status"] == "PASS"
    value["totals"]["failed"] = 1
    path.write_text(json.dumps(value), encoding="utf-8")
    result = verify(path)
    assert result["status"] == "FAIL"
    assert {"receipt_hash_mismatch", "receipt_not_pass"}.issubset(result["errors"])


@pytest.mark.negative
def test_live_provider_all_skipped_is_not_reported_as_pass() -> None:
    status, reason = _profile_status("live-provider", [{"returncode": 0}], {"passed": 0, "failed": 0, "errors": 0, "skipped": 2})
    assert status == "BLOCKED_ENVIRONMENT"
    assert reason and "not executed" in reason
    assert _profile_status("live-provider", [{"returncode": 0}], {"passed": 1, "failed": 0, "errors": 0, "skipped": 0}) == ("PASS", None)
