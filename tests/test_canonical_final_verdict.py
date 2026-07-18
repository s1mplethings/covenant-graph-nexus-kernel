from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.acceptance_verifier as verifier
import scripts.canonical_evidence_hash as evidence_hash


IDENTITY = {
    "run_id": "run-final",
    "candidate_id": "candidate-final",
    "candidate_hash": "sha256:" + "1" * 64,
    "commit_sha": "commit-final",
}


def write_gate(path: pathlib.Path, name: str, status: str = "PASS") -> None:
    document = {
        "kind": f"Test{name}",
        "schema_version": "1.0",
        **IDENTITY,
        "producer": "tests",
        "created_at": "2026-07-18T00:00:00+00:00",
        "status": status,
        "artifact_hash": "",
    }
    document["artifact_hash"] = evidence_hash.canonical_json_hash(document, ("artifact_hash",))
    path.write_text(json.dumps(document), encoding="utf-8")


def gate_refs(root: pathlib.Path) -> dict[str, pathlib.Path]:
    refs = {}
    for name in verifier.REQUIRED_GATES:
        path = root / f"{name}.json"
        write_gate(path, name)
        refs[name] = path
    return refs


def test_all_required_disk_gates_pass(tmp_path: pathlib.Path) -> None:
    refs = gate_refs(tmp_path)
    verdict = verifier.produce_canonical_final_verdict(tmp_path, upstream_refs=refs, **IDENTITY)
    inspection = verifier.inspect_canonical_final_verdict(
        tmp_path,
        expected_run_id=IDENTITY["run_id"],
        expected_candidate_id=IDENTITY["candidate_id"],
        expected_candidate_hash=IDENTITY["candidate_hash"],
        expected_commit_sha=IDENTITY["commit_sha"],
        expected_upstream_refs=refs,
    )
    assert verdict["status"] == "PASS"
    assert inspection["status"] == "PASS"


def test_missing_nonpass_and_pass_with_limits_cannot_pass(tmp_path: pathlib.Path) -> None:
    refs = gate_refs(tmp_path)
    write_gate(refs["recovery"], "recovery", "NOT_EVALUATED")
    write_gate(refs["full_all"], "full_all", "PASS_WITH_LIMITS")
    refs.pop("live_provider_e2e")
    verdict = verifier.produce_canonical_final_verdict(tmp_path, upstream_refs=refs, **IDENTITY)
    assert verdict["status"] == "NEEDS_REWORK"
    assert "gate_not_pass:recovery:NOT_EVALUATED" in verdict["failures"]
    assert "gate_not_pass:full_all:PASS_WITH_LIMITS" in verdict["failures"]
    assert "missing_gate:live_provider_e2e" in verdict["failures"]


def test_rehashing_verdict_cannot_hide_upstream_tamper(tmp_path: pathlib.Path) -> None:
    refs = gate_refs(tmp_path)
    verifier.produce_canonical_final_verdict(tmp_path, upstream_refs=refs, **IDENTITY)
    write_gate(refs["delivery_receipt"], "delivery_receipt", "FAIL")
    verdict_path = tmp_path / verifier.FILE_NAME
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["artifact_hash"] = evidence_hash.canonical_json_hash(verdict, ("artifact_hash",))
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    inspection = verifier.inspect_canonical_final_verdict(
        tmp_path,
        expected_run_id=IDENTITY["run_id"],
        expected_candidate_id=IDENTITY["candidate_id"],
        expected_candidate_hash=IDENTITY["candidate_hash"],
        expected_commit_sha=IDENTITY["commit_sha"],
        expected_upstream_refs=refs,
    )
    assert inspection["status"] == "NEEDS_REWORK"
    assert "delivery_receipt" in inspection["nonpass_gates"]
    assert "upstream_hash_mismatch:delivery_receipt" in inspection["failures"]
