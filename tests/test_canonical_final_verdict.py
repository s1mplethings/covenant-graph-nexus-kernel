from __future__ import annotations

import json
import pathlib

import pytest

import scripts.acceptance_verifier as verifier
import scripts.canonical_evidence_hash as evidence_hash
import scripts.formal_gate_registry as gate_registry
from scripts import goal_acceptance


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


def passing_goal_support(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    project = root / "candidate"
    run = root / "run"
    (project / "tests").mkdir(parents=True, exist_ok=True)
    requirement = run / "requirement_decision"
    requirement.mkdir(parents=True, exist_ok=True)
    behaviors = ["timer completes a focus session"]
    symbol = "test_timer_completes_focus_session"
    (requirement / "goal_spec.json").write_text(
        json.dumps({"kind": "GoalSpec", "status": "PASS", "goal": "Pomodoro", "domain": "productivity", "acceptance_behaviors": behaviors}),
        encoding="utf-8",
    )
    (requirement / "project_plan.json").write_text(
        json.dumps({"kind": "GoalDrivenProjectPlan", "status": "PASS", "goal": "Pomodoro", "domain": "productivity", "test_intents": behaviors, "goal_acceptance_tests": [{"intent": behaviors[0], "test_symbol": symbol}]}),
        encoding="utf-8",
    )
    (project / "tests" / "test_timer.py").write_text(
        "def test_timer_completes_focus_session():\n    result = sum([1, 2])\n    assert result == 3\n",
        encoding="utf-8",
    )
    (project / "test_execution.json").write_text(
        json.dumps({
            "kind": "CGKNTestExecutionEvidence",
            "producer": "scripts/real_test_execution.py",
            "status": "PASS",
            "argv": ["python", "-m", "pytest"],
            "exit_code": 0,
            "skipped": 0,
        }),
        encoding="utf-8",
    )
    receipt = goal_acceptance.evaluate_goal_acceptance(
        project_dir=project,
        run_dir=run,
        test_result={"status": "pass", "argv": ["python", "-m", "pytest"], "returncode": 0},
    )
    artifact = run / "artifacts" / goal_acceptance.FILE_NAME
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(receipt), encoding="utf-8")
    return project, run


def trust_formal_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate_registry,
        "inspect_gate_status",
        lambda name, path, **kwargs: {"status": json.loads(pathlib.Path(path).read_text(encoding="utf-8"))["status"], "failures": []},
    )


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


def test_applicable_goal_acceptance_is_veto_only(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_formal_wrappers(monkeypatch)
    refs = {name: write_gate(tmp_path / f"{name}.json", name, "PASS") for name in verifier.REQUIRED_GATES}
    project, run = passing_goal_support(tmp_path / "support")
    context = {"candidate_dir": str(project), "production_run_dir": str(run)}
    verdict = verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, inspection_context=context, **IDENTITY
    )
    assert verdict["status"] == "PASS"
    assert verdict["support_prerequisites"]["goal_acceptance"]["status"] == "PASS"
    write_gate(refs["recovery"], "recovery", "NEEDS_REWORK")
    verdict = verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, inspection_context=context, **IDENTITY
    )
    assert verdict["status"] == "NEEDS_REWORK"


def test_missing_or_tampered_applicable_goal_acceptance_prevents_pass(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_formal_wrappers(monkeypatch)
    refs = {name: write_gate(tmp_path / f"{name}.json", name, "PASS") for name in verifier.REQUIRED_GATES}
    project, run = passing_goal_support(tmp_path / "support")
    receipt_path = run / "artifacts" / goal_acceptance.FILE_NAME
    receipt_path.unlink()
    context = {"candidate_dir": str(project), "production_run_dir": str(run)}
    missing = verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, inspection_context=context, **IDENTITY
    )
    assert missing["status"] == "NEEDS_REWORK"
    assert "goal_acceptance_receipt_missing" in missing["support_prerequisites"]["goal_acceptance"]["inspection"]["failures"]
    _, run = passing_goal_support(tmp_path / "support")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["status"] = "PASS"
    receipt["mapped_tests"][0]["matches"][0]["source_sha256"] = "forged"
    receipt["receipt_sha256"] = goal_acceptance._canonical_hash({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    tampered = verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, inspection_context=context, **IDENTITY
    )
    assert tampered["status"] == "NEEDS_REWORK"
    assert "goal_acceptance_recomputed_mismatch:mapped_tests" in tampered["support_prerequisites"]["goal_acceptance"]["inspection"]["failures"]


def test_forged_goal_execution_summary_cannot_replace_canonical_test_evidence(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_formal_wrappers(monkeypatch)
    refs = {name: write_gate(tmp_path / f"{name}.json", name, "PASS") for name in verifier.REQUIRED_GATES}
    project, run = passing_goal_support(tmp_path / "support")
    receipt_path = run / "artifacts" / goal_acceptance.FILE_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["test_execution"]["argv"] = ["python", "-m", "pytest", "forged_only.py"]
    receipt["receipt_sha256"] = goal_acceptance._canonical_hash({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    verdict = verifier.produce_canonical_final_verdict(
        tmp_path / "verdict",
        upstream_refs=refs,
        inspection_context={"candidate_dir": str(project), "production_run_dir": str(run)},
        **IDENTITY,
    )
    assert verdict["status"] == "NEEDS_REWORK"
    assert "goal_acceptance_recomputed_mismatch:test_execution" in verdict["support_prerequisites"]["goal_acceptance"]["inspection"]["failures"]


def test_legacy_run_without_goal_plan_preserves_final_verdict(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_formal_wrappers(monkeypatch)
    refs = {name: write_gate(tmp_path / f"{name}.json", name, "PASS") for name in verifier.REQUIRED_GATES}
    project = tmp_path / "candidate"
    run = tmp_path / "run"
    project.mkdir()
    run.mkdir()
    (run / "requirement_decision").mkdir()
    verdict = verifier.produce_canonical_final_verdict(
        tmp_path / "verdict",
        upstream_refs=refs,
        inspection_context={"candidate_dir": str(project), "production_run_dir": str(run)},
        **IDENTITY,
    )
    assert verdict["status"] == "PASS"
    assert verdict["support_prerequisites"]["goal_acceptance"]["applicable"] is False


def test_final_verdict_reinspection_detects_goal_source_change(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_formal_wrappers(monkeypatch)
    refs = {name: write_gate(tmp_path / f"{name}.json", name, "PASS") for name in verifier.REQUIRED_GATES}
    project, run = passing_goal_support(tmp_path / "support")
    context = {"candidate_dir": str(project), "production_run_dir": str(run)}
    verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, inspection_context=context, **IDENTITY
    )
    test_path = project / "tests" / "test_timer.py"
    test_path.write_text(test_path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    inspection = verifier.inspect_canonical_final_verdict(
        tmp_path / "verdict",
        expected_run_id=IDENTITY["run_id"],
        expected_candidate_id=IDENTITY["candidate_id"],
        expected_candidate_hash=IDENTITY["candidate_hash"],
        expected_commit_sha=IDENTITY["commit_sha"],
        expected_upstream_refs=refs,
        inspection_context=context,
    )
    assert inspection["status"] == "NEEDS_REWORK"
    assert "goal_acceptance" in inspection["nonpass_support"]
    assert "goal_acceptance_support_mismatch:inspection" in inspection["failures"]
