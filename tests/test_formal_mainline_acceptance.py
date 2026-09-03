from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

from scripts import acceptance_verifier
from scripts import browser_visual_evidence
from scripts import canonical_evidence_hash
from scripts import customer_runtime_runner
from scripts import formal_gate_registry
from scripts import formal_mainline_acceptance
from scripts import real_test_execution
from scripts import production_candidate_provenance


FIXTURE_PRODUCER = "scripts/final_internal_acceptance.py"
FORMAL_PRODUCER = "scripts/formal_mainline_acceptance.py"


def _identity(candidate_hash: str = "sha256:" + "1" * 64) -> dict[str, str]:
    return {
        "run_id": "production-run",
        "candidate_id": "customer-candidate",
        "candidate_hash": candidate_hash,
        "commit_sha": "commit-production",
    }


def _write(path: pathlib.Path, document: dict) -> pathlib.Path:
    document["artifact_hash"] = ""
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _wrapper(
    path: pathlib.Path,
    gate: str,
    *,
    status: str = "PASS",
    producer: str = FORMAL_PRODUCER,
    identity: dict[str, str] | None = None,
    source: pathlib.Path | None = None,
) -> pathlib.Path:
    source_doc = (
        json.loads(source.read_text(encoding="utf-8")) if source and source.is_file() else {}
    )
    spec = formal_gate_registry.GATE_SPECS[gate]
    return _write(
        path,
        {
            "kind": "CGKNFormalGateStatus",
            "schema_version": "1.0",
            **(identity or _identity()),
            "producer": producer,
            "created_at": "2026-07-19T00:00:00+00:00",
            "status": status,
            "gate": gate,
            "scope": spec["scope"],
            "source_ref": str(source.resolve()) if source else "",
            "source_hash": canonical_evidence_hash.sha256_file(source) if source else "",
            "source_producer": str(source_doc.get("producer", "")),
            "inspector": str(spec.get("inspector", "")),
            "inspector_result": {"status": status},
            "failures": [],
            "reason": "",
            "blocker_code": (
                "BLOCKED_USER_REVIEW" if status == "BLOCKED" else ""
            ),
        },
    )


def _fixture_source(path: pathlib.Path, gate: str = "leaf_profile") -> pathlib.Path:
    return _write(
        path,
        {
            "kind": f"CGKNFixture{gate.title()}Evidence",
            "schema_version": "1.0",
            **_identity(),
            "producer": FIXTURE_PRODUCER,
            "created_at": "2026-07-19T00:00:00+00:00",
            "status": "PASS",
        },
    )


def _formal_refs(root: pathlib.Path, *, internal_status: str = "NOT_EVALUATED") -> dict[str, pathlib.Path]:
    refs: dict[str, pathlib.Path] = {}
    for gate in acceptance_verifier.REQUIRED_GATES:
        status = (
            "BLOCKED"
            if gate in {"user_review", "delivery_manifest", "delivery_receipt"}
            else internal_status
        )
        refs[gate] = _wrapper(root / f"{gate}.json", gate, status=status)
    return refs


def test_01_final_internal_acceptance_cannot_authorize_leaf_pass(
    tmp_path: pathlib.Path,
) -> None:
    result = formal_gate_registry.inspect_gate_status(
        "leaf_profile",
        _wrapper(
            tmp_path / "leaf.json",
            "leaf_profile",
            producer=FIXTURE_PRODUCER,
        ),
        expected_identity=_identity(),
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "producer_not_authorized" in result["failures"]


def test_02_final_internal_acceptance_cannot_authorize_replan_pass(
    tmp_path: pathlib.Path,
) -> None:
    result = formal_gate_registry.inspect_gate_status(
        "replan",
        _wrapper(tmp_path / "replan.json", "replan", producer=FIXTURE_PRODUCER),
        expected_identity=_identity(),
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "producer_not_authorized" in result["failures"]


def test_03_final_internal_acceptance_cannot_authorize_recovery_pass(
    tmp_path: pathlib.Path,
) -> None:
    result = formal_gate_registry.inspect_gate_status(
        "recovery",
        _wrapper(
            tmp_path / "recovery.json", "recovery", producer=FIXTURE_PRODUCER
        ),
        expected_identity=_identity(),
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "producer_not_authorized" in result["failures"]


def test_04_handwritten_wrapper_pass_is_rejected(tmp_path: pathlib.Path) -> None:
    result = formal_gate_registry.inspect_gate_status(
        "test_execution",
        _wrapper(tmp_path / "gate.json", "test_execution", producer="unknown"),
        expected_identity=_identity(),
    )
    assert result["status"] == "NEEDS_REWORK"
    assert {"producer_not_authorized", "source_missing"} <= set(result["failures"])


def test_05_source_inspection_pass_string_is_rejected(tmp_path: pathlib.Path) -> None:
    wrapper = _wrapper(tmp_path / "gate.json", "test_execution")
    document = json.loads(wrapper.read_text(encoding="utf-8"))
    document["source_inspection"] = "PASS"
    _write(wrapper, document)
    result = formal_gate_registry.inspect_gate_status(
        "test_execution", wrapper, expected_identity=_identity()
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "deprecated_source_inspection" in result["failures"]


def test_06_gate_without_formal_inspector_cannot_pass(tmp_path: pathlib.Path) -> None:
    result = formal_gate_registry.inspect_source(
        "leaf_profile",
        _fixture_source(tmp_path / "leaf_source.json"),
        expected_identity=_identity(),
    )
    assert result["status"] == "NOT_EVALUATED"
    assert "formal_inspector_unavailable" in result["failures"]


def test_07_inspector_fail_prevents_final_verdict_pass(tmp_path: pathlib.Path) -> None:
    source = _write(
        tmp_path / "test_execution.json",
        {
            "kind": "CGKNTestExecutionEvidence",
            "schema_version": "1.0",
            **_identity(),
            "producer": "scripts/real_test_execution.py",
            "created_at": "2026-07-19T00:00:00+00:00",
            "status": "PASS",
        },
    )
    refs = _formal_refs(tmp_path / "gates")
    refs["test_execution"] = _wrapper(
        tmp_path / "gates" / "test_execution.json",
        "test_execution",
        source=source,
    )
    verdict = acceptance_verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, **_identity()
    )
    assert verdict["status"] != "PASS"
    assert (
        verdict["upstream_gates"]["test_execution"]["formal_inspection"]["status"]
        == "NEEDS_REWORK"
    )


def test_08_inspector_needs_rework_prevents_blocked_only(
    tmp_path: pathlib.Path,
) -> None:
    refs = _formal_refs(tmp_path)
    refs["replan"] = _wrapper(
        tmp_path / "replan.json", "replan", status="NEEDS_REWORK"
    )
    verdict = acceptance_verifier.produce_canonical_final_verdict(
        tmp_path, upstream_refs=refs, **_identity()
    )
    assert verdict["status"] == "NEEDS_REWORK"
    assert "replan" in verdict["internal_failures"]
    assert "BLOCKED_USER_REVIEW" in verdict["blockers"]


def test_09_different_test_runtime_visual_candidates_cannot_be_rewrapped(
    tmp_path: pathlib.Path,
) -> None:
    for gate, artifact, producer in (
        ("test_execution", "test_execution.json", "scripts/real_test_execution.py"),
        (
            "customer_runtime",
            "customer_runtime.json",
            "scripts/customer_runtime_runner.py",
        ),
        (
            "visual_evidence",
            "visual_evidence.json",
            "scripts/browser_visual_evidence.py",
        ),
    ):
        source = _write(
            tmp_path / gate / artifact,
            {
                "kind": "Fixture",
                "schema_version": "1.0",
                **_identity("sha256:" + "a" * 64),
                "producer": producer,
                "created_at": "2026-07-19T00:00:00+00:00",
                "status": "PASS",
            },
        )
        result = formal_gate_registry.inspect_gate_status(
            gate,
            _wrapper(
                tmp_path / f"{gate}_wrapper.json",
                gate,
                identity=_identity("sha256:" + "b" * 64),
                source=source,
            ),
            expected_identity=_identity("sha256:" + "b" * 64),
        )
        assert result["status"] == "NEEDS_REWORK"
        assert "candidate_identity_mismatch" in result["failures"]


def test_10_commit_hash_cannot_replace_candidate_source_hash(
    tmp_path: pathlib.Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.html").write_text("<h1>customer source</h1>", encoding="utf-8")
    actual = canonical_evidence_hash.candidate_source_hash(candidate)
    fake = "sha256:" + hashlib.sha256(b"commit-production").hexdigest()
    identity, failures = formal_mainline_acceptance._candidate_identity(
        candidate, "commit-production"
    )
    assert actual != fake
    assert identity["candidate_hash"] == actual
    assert "production_run_identity_missing_or_mixed" in failures


def test_11_codex_block_cannot_hide_internal_needs_rework() -> None:
    gates = {
        gate: {
            "status": (
                "NEEDS_REWORK"
                if gate == "recovery"
                else "BLOCKED"
                if gate in acceptance_verifier.CODEX_DEPENDENT_GATES
                else "PASS"
            ),
            "blocker_code": "BLOCKED_USER_REVIEW",
        }
        for gate in acceptance_verifier.REQUIRED_GATES
    }
    status, internal, blockers = acceptance_verifier._aggregate_status(gates)
    assert status == "NEEDS_REWORK"
    assert internal == ["recovery"]
    assert blockers == ["BLOCKED_USER_REVIEW"]


def test_12_only_codex_missing_allows_blocked_codex() -> None:
    gates = {
        gate: {
            "status": (
                "BLOCKED"
                if gate in acceptance_verifier.CODEX_DEPENDENT_GATES
                else "PASS"
            ),
            "blocker_code": "BLOCKED_USER_REVIEW",
        }
        for gate in acceptance_verifier.REQUIRED_GATES
    }
    status, internal, blockers = acceptance_verifier._aggregate_status(gates)
    assert status == "BLOCKED"
    assert internal == []
    assert blockers == ["BLOCKED_USER_REVIEW"]


def test_source_free_internal_blocker_is_rejected(
    tmp_path: pathlib.Path,
) -> None:
    result = formal_gate_registry.inspect_gate_status(
        "recovery",
        _wrapper(tmp_path / "recovery.json", "recovery", status="BLOCKED"),
        expected_identity=_identity(),
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "unsupported_source_free_blocker" in result["failures"]


def test_13_arbitrary_conversation_id_without_sources_cannot_pass(
    tmp_path: pathlib.Path,
) -> None:
    result = formal_mainline_acceptance.build_acceptance(
        tmp_path / "acceptance", codex_test_conversation_id="arbitrary"
    )
    assert result["status"] == "NEEDS_REWORK"
    for gate in ("user_review", "delivery_manifest", "delivery_receipt"):
        assert result["gates"][gate]["status"] == "NOT_EVALUATED"


@pytest.fixture
def no_chat_acceptance(tmp_path: pathlib.Path) -> pathlib.Path:
    out = tmp_path / "acceptance"
    result = formal_mainline_acceptance.build_acceptance(out)
    assert result["status"] == "NEEDS_REWORK"
    return out


def test_14_blocked_gate_does_not_create_canonical_user_review(
    no_chat_acceptance: pathlib.Path,
) -> None:
    assert not (no_chat_acceptance / "user_review.json").exists()
    assert (no_chat_acceptance / "user_review_gate_status.json").is_file()


def test_15_blocked_gate_does_not_create_canonical_delivery_manifest(
    no_chat_acceptance: pathlib.Path,
) -> None:
    assert not (no_chat_acceptance / "delivery_manifest.json").exists()
    assert (no_chat_acceptance / "delivery_manifest_gate_status.json").is_file()


def test_16_blocked_gate_does_not_create_canonical_delivery_receipt(
    no_chat_acceptance: pathlib.Path,
) -> None:
    assert not (no_chat_acceptance / "delivery_receipt.json").exists()
    assert (no_chat_acceptance / "delivery_receipt_gate_status.json").is_file()


def test_17_final_verdict_reads_disk_and_executes_inspector(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[pathlib.Path] = []
    real_inspector = formal_gate_registry.inspect_gate_status

    def recording_inspector(gate, gate_ref, **kwargs):
        calls.append(pathlib.Path(gate_ref).resolve())
        return real_inspector(gate, gate_ref, **kwargs)

    monkeypatch.setattr(
        formal_gate_registry, "inspect_gate_status", recording_inspector
    )
    refs = _formal_refs(tmp_path / "gates")
    acceptance_verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, **_identity()
    )
    assert calls == [refs[gate].resolve() for gate in acceptance_verifier.REQUIRED_GATES]


def test_18_upstream_change_breaks_final_verdict_inspection(
    tmp_path: pathlib.Path,
) -> None:
    refs = _formal_refs(tmp_path / "gates")
    acceptance_verifier.produce_canonical_final_verdict(
        tmp_path / "verdict", upstream_refs=refs, **_identity()
    )
    changed = json.loads(refs["recovery"].read_text(encoding="utf-8"))
    changed["reason"] = "changed after verdict"
    _write(refs["recovery"], changed)
    inspection = acceptance_verifier.inspect_canonical_final_verdict(
        tmp_path / "verdict",
        expected_run_id=_identity()["run_id"],
        expected_candidate_id=_identity()["candidate_id"],
        expected_candidate_hash=_identity()["candidate_hash"],
        expected_commit_sha=_identity()["commit_sha"],
        expected_upstream_refs=refs,
    )
    assert inspection["status"] == "NEEDS_REWORK"
    assert "upstream_hash_mismatch:recovery" in inspection["failures"]


def test_19_producer_change_with_new_self_hash_is_rejected(
    tmp_path: pathlib.Path,
) -> None:
    wrapper = _wrapper(tmp_path / "gate.json", "test_execution")
    changed = json.loads(wrapper.read_text(encoding="utf-8"))
    changed["producer"] = FIXTURE_PRODUCER
    _write(wrapper, changed)
    result = formal_gate_registry.inspect_gate_status(
        "test_execution", wrapper, expected_identity=_identity()
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "producer_not_authorized" in result["failures"]


def test_20_fixture_source_with_correct_self_hash_cannot_enter_formal_gate(
    tmp_path: pathlib.Path,
) -> None:
    source = _fixture_source(tmp_path / "test_execution.json", "test_execution")
    result = formal_gate_registry.inspect_source(
        "test_execution", source, expected_identity=_identity()
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "producer_not_authorized" in result["failures"]


def test_real_canonical_test_runtime_and_playwright_visual_enter_registry_pass(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.html").write_text(
        "<main><h1>Formal candidate</h1><button>Run</button></main>",
        encoding="utf-8",
    )
    tests = candidate / "tests"
    tests.mkdir()
    (tests / "test_candidate.py").write_text(
        "def test_candidate():\n    assert True\n", encoding="utf-8"
    )
    identity = {
        "run_id": "real-production-run",
        "candidate_id": "real-customer-candidate",
        "candidate_hash": canonical_evidence_hash.candidate_source_hash(candidate),
        "commit_sha": formal_mainline_acceptance.git_sha(),
    }
    run_root = tmp_path / "production-run"
    run_root.mkdir()
    provider_result = run_root / "provider_generation_result.json"
    provider_result.write_text('{"status":"PASS"}', encoding="utf-8")
    times = (
        ("2026-07-19T00:00:00+00:00", "2026-07-19T00:00:01+00:00"),
        ("2026-07-19T00:00:02+00:00", "2026-07-19T00:00:03+00:00"),
        ("2026-07-19T00:00:04+00:00", "2026-07-19T00:00:05+00:00"),
        ("2026-07-19T00:00:06+00:00", "2026-07-19T00:00:07+00:00"),
    )
    receipts = {}
    provider_ref = {
        "role": "provider_generation_result",
        "ref": str(provider_result.resolve()),
        "hash": canonical_evidence_hash.sha256_file(provider_result),
    }
    manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    manifest_hash = canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": manifest}, ()
    )
    for index, stage in enumerate(production_candidate_provenance.STAGE_ORDER):
        receipts[stage] = production_candidate_provenance.write_stage_receipt(
            run_root,
            stage=stage,
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
            candidate_root=candidate,
            started_at=times[index][0],
            finished_at=times[index][1],
            candidate_hash=identity["candidate_hash"] if stage == "post_build" else "",
            candidate_source_manifest_hash=manifest_hash if stage == "post_build" else "",
            artifact_refs=[provider_ref]
            if stage in {"provider_generation", "provider_validation"}
            else [],
        )
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        tmp_path.resolve(),
    )
    provenance = production_candidate_provenance.produce(
        candidate,
        run_root,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        stage_receipts=receipts,
        provider_result_ref=provider_result,
    )
    provenance_args = {
        "production_provenance_ref": provenance["provenance_ref"],
        "production_provenance_hash": provenance["provenance_hash"],
    }
    test_result = real_test_execution.run_tests(candidate, **identity, **provenance_args)
    runtime = customer_runtime_runner.run(
        candidate,
        **identity,
        **provenance_args,
        live_consumer=browser_visual_evidence.capture_live_runtime,
        browser_capture_required=True,
    )
    visual = browser_visual_evidence.finalize_evidence(
        candidate,
        runtime_result=runtime,
        capture_receipt=runtime["browser_capture_receipt"],
        required=True,
    )
    assert test_result["status"] == runtime["status"] == visual["status"] == "PASS"
    for gate, artifact in (
        ("test_execution", "test_execution.json"),
        ("customer_runtime", "customer_runtime.json"),
        ("visual_evidence", "visual_evidence.json"),
    ):
        inspection = formal_gate_registry.inspect_source(
            gate,
            candidate / artifact,
            expected_identity=identity,
            context={
                "production_provenance_ref": provenance[
                    "provenance_ref"
                ]
            },
        )
        assert inspection["status"] == "PASS", inspection
    acceptance = formal_mainline_acceptance.build_acceptance(
        tmp_path / "formal",
        candidate_dir=candidate,
        production_run_dir=run_root,
    )
    assert {
        gate: acceptance["gates"][gate]["status"]
        for gate in ("test_execution", "customer_runtime", "visual_evidence")
    } == {
        "test_execution": "PASS",
        "customer_runtime": "PASS",
        "visual_evidence": "PASS",
    }
    for gate in ("test_execution", "customer_runtime", "visual_evidence"):
        inspection = acceptance["gates"][gate]["formal_inspection"][
            "source_inspection"
        ]
        assert inspection["inspector_result"]["status"] == "PASS"
        assert inspection["provenance_inspection"]["status"] == "PASS"
    assert acceptance["status"] == "NEEDS_REWORK"
    assert acceptance["candidate_identity"] == identity
    assert not any(
        (tmp_path / "formal" / name).exists()
        for name in ("user_review.json", "delivery_manifest.json", "delivery_receipt.json")
    )
    run_manifest = json.loads(
        (tmp_path / "formal" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert run_manifest["codex_messages_sent"] == 0
    matrix = json.loads(
        (tmp_path / "formal" / "acceptance_matrix.json").read_text(encoding="utf-8")
    )
    verdict = json.loads(
        (tmp_path / "formal" / "final_verdict.json").read_text(encoding="utf-8")
    )
    assert matrix["status"] == verdict["status"] == acceptance["status"]
    assert {
        gate: details["status"] for gate, details in matrix["gates"].items()
    } == {
        gate: details["status"]
        for gate, details in verdict["upstream_gates"].items()
    }


def test_repository_full_all_result_is_independently_verified(
    tmp_path: pathlib.Path,
) -> None:
    commit_sha = formal_mainline_acceptance.git_sha()
    result = {
        "kind": "CGKNTestProfileResult",
        "schema_version": "1.0",
        "run_id": "full-all-run",
        "candidate_id": "CGKN",
        "candidate_hash": "",
        "commit_sha": commit_sha,
        "producer": "scripts/run_test_profile.py",
        "profile": "full_all",
        "status": "PASS",
        "exit_code": 0,
        "pytest_run": True,
        "collected": 1200,
        "executed": 1200,
        "passed": 1200,
        "failed": 0,
        "skipped": 0,
        "deselected": 0,
        "timeout": False,
        "artifact_hash": "",
    }
    path = _write(tmp_path / "full_all_result.json", result)
    inspection = formal_gate_registry.inspect_source(
        "full_all", path, expected_identity={**_identity(), "commit_sha": commit_sha}
    )
    assert inspection["status"] == "PASS", inspection


def test_formal_mainline_cli_is_directly_executable(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "cli-formal"
    proc = subprocess.run(
        [
            sys.executable,
            str(formal_mainline_acceptance.ROOT / "scripts" / "formal_mainline_acceptance.py"),
            "--out-dir",
            str(out),
        ],
        cwd=formal_mainline_acceptance.ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["status"] == "NEEDS_REWORK"
    assert (out / "run_manifest.json").is_file()
