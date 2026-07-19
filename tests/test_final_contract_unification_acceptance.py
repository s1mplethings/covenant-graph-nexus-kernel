from __future__ import annotations

import json
import pathlib

from scripts import canonical_evidence_hash
from scripts import final_contract_unification_acceptance as compatibility
from scripts import formal_mainline_acceptance


def test_compatibility_entry_delegates_to_formal_reader_without_fake_artifacts(
    tmp_path: pathlib.Path,
) -> None:
    full_all = tmp_path / "full_all_result.json"
    document = {
        "kind": "CGKNTestProfileResult",
        "schema_version": "1.0",
        "run_id": "repository-full-all",
        "candidate_id": "CGKN",
        "candidate_hash": "repository-scope",
        "commit_sha": formal_mainline_acceptance.git_sha(),
        "producer": "scripts/run_test_profile.py",
        "created_at": "2026-07-19T00:00:00+00:00",
        "profile": "full_all",
        "status": "PASS",
        "exit_code": 0,
        "pytest_run": True,
        "collected": 3,
        "executed": 3,
        "passed": 3,
        "failed": 0,
        "skipped": 0,
        "deselected": 0,
        "timeout": False,
        "artifact_hash": "",
    }
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    )
    full_all.write_text(json.dumps(document), encoding="utf-8")

    result = compatibility.build_acceptance(tmp_path / "formal", full_all_result=full_all)

    assert result["status"] == "NEEDS_REWORK"
    assert result["gates"]["full_all"]["status"] == "PASS"
    assert result["gates"]["leaf_profile"]["status"] == "NOT_EVALUATED"
    assert result["gates"]["replan"]["status"] == "NOT_EVALUATED"
    assert result["gates"]["recovery"]["status"] == "NOT_EVALUATED"
    assert not (tmp_path / "formal" / "user_review.json").exists()
    assert not (tmp_path / "formal" / "delivery_manifest.json").exists()
    assert not (tmp_path / "formal" / "delivery_receipt.json").exists()
    assert (tmp_path / "formal" / "user_review_gate_status.json").is_file()
