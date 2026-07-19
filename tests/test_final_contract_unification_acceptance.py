from __future__ import annotations

import hashlib
import json
import pathlib

from scripts import canonical_evidence_hash
from scripts import final_contract_unification_acceptance as producer


def test_acceptance_run_records_missing_gates_without_false_pass(tmp_path: pathlib.Path) -> None:
    leaf = tmp_path / "live_provider_leaf"
    project = tmp_path / "customer_project"
    (project / "app").mkdir(parents=True)
    leaf.mkdir()
    product = project / "app" / "service.py"
    product.write_text("def ready(): return True\n", encoding="utf-8")
    decision = {"files": [{"path": "app/service.py"}]}
    patch = [{"path": "app/service.py", "file_hash": canonical_evidence_hash.sha256_file(product)}]
    digest = lambda value: "sha256:" + hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    trace = {
        "provider_request_identity": "request-1",
        "request_body_hash": "sha256:" + "1" * 64,
        "provider_response_id": "response-1",
        "response_content_hash": "sha256:" + "2" * 64,
        "decision": decision,
        "decision_hash": canonical_evidence_hash.canonical_json_hash(decision, ()),
        "patch": patch,
        "patch_hash": digest(patch),
        "provider_output_override": False,
    }
    (leaf / "provider_causal_trace.json").write_text(json.dumps(trace), encoding="utf-8")
    (leaf / "checkpoint_acceptance_backend_leaf.json").write_text('{"verdict":"PASS"}', encoding="utf-8")

    full_all = tmp_path / "input_full_all_result.json"
    full_all_doc = {
        "kind": "CGKNTestProfileResult",
        "profile": "full_all",
        "status": "PASS",
        "exit_code": 0,
        "pytest_run": True,
        "commit_sha": producer._git_sha(),
        "collected": 3,
        "executed": 3,
        "passed": 3,
        "failed": 0,
        "skipped": 0,
        "deselected": 0,
        "artifact_hash": "",
    }
    full_all_doc["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        full_all_doc, ("artifact_hash",)
    )
    full_all.write_text(json.dumps(full_all_doc), encoding="utf-8")

    result = producer.build_acceptance(tmp_path, full_all_result=full_all)

    assert result["verdict"] == "BLOCKED"
    matrix = json.loads((tmp_path / "acceptance_matrix.json").read_text(encoding="utf-8"))
    assert matrix["gates"]["provider_causal_trace"] == "PASS"
    assert matrix["gates"]["full_all"] == "PASS"
    assert matrix["gates"]["delivery_receipt"] == "BLOCKED"
    assert matrix["gates"]["replan"] == "NOT_EVALUATED"
    assert (tmp_path / "final_verdict.json").is_file()
