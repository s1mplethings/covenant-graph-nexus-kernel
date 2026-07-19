from __future__ import annotations

import json
import pathlib

import pytest

from scripts import canonical_evidence_hash
from scripts import final_internal_acceptance
from scripts import formal_gate_registry


@pytest.mark.e2e
def test_internal_acceptance_executes_diagnostic_fixtures_only(
    tmp_path: pathlib.Path,
) -> None:
    assert final_internal_acceptance.DIAGNOSTIC_FIXTURE_ONLY is True
    result = final_internal_acceptance.build_internal_acceptance(tmp_path / "acceptance-run")

    assert result["status"] == "PASS"
    for name in (
        "internal_leaf_sessions.json",
        "internal_workspace_inventory.json",
        "internal_collaboration_evidence.json",
        "internal_replan_evidence.json",
        "internal_recovery_evidence.json",
        "internal_startup_profile.json",
    ):
        document = json.loads((tmp_path / "acceptance-run" / name).read_text(encoding="utf-8"))
        assert document["status"] == "PASS", name
    leaf = tmp_path / "acceptance-run" / "internal_leaf_sessions.json"
    identity = json.loads(leaf.read_text(encoding="utf-8"))
    formal = {
        "kind": "CGKNFormalGateStatus",
        "schema_version": "1.0",
        **{
            key: identity[key]
            for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha")
        },
        "producer": final_internal_acceptance.PRODUCER,
        "created_at": identity["created_at"],
        "status": "PASS",
        "artifact_hash": "",
        "gate": "leaf_profile",
        "scope": "candidate",
        "source_ref": str(leaf.resolve()),
        "source_hash": canonical_evidence_hash.sha256_file(leaf),
        "source_producer": final_internal_acceptance.PRODUCER,
        "inspector": "",
        "inspector_result": {"status": "PASS"},
        "failures": [],
        "reason": "",
        "blocker_code": "",
    }
    formal["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        formal, ("artifact_hash",)
    )
    formal_path = tmp_path / "acceptance-run" / "formal_leaf_attempt.json"
    formal_path.write_text(json.dumps(formal), encoding="utf-8")
    rejection = formal_gate_registry.inspect_gate_status(
        "leaf_profile",
        formal_path,
        expected_identity={
            key: identity[key]
            for key in ("run_id", "candidate_id", "candidate_hash", "commit_sha")
        },
    )
    assert rejection["status"] == "NEEDS_REWORK"
    assert "producer_not_authorized" in rejection["failures"]
    deterministic = json.loads(
        (tmp_path / "acceptance-run" / "internal_deterministic_e2e.json").read_text(encoding="utf-8")
    )
    assert deterministic["status"] == "BLOCKED"
    assert deterministic["blocker_code"] == "BLOCKED_TELEGRAM_TEST_CHAT"
