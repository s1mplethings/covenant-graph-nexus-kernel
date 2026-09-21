from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import time

import jsonschema
import pytest

from scripts import canonical_evidence_hash
from scripts import formal_gate_registry
from scripts import formal_mainline_acceptance
from scripts import production_candidate_provenance
from scripts import provider_causal_trace
from scripts import codex_conversation


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rehash(path: pathlib.Path, document: dict) -> None:
    document["artifact_hash"] = ""
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    )
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write(path: pathlib.Path, document: dict) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _artifact_refs(capture: dict) -> list[dict[str, str]]:
    return [
        {
            "role": role,
            "ref": str(pathlib.Path(capture[key]).resolve()),
            "hash": canonical_evidence_hash.sha256_file(capture[key]),
        }
        for role, key in (
            ("provider_request", "request_ref"),
            ("provider_response", "response_ref"),
            ("implementation_decision", "decision_ref"),
            ("implementation_patch", "patch_ref"),
            ("patch_application", "application_ref"),
        )
    ]


def _begin_request(
    candidate: pathlib.Path,
    run_root: pathlib.Path,
    identity: dict[str, str],
    *,
    goal: str,
) -> dict:
    return provider_causal_trace.begin_provider_request(
        candidate_dir=candidate,
        production_run_dir=run_root,
        identity=identity,
        goal=goal,
        model="reproducible-provider",
        request_started_at=provider_causal_trace.now(),
    )


def _valid_case(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> dict:
    allowed_root = tmp_path / "production_candidates"
    candidate = allowed_root / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "generation_context_snapshot.json").write_text(
        '{"goal":"causal trace"}\n', encoding="utf-8"
    )
    staging = tmp_path / "provider_staging"
    staging.mkdir()
    response_files = {
        "README.md": "# Causal candidate\n",
        "index.html": "<main><h1>Causal candidate</h1></main>\n",
        "app.js": "document.body.dataset.causal = 'applied';\n",
        "tests/test_candidate.py": (
            "def test_candidate():\n"
            "    assert 'applied' in open('app.js', encoding='utf-8').read()\n"
        ),
    }
    for relative, content in response_files.items():
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    run_root = tmp_path / "production_run"
    run_root.mkdir()
    result_path = _write(
        run_root / "provider_generation_result.json",
        {
            "status": "PASS",
            "generated_files": sorted(response_files),
            "provider_response_id": "provider-response-a",
            "provider_semantic_review": {"status": "pass"},
            "artifact_refs": {},
            "agent_usage": {
                "status": "pass",
                "events": [{"command": "python -m pytest tests"}],
            },
            "example_outputs": {},
        },
    )
    identity = {
        "run_id": "production-causal-run",
        "candidate_id": "customer-causal-candidate",
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
    }
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        allowed_root.resolve(),
    )
    entry_started = provider_causal_trace.now()
    entry_receipt = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="production_entry",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=candidate,
        started_at=entry_started,
        finished_at=provider_causal_trace.now(),
    )
    request_started = provider_causal_trace.now()
    request_capture = provider_causal_trace.begin_provider_request(
        candidate_dir=candidate,
        production_run_dir=run_root,
        identity=identity,
        goal="Build a causal candidate",
        model="reproducible-provider",
        request_started_at=request_started,
    )
    capture = provider_causal_trace.consume_provider_response(
        candidate_dir=candidate,
        provider_staging_dir=staging,
        production_run_dir=run_root,
        provider_result_path=result_path,
        identity=identity,
        provider_request_capture=request_capture,
        response_received_at=provider_causal_trace.now(),
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["project_dir"] = str(candidate.resolve())
    result["provider_staging_dir"] = str(staging.resolve())
    result["provider_causal_artifacts"] = {
        key: str(pathlib.Path(value).resolve())
        if key.endswith("_ref")
        else value
        for key, value in capture.items()
    }
    _write(result_path, result)
    result_hash = canonical_evidence_hash.sha256_file(result_path)
    refs = _artifact_refs(capture)
    generation_receipt = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="provider_generation",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=candidate,
        started_at=request_started,
        finished_at=provider_causal_trace.now(),
        artifact_refs=[
            {
                "role": "provider_generation_result",
                "ref": str(result_path.resolve()),
                "hash": result_hash,
            },
            *refs,
        ],
    )
    validation_started = provider_causal_trace.now()
    validation_receipt = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="provider_validation",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=candidate,
        started_at=validation_started,
        finished_at=provider_causal_trace.now(),
        artifact_refs=[
            {
                "role": "provider_generation_result",
                "ref": str(result_path.resolve()),
                "hash": result_hash,
            },
            {
                "role": "provider_generation_receipt",
                "ref": str(generation_receipt.resolve()),
                "hash": canonical_evidence_hash.sha256_file(
                    generation_receipt
                ),
            },
            *refs,
        ],
    )
    manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    candidate_hash = canonical_evidence_hash.candidate_source_hash(candidate)
    manifest_hash = canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": manifest}, ()
    )
    post_build_started = provider_causal_trace.now()
    post_build_receipt = production_candidate_provenance.write_stage_receipt(
        run_root,
        stage="post_build",
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        candidate_root=candidate,
        started_at=post_build_started,
        finished_at=provider_causal_trace.now(),
        candidate_hash=candidate_hash,
        candidate_source_manifest_hash=manifest_hash,
        artifact_refs=[
            {
                "role": "provider_validation_receipt",
                "ref": str(validation_receipt.resolve()),
                "hash": canonical_evidence_hash.sha256_file(
                    validation_receipt
                ),
            }
        ],
    )
    receipts = {
        "production_entry": entry_receipt,
        "provider_generation": generation_receipt,
        "provider_validation": validation_receipt,
        "post_build": post_build_receipt,
    }
    provenance = production_candidate_provenance.produce(
        candidate,
        run_root,
        run_id=identity["run_id"],
        candidate_id=identity["candidate_id"],
        commit_sha=identity["commit_sha"],
        stage_receipts=receipts,
        provider_result_ref=result_path,
    )
    trace = provider_causal_trace.finalize(
        candidate_dir=candidate,
        production_run_dir=run_root,
        identity=identity,
        causal_capture=capture,
        production_provenance_ref=provenance["provenance_ref"],
    )
    identity["candidate_hash"] = candidate_hash
    return {
        "allowed_root": allowed_root,
        "candidate": candidate,
        "staging": staging,
        "run_root": run_root,
        "result_path": result_path,
        "identity": identity,
        "capture": capture,
        "receipts": receipts,
        "provenance": provenance,
        "trace": trace,
        "trace_path": pathlib.Path(trace["trace_ref"]),
        "response_files": response_files,
    }


def _inspect(case: dict, **overrides) -> dict:
    arguments = {
        "expected_candidate_dir": case["candidate"],
        "expected_production_run_dir": case["run_root"],
        "expected_run_id": case["identity"]["run_id"],
        "expected_candidate_id": case["identity"]["candidate_id"],
        "expected_candidate_hash": case["identity"]["candidate_hash"],
        "expected_commit_sha": case["identity"]["commit_sha"],
    }
    arguments.update(overrides)
    return provider_causal_trace.inspect(case["trace_path"], **arguments)


def test_causal_trace_schema_hash_and_independent_inspector(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    document = json.loads(case["trace_path"].read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "provider_causal_trace_v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    resolver = jsonschema.RefResolver.from_schema(
        schema,
        store={
            "canonical_defs.schema.json": json.loads(
                (ROOT / "schemas" / "canonical_defs.schema.json").read_text(
                    encoding="utf-8"
                )
            )
        },
    )
    jsonschema.validate(document, schema, resolver=resolver)
    inspection = _inspect(case)
    assert inspection["status"] == "PASS", inspection
    assert (
        inspection["response_content_hash_recomputed"]
        == document["response_content_hash"]
    )
    assert inspection["patch_hunk_count"] == len(case["response_files"])
    assert (
        inspection["after_candidate_hash_recomputed"]
        == case["identity"]["candidate_hash"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        ("missing_body", "provider_response_content_invalid"),
        ("ids_only", "provider_response_content_invalid"),
        ("forged_hash", "provider_response_identity_or_content_hash"),
        ("modified_after_decision", "response_decision_binding"),
    ],
)
def test_response_to_decision_tampering_rejected(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_failure: str,
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    response_path = pathlib.Path(case["capture"]["response_ref"])
    response = json.loads(response_path.read_text(encoding="utf-8"))
    if mutation == "missing_body":
        response.pop("response_content", None)
    elif mutation == "ids_only":
        response["response_content"] = {}
    elif mutation == "forged_hash":
        response["response_content_hash"] = "sha256:" + "0" * 64
    else:
        response["response_content"]["files"][0]["content"] += "tampered"
        response["response_content_hash"] = provider_causal_trace.response_content_hash(
            response["response_content"]["files"]
        )
    _rehash(response_path, response)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert any(
        expected_failure in failure or "artifact_ref_hash:response" in failure
        for failure in result["failures"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        ("missing_decision", "artifact_path:implementation_decision.json"),
        ("forged_decision_hash", "artifact_self_hash:implementation_decision.json"),
        ("foreign_response", "response_decision_binding"),
        ("modified_after_patch", "decision_patch_binding"),
    ],
)
def test_decision_to_patch_tampering_rejected(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_failure: str,
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    decision_path = pathlib.Path(case["capture"]["decision_ref"])
    if mutation == "missing_decision":
        decision_path.unlink()
    else:
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        if mutation == "forged_decision_hash":
            decision["artifact_hash"] = "sha256:" + "0" * 64
            _write(decision_path, decision)
        elif mutation == "foreign_response":
            decision["response_content_hash"] = "sha256:" + "1" * 64
            _rehash(decision_path, decision)
        else:
            decision["decisions"][0]["implementation_result"] = "write:other.py"
            decision["decision_content_hash"] = canonical_evidence_hash.canonical_json_hash(
                {"decisions": decision["decisions"]}, ()
            )
            _rehash(decision_path, decision)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert any(
        expected_failure in failure
        or "artifact_ref_hash:decision" in failure
        for failure in result["failures"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_failure"),
    [
        ("missing_patch", "artifact_path:implementation_patch.json"),
        ("forged_patch_hash", "artifact_self_hash:implementation_patch.json"),
        ("decision_mismatch", "decision_patch_binding"),
        ("wrong_before", "decision_patch_binding"),
        ("wrong_after", "decision_patch_binding"),
        ("path_escape", "decision_patch_binding"),
        ("declared_apply_after_failure", "patch_application_binding"),
    ],
)
def test_patch_hunk_and_application_tampering_rejected(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_failure: str,
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    patch_path = pathlib.Path(case["capture"]["patch_ref"])
    application_path = pathlib.Path(case["capture"]["application_ref"])
    if mutation == "missing_patch":
        patch_path.unlink()
    elif mutation == "declared_apply_after_failure":
        application = json.loads(application_path.read_text(encoding="utf-8"))
        application["applied_hunks"][0]["after_hash"] = "sha256:" + "2" * 64
        _rehash(application_path, application)
    else:
        patch = json.loads(patch_path.read_text(encoding="utf-8"))
        hunk = patch["hunks"][0]
        if mutation == "forged_patch_hash":
            patch["artifact_hash"] = "sha256:" + "0" * 64
            _write(patch_path, patch)
        elif mutation == "decision_mismatch":
            hunk["decision_id"] = "sha256:" + "3" * 64
            _rehash(patch_path, patch)
        elif mutation == "wrong_before":
            hunk["before_content_b64"] = "d3JvbmctYmVmb3Jl"
            _rehash(patch_path, patch)
        elif mutation == "wrong_after":
            hunk["after_content"] = "wrong-after"
            _rehash(patch_path, patch)
        else:
            hunk["path"] = "../escape.py"
            _rehash(patch_path, patch)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert any(
        expected_failure in failure or "artifact_ref_hash:patch" in failure
        for failure in result["failures"]
    )


def test_patch_not_applied_or_applied_to_other_candidate_rejected(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    (case["candidate"] / "app.js").write_text("", encoding="utf-8")
    result = _inspect(case, expected_candidate_hash=None)
    assert result["status"] == "NEEDS_REWORK"
    assert "patch_candidate_binding" in result["failures"]
    other = case["allowed_root"] / "other"
    shutil.copytree(case["candidate"], other)
    result = _inspect(
        case,
        expected_candidate_dir=other,
        expected_candidate_hash=None,
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "candidate_root_invalid" in result["failures"]


def test_preexisting_result_and_posthoc_noop_trace_are_rejected(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    candidate = allowed / "candidate"
    staging = tmp_path / "staging"
    candidate.mkdir(parents=True)
    staging.mkdir()
    content = "print('already present')\n"
    (candidate / "app.py").write_text(content, encoding="utf-8")
    (staging / "app.py").write_text(content, encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    result_path = _write(
        run_root / "provider_generation_result.json",
        {
            "status": "PASS",
            "generated_files": ["app.py"],
            "provider_semantic_review": {"status": "pass"},
        },
    )
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        allowed.resolve(),
    )
    identity = {
        "run_id": "run",
        "candidate_id": "candidate",
        "commit_sha": "commit",
    }
    request_capture = _begin_request(
        candidate, run_root, identity, goal="posthoc"
    )
    with pytest.raises(ValueError, match="no-op"):
        provider_causal_trace.consume_provider_response(
            candidate_dir=candidate,
            provider_staging_dir=staging,
            production_run_dir=run_root,
            provider_result_path=result_path,
            identity=identity,
            provider_request_capture=request_capture,
            response_received_at=provider_causal_trace.now(),
        )


def test_provider_direct_final_candidate_write_cannot_obtain_trace(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    candidate = allowed / "candidate"
    candidate.mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    result_path = _write(
        run_root / "provider_generation_result.json",
        {
            "status": "PASS",
            "generated_files": ["app.py"],
            "provider_semantic_review": {"status": "pass"},
        },
    )
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        allowed.resolve(),
    )
    identity = {
        "run_id": "run",
        "candidate_id": "candidate",
        "commit_sha": "commit",
    }
    request_capture = _begin_request(
        candidate, run_root, identity, goal="direct write"
    )
    (candidate / "app.py").write_text("print('direct')\n", encoding="utf-8")
    (staging / "app.py").write_text("print('direct')\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside causal patch"):
        provider_causal_trace.consume_provider_response(
            candidate_dir=candidate,
            provider_staging_dir=staging,
            production_run_dir=run_root,
            provider_result_path=result_path,
            identity=identity,
            provider_request_capture=request_capture,
            response_received_at=provider_causal_trace.now(),
        )


def test_patch_path_escape_and_external_junction_are_rejected_before_apply(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    candidate = allowed / "candidate"
    candidate.mkdir(parents=True)
    staging = tmp_path / "staging"
    staging.mkdir()
    run_root = tmp_path / "run"
    run_root.mkdir()
    result_path = _write(
        run_root / "provider_generation_result.json",
        {
            "status": "PASS",
            "generated_files": ["../escape.py"],
            "provider_semantic_review": {"status": "pass"},
        },
    )
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        allowed.resolve(),
    )
    identity = {
        "run_id": "run",
        "candidate_id": "candidate",
        "commit_sha": "commit",
    }
    request_capture = _begin_request(
        candidate, run_root, identity, goal="unsafe paths"
    )
    with pytest.raises(ValueError, match="unsafe"):
        provider_causal_trace.consume_provider_response(
            candidate_dir=candidate,
            provider_staging_dir=staging,
            production_run_dir=run_root,
            provider_result_path=result_path,
            identity=identity,
            provider_request_capture=request_capture,
            response_received_at=provider_causal_trace.now(),
        )
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = candidate / "external"
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    (staging / "external").mkdir()
    (staging / "external" / "escape.py").write_text(
        "print('escape')\n", encoding="utf-8"
    )
    _write(
        result_path,
        {
            "status": "PASS",
            "generated_files": ["external/escape.py"],
            "provider_semantic_review": {"status": "pass"},
        },
    )
    with pytest.raises(ValueError, match="reparse point"):
        provider_causal_trace.consume_provider_response(
            candidate_dir=candidate,
            provider_staging_dir=staging,
            production_run_dir=run_root,
            provider_result_path=result_path,
            identity=identity,
            provider_request_capture=request_capture,
            response_received_at=provider_causal_trace.now(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "old-production-run"),
        ("candidate_id", "other-candidate"),
        ("candidate_hash", "sha256:" + "4" * 64),
    ],
)
def test_trace_and_provenance_identity_mismatch_rejected(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    trace = json.loads(case["trace_path"].read_text(encoding="utf-8"))
    trace[field] = value
    _rehash(case["trace_path"], trace)
    result = _inspect(case, **{f"expected_{field}": None})
    assert result["status"] == "NEEDS_REWORK"
    assert "production_provenance_binding" in result["failures"]


def test_generation_validation_post_build_cross_run_rejected(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    validation = case["receipts"]["provider_validation"]
    document = json.loads(validation.read_text(encoding="utf-8"))
    document["run_id"] = "other-run"
    _rehash(validation, document)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert "production_provenance_binding" in result["failures"]


@pytest.mark.parametrize(
    "forbidden_producer",
    [
        "scripts/formal_mainline_acceptance.py",
        "scripts/final_internal_acceptance.py",
        "tests/test_provider_fixture.py",
        "fixture/provider.py",
        "example/provider.py",
        "demo/provider.py",
        "benchmark/provider.py",
    ],
)
def test_acceptance_fixture_test_demo_example_benchmark_trace_rejected(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    forbidden_producer: str,
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    trace = json.loads(case["trace_path"].read_text(encoding="utf-8"))
    trace["producer"] = forbidden_producer
    _rehash(case["trace_path"], trace)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert "provider_causal_trace_contract" in result["failures"]


@pytest.mark.parametrize(
    "artifact_key",
    ["request_ref", "response_ref", "decision_ref", "patch_ref", "application_ref"],
)
def test_every_causal_artifact_tamper_invalidates_pass(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_key: str,
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    assert _inspect(case)["status"] == "PASS"
    path = pathlib.Path(case["capture"][artifact_key])
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert _inspect(case)["status"] == "NEEDS_REWORK"


def test_caller_boolean_and_adaptive_agent_cannot_override_inspector(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    response = pathlib.Path(case["capture"]["response_ref"])
    response.write_text(
        response.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    gate = formal_gate_registry.inspect_source(
        "provider_causal_trace",
        case["trace_path"],
        expected_identity=case["identity"],
        context={
            "causal_trace_verified": True,
            "provider_consumed": True,
            "patch_applied": True,
            "source_inspection": "PASS",
        },
    )
    assert gate["status"] == "NEEDS_REWORK"
    called: list[bool] = []
    delivery = codex_conversation.evaluate_public_delivery_gate(
        case["candidate"],
        {},
        {},
        production_provenance_ref=case["provenance"]["provenance_ref"],
        agent=lambda _messages: called.append(True) or {"delivery_allowed": True},
    )
    assert delivery["status"] == "NEEDS_REWORK"
    assert called == []


def test_acceptance_runner_never_produces_causal_trace(
    tmp_path: pathlib.Path,
) -> None:
    out = tmp_path / "acceptance"
    formal_mainline_acceptance.build_acceptance(out)
    assert not (out / provider_causal_trace.FILE_NAME).exists()


def test_candidate_local_trace_cannot_shadow_production_run_trace(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _valid_case(tmp_path, monkeypatch)
    _write(
        case["candidate"] / provider_causal_trace.FILE_NAME,
        {
            "kind": "CGKNProviderCausalTrace",
            "producer": "scripts/formal_mainline_acceptance.py",
            "status": "PASS",
        },
    )
    source = formal_mainline_acceptance._source_for_gate(
        "provider_causal_trace",
        candidate_dir=case["candidate"],
        production_run_dir=case["run_root"],
        full_all_result=None,
    )
    assert source is not None
    assert source.resolve() == case["trace_path"].resolve()
