from __future__ import annotations

import json
import pathlib

import scripts.acceptance_verifier as verifier
import scripts.canonical_evidence_hash as evidence_hash
import scripts.formal_gate_registry as gate_registry


IDENTITY = {
    "run_id": "run-final",
    "candidate_id": "candidate-final",
    "candidate_hash": "sha256:" + "1" * 64,
    "commit_sha": "commit-final",
}


def write_gate(path: pathlib.Path, name: str, status: str) -> pathlib.Path:
    spec = gate_registry.GATE_SPECS[name]
    document = {
        "kind": "CGKNFormalGateStatus",
        "schema_version": "1.0",
        **IDENTITY,
        "producer": gate_registry.FORMAL_GATE_STATUS_PRODUCER,
        "created_at": "2026-07-18T00:00:00+00:00",
        "status": status,
        "artifact_hash": "",
        "gate": name,
        "scope": spec["scope"],
        "source_ref": "",
        "source_hash": "",
        "source_producer": "",
        "inspector": spec["inspector"],
        "inspector_result": {"status": status},
        "failures": [],
        "reason": "",
        "blocker_code": (
            "BLOCKED_TELEGRAM_TEST_CHAT" if status == "BLOCKED" else ""
        ),
    }
    document["artifact_hash"] = evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    )
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def gate_refs(root: pathlib.Path) -> dict[str, pathlib.Path]:
    refs = {}
    for name in verifier.REQUIRED_GATES:
        status = (
            "BLOCKED"
            if name in {"user_review", "delivery_manifest", "delivery_receipt"}
            else "NOT_EVALUATED"
        )
        refs[name] = write_gate(root / f"{name}.json", name, status)
    return refs


def test_arbitrary_disk_pass_documents_cannot_authorize_final_pass(
    tmp_path: pathlib.Path,
) -> None:
    refs = {}
    for name in verifier.REQUIRED_GATES:
        path = tmp_path / f"{name}.json"
        document = {
            "kind": f"Test{name}",
            "schema_version": "1.0",
            **IDENTITY,
            "producer": "tests",
            "created_at": "2026-07-18T00:00:00+00:00",
            "status": "PASS",
            "artifact_hash": "",
        }
        document["artifact_hash"] = evidence_hash.canonical_json_hash(
            document, ("artifact_hash",)
        )
        path.write_text(json.dumps(document), encoding="utf-8")
        refs[name] = path
    verdict = verifier.produce_canonical_final_verdict(
        tmp_path, upstream_refs=refs, **IDENTITY
    )
    assert verdict["status"] == "NEEDS_REWORK"
    assert all(
        gate["formal_inspection"]["failures"]
        == ["upstream_not_formal_gate_status"]
        for gate in verdict["upstream_gates"].values()
    )


def test_nonpass_and_pass_with_limits_cannot_pass(tmp_path: pathlib.Path) -> None:
    refs = gate_refs(tmp_path)
    write_gate(refs["recovery"], "recovery", "NEEDS_REWORK")
    write_gate(refs["full_all"], "full_all", "PASS_WITH_LIMITS")
    refs.pop("live_provider_e2e")
    verdict = verifier.produce_canonical_final_verdict(
        tmp_path, upstream_refs=refs, **IDENTITY
    )
    assert verdict["status"] == "NEEDS_REWORK"
    assert "gate_not_pass:recovery:NEEDS_REWORK" in verdict["failures"]
    assert "gate_not_pass:full_all:NEEDS_REWORK" in verdict["failures"]
    assert "missing_gate:live_provider_e2e" in verdict["failures"]


def test_rehashing_verdict_cannot_hide_upstream_tamper(
    tmp_path: pathlib.Path,
) -> None:
    refs = gate_refs(tmp_path)
    verifier.produce_canonical_final_verdict(tmp_path, upstream_refs=refs, **IDENTITY)
    write_gate(refs["delivery_receipt"], "delivery_receipt", "NEEDS_REWORK")
    verdict_path = tmp_path / verifier.FILE_NAME
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["artifact_hash"] = evidence_hash.canonical_json_hash(
        verdict, ("artifact_hash",)
    )
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
