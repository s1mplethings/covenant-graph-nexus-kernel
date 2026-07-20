from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import time
import uuid

import pytest

from scripts import browser_visual_evidence
from scripts import canonical_evidence_hash
from scripts import formal_gate_registry
from scripts import formal_mainline_acceptance
from scripts import production_candidate_provenance
from scripts import provider_causal_trace
from scripts import telegram_live_bridge


def _rehash(path: pathlib.Path, document: dict) -> None:
    document["artifact_hash"] = ""
    document["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(
        document, ("artifact_hash",)
    )
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _valid_provenance(tmp_path: pathlib.Path) -> dict:
    allowed_root = tmp_path / "allowed"
    candidate = allowed_root / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "index.html").write_text(
        "<main><h1>Production candidate</h1></main>", encoding="utf-8"
    )
    tests = candidate / "tests"
    tests.mkdir()
    (tests / "test_candidate.py").write_text(
        "def test_candidate():\n    assert True\n", encoding="utf-8"
    )
    run_root = tmp_path / "run"
    run_root.mkdir()
    provider_result = run_root / "provider_generation_result.json"
    provider_result.write_text(
        '{"status":"PASS","provider_semantic_review":{"status":"pass"}}\n',
        encoding="utf-8",
    )
    identity = {
        "run_id": "production-run-a",
        "candidate_id": "customer-candidate-a",
        "candidate_hash": canonical_evidence_hash.candidate_source_hash(candidate),
        "commit_sha": "0123456789abcdef0123456789abcdef01234567",
    }
    manifest = canonical_evidence_hash.candidate_source_manifest(candidate)
    manifest_hash = canonical_evidence_hash.canonical_json_hash(
        {"candidate_source_manifest": manifest}, ()
    )
    provider_ref = {
        "role": "provider_generation_result",
        "ref": str(provider_result.resolve()),
        "hash": canonical_evidence_hash.sha256_file(provider_result),
    }
    times = (
        ("2026-07-19T00:00:00+00:00", "2026-07-19T00:00:01+00:00"),
        ("2026-07-19T00:00:02+00:00", "2026-07-19T00:00:03+00:00"),
        ("2026-07-19T00:00:04+00:00", "2026-07-19T00:00:05+00:00"),
        ("2026-07-19T00:00:06+00:00", "2026-07-19T00:00:07+00:00"),
    )
    receipts: dict[str, pathlib.Path] = {}
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
    original_root = production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT
    production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = allowed_root.resolve()
    try:
        provenance = production_candidate_provenance.produce(
            candidate,
            run_root,
            run_id=identity["run_id"],
            candidate_id=identity["candidate_id"],
            commit_sha=identity["commit_sha"],
            stage_receipts=receipts,
            provider_result_ref=provider_result,
        )
    finally:
        production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = original_root
    return {
        "allowed_root": allowed_root,
        "candidate": candidate,
        "run_root": run_root,
        "provider_result": provider_result,
        "identity": identity,
        "receipts": receipts,
        "provenance": provenance,
        "path": pathlib.Path(provenance["provenance_ref"]),
    }


def test_candidate_source_hash_prunes_excluded_dependency_environment(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "app.py").write_bytes(b"print('candidate')\n")
    environment = candidate / ".cgkn_test_env"
    (environment / "Lib" / "site-packages").mkdir(parents=True)
    ignored = environment / "Lib" / "site-packages" / "large.py"
    ignored.write_bytes(b"x = 1\n")
    original_walk = canonical_evidence_hash.os.walk
    visited: list[pathlib.Path] = []

    def recording_walk(*args, **kwargs):
        for directory, dirnames, filenames in original_walk(*args, **kwargs):
            visited.append(pathlib.Path(directory).resolve())
            yield directory, dirnames, filenames

    monkeypatch.setattr(canonical_evidence_hash.os, "walk", recording_walk)
    first = canonical_evidence_hash.candidate_source_hash(candidate)
    ignored.write_bytes(b"x = 2\n")
    second = canonical_evidence_hash.candidate_source_hash(candidate)

    assert first == second
    assert environment.resolve() not in visited


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
    original_root = production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT
    production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = case[
        "allowed_root"
    ].resolve()
    try:
        return production_candidate_provenance.inspect(
            case["path"], **arguments
        )
    finally:
        production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = (
            original_root
        )


def test_provenance_schema_self_hash_and_independent_recalculation(
    tmp_path: pathlib.Path,
) -> None:
    case = _valid_provenance(tmp_path)
    inspection = _inspect(case)
    assert inspection["status"] == "PASS"
    assert (
        inspection["candidate_hash_recomputed"]
        == case["identity"]["candidate_hash"]
    )
    assert (
        inspection["candidate_source_manifest"]
        == canonical_evidence_hash.candidate_source_manifest(case["candidate"])
    )


def test_missing_provenance_rejected_even_when_canonical_evidence_exists(
    tmp_path: pathlib.Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    source = candidate / "test_execution.json"
    source.write_text(
        json.dumps(
            {
                "producer": "scripts/real_test_execution.py",
                "run_id": "run",
                "candidate_id": "candidate",
                "candidate_hash": "sha256:" + "1" * 64,
                "commit_sha": "commit",
            }
        ),
        encoding="utf-8",
    )
    result = formal_gate_registry.inspect_source(
        "test_execution",
        source,
        expected_identity={
            "run_id": "run",
            "candidate_id": "candidate",
            "candidate_hash": "sha256:" + "1" * 64,
            "commit_sha": "commit",
        },
        context={
            "production_provenance_verified": True,
            "source_inspection": "PASS",
        },
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "production_candidate_provenance_missing" in result["failures"]


def test_caller_production_provenance_verified_boolean_cannot_bypass(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "test_execution.json"
    source.write_text(
        '{"producer":"scripts/real_test_execution.py"}', encoding="utf-8"
    )
    result = formal_gate_registry.inspect_source(
        "test_execution",
        source,
        expected_identity={
            "run_id": "run",
            "candidate_id": "candidate",
            "candidate_hash": "sha256:" + "1" * 64,
            "commit_sha": "commit",
        },
        context={"production_provenance_verified": True},
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "production_candidate_provenance_missing" in result["failures"]


def test_caller_source_inspection_pass_cannot_bypass(
    tmp_path: pathlib.Path,
) -> None:
    source = tmp_path / "test_execution.json"
    source.write_text(
        '{"producer":"scripts/real_test_execution.py"}', encoding="utf-8"
    )
    result = formal_gate_registry.inspect_source(
        "test_execution",
        source,
        expected_identity={
            "run_id": "run",
            "candidate_id": "candidate",
            "candidate_hash": "sha256:" + "1" * 64,
            "commit_sha": "commit",
        },
        context={"source_inspection": "PASS"},
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "production_candidate_provenance_missing" in result["failures"]


def test_acceptance_runner_cannot_produce_canonical_provenance(
    tmp_path: pathlib.Path,
) -> None:
    out = tmp_path / "acceptance"
    formal_mainline_acceptance.build_acceptance(out)
    assert not (out / production_candidate_provenance.FILE_NAME).exists()
    inspection = json.loads(
        (out / "production_provenance_inspection.json").read_text(
            encoding="utf-8"
        )
    )
    assert inspection["producer"] == "scripts/formal_mainline_acceptance.py"
    assert inspection["kind"] == "CGKNProductionCandidateProvenanceInspection"
    assert inspection["status"] == "NOT_EVALUATED"


@pytest.mark.parametrize(
    "forbidden_producer",
    [
        "scripts/final_internal_acceptance.py",
        "tests/test_fixture.py",
        "fixture/provider.py",
        "example/provider.py",
        "demo/provider.py",
        "benchmark/provider.py",
    ],
)
def test_fixture_test_example_demo_benchmark_producer_rejected(
    tmp_path: pathlib.Path,
    forbidden_producer: str,
) -> None:
    case = _valid_provenance(tmp_path)
    document = json.loads(case["path"].read_text(encoding="utf-8"))
    document["producer"] = forbidden_producer
    _rehash(case["path"], document)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert "production_provenance_contract" in result["failures"]


def test_handwritten_provenance_with_correct_self_hash_rejected(
    tmp_path: pathlib.Path,
) -> None:
    candidate = tmp_path / "allowed" / "candidate"
    candidate.mkdir(parents=True)
    (candidate / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    document = {
        "kind": "CGKNProductionCandidateProvenance",
        "schema_version": "1.0",
        "run_id": "run",
        "candidate_id": "candidate",
        "candidate_hash": canonical_evidence_hash.candidate_source_hash(candidate),
        "commit_sha": "commit",
        "producer": "scripts/telegram_live_bridge.py",
        "created_at": "2026-07-20T00:00:00+00:00",
        "status": "PASS",
        "artifact_hash": "",
        "production_entrypoint": production_candidate_provenance.PRODUCTION_ENTRYPOINT,
        "generation_function": production_candidate_provenance.GENERATION_FUNCTION,
        "candidate_root": str(candidate.resolve()),
        "production_run_root": str(run_root.resolve()),
        "candidate_source_manifest": canonical_evidence_hash.candidate_source_manifest(
            candidate
        ),
        "candidate_source_manifest_hash": canonical_evidence_hash.canonical_json_hash(
            {
                "candidate_source_manifest": canonical_evidence_hash.candidate_source_manifest(
                    candidate
                )
            },
            (),
        ),
        "candidate_hash_method": "scripts.canonical_evidence_hash.candidate_source_hash",
        "stage_receipts": [],
        "artifact_refs": [],
    }
    path = run_root / production_candidate_provenance.FILE_NAME
    _rehash(path, document)
    original_root = production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT
    production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = (
        tmp_path / "allowed"
    ).resolve()
    try:
        result = production_candidate_provenance.inspect(path)
    finally:
        production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = (
            original_root
        )
    assert result["status"] == "NEEDS_REWORK"
    assert "stage_receipt_order" in result["failures"]


@pytest.mark.parametrize("mode", ["commit", "commit_digest"])
def test_repository_commit_hash_cannot_impersonate_candidate_hash(
    tmp_path: pathlib.Path, mode: str
) -> None:
    case = _valid_provenance(tmp_path)
    document = json.loads(case["path"].read_text(encoding="utf-8"))
    fake = case["identity"]["commit_sha"]
    if mode == "commit_digest":
        fake = "sha256:" + hashlib.sha256(fake.encode("utf-8")).hexdigest()
    document["candidate_hash"] = fake
    _rehash(case["path"], document)
    result = _inspect(case, expected_candidate_hash=None)
    assert result["status"] == "NEEDS_REWORK"
    expected = (
        "commit_hash_used_as_candidate_hash"
        if mode == "commit"
        else "commit_digest_used_as_candidate_hash"
    )
    assert expected in result["failures"]


def test_provenance_for_other_candidate_rejected(tmp_path: pathlib.Path) -> None:
    case = _valid_provenance(tmp_path)
    other = case["allowed_root"] / "other"
    other.mkdir()
    (other / "index.html").write_text("<h1>other</h1>", encoding="utf-8")
    result = _inspect(case, expected_candidate_dir=other)
    assert result["status"] == "NEEDS_REWORK"
    assert "candidate_path_invalid" in result["failures"]


def test_provenance_candidate_path_missing_rejected(tmp_path: pathlib.Path) -> None:
    case = _valid_provenance(tmp_path)
    shutil.rmtree(case["candidate"])
    result = _inspect(case, expected_candidate_hash=None)
    assert result["status"] == "NEEDS_REWORK"
    assert "candidate_path_invalid" in result["failures"]


def test_old_run_id_rejected(tmp_path: pathlib.Path) -> None:
    case = _valid_provenance(tmp_path)
    result = _inspect(case, expected_run_id="new-production-run")
    assert result["status"] == "NEEDS_REWORK"
    assert "provenance_identity_mismatch:run_id" in result["failures"]


def test_generation_validation_post_build_identity_mismatch_rejected(
    tmp_path: pathlib.Path,
) -> None:
    case = _valid_provenance(tmp_path)
    validation = case["receipts"]["provider_validation"]
    document = json.loads(validation.read_text(encoding="utf-8"))
    document["run_id"] = "other-run"
    _rehash(validation, document)
    provenance = json.loads(case["path"].read_text(encoding="utf-8"))
    for receipt in provenance["stage_receipts"]:
        if receipt["stage"] == "provider_validation":
            receipt["hash"] = canonical_evidence_hash.sha256_file(validation)
    _rehash(case["path"], provenance)
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert (
        "stage_identity_mismatch:provider_validation:run_id"
        in result["failures"]
    )


def test_candidate_modified_added_or_deleted_after_provenance_rejected(
    tmp_path: pathlib.Path,
) -> None:
    case = _valid_provenance(tmp_path)
    (case["candidate"] / "index.html").write_text("<h1>changed</h1>", encoding="utf-8")
    (case["candidate"] / "new.js").write_text("alert(1)", encoding="utf-8")
    (case["candidate"] / "tests" / "test_candidate.py").unlink()
    result = _inspect(case, expected_candidate_hash=None)
    assert result["status"] == "NEEDS_REWORK"
    assert "candidate_source_manifest_mismatch" in result["failures"]
    assert "candidate_hash_mismatch" in result["failures"]


def test_candidate_path_escape_rejected(tmp_path: pathlib.Path) -> None:
    case = _valid_provenance(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("<h1>outside</h1>", encoding="utf-8")
    document = json.loads(case["path"].read_text(encoding="utf-8"))
    document["candidate_root"] = str(outside.resolve())
    _rehash(case["path"], document)
    result = _inspect(case, expected_candidate_dir=None)
    assert result["status"] == "NEEDS_REWORK"
    assert "candidate_path_invalid" in result["failures"]


def test_external_junction_rejected(tmp_path: pathlib.Path) -> None:
    case = _valid_provenance(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    link = case["candidate"] / "external"
    proc = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert "candidate_symlink" in result["failures"]


def test_referenced_artifact_tamper_invalidates_prior_pass(
    tmp_path: pathlib.Path,
) -> None:
    case = _valid_provenance(tmp_path)
    assert _inspect(case)["status"] == "PASS"
    case["provider_result"].write_text('{"status":"tampered"}', encoding="utf-8")
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert "provider_generation_artifact_invalid" in result["failures"]


def test_provenance_artifact_tamper_invalidates_prior_pass(
    tmp_path: pathlib.Path,
) -> None:
    case = _valid_provenance(tmp_path)
    document = json.loads(case["path"].read_text(encoding="utf-8"))
    document["candidate_id"] = "tampered-without-rehash"
    case["path"].write_text(json.dumps(document), encoding="utf-8")
    result = _inspect(case)
    assert result["status"] == "NEEDS_REWORK"
    assert "production_provenance_artifact_hash" in result["failures"]


@pytest.mark.parametrize(
    ("gate", "artifact", "producer"),
    [
        (
            "test_execution",
            "test_execution.json",
            "scripts/real_test_execution.py",
        ),
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
    ],
)
def test_canonical_evidence_from_old_candidate_rejected(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    gate: str,
    artifact: str,
    producer: str,
) -> None:
    case = _valid_provenance(tmp_path)
    monkeypatch.setattr(
        production_candidate_provenance,
        "PRODUCTION_CANDIDATE_ROOT",
        case["allowed_root"].resolve(),
    )
    source = case["candidate"] / artifact
    document = {
        "kind": "OldCandidateEvidence",
        "schema_version": "1.0",
        **case["identity"],
        "run_id": "old-production-run",
        "producer": producer,
        "created_at": "2026-07-19T00:00:00+00:00",
        "status": "PASS",
        "artifact_hash": "",
        "production_provenance_ref": case["provenance"]["provenance_ref"],
        "production_provenance_hash": case["provenance"]["provenance_hash"],
    }
    _rehash(source, document)
    result = formal_gate_registry.inspect_source(
        gate,
        source,
        expected_identity=case["identity"],
        context={
            "production_provenance_ref": case["provenance"][
                "provenance_ref"
            ]
        },
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "run_id_mismatch" in result["failures"]


def test_adaptive_agent_cannot_override_provenance_failure(
    tmp_path: pathlib.Path,
) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    called: list[bool] = []
    result = telegram_live_bridge.evaluate_public_delivery_gate(
        candidate,
        {},
        {},
        agent=lambda _messages: called.append(True) or {"delivery_allowed": True},
    )
    assert result["status"] == "NEEDS_REWORK"
    assert called == []
    assert "production_candidate_provenance" in result[
        "canonical_evidence_gate"
    ]["failures"]


class _NoTelegramTransport:
    def __init__(self) -> None:
        self.messages_sent = 0
        self.photos_sent = 0
        self.documents_sent = 0

    def send_chat_action(self, *_args, **_kwargs) -> None:
        return None

    def send_message(self, *_args, **_kwargs) -> bool:
        self.messages_sent += 1
        return True

    def send_photo(self, *_args, **_kwargs) -> bool:
        self.photos_sent += 1
        return True

    def send_document(self, *_args, **_kwargs) -> bool:
        self.documents_sent += 1
        return True


class _InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self) -> None:
        self.target(*self.args, **self.kwargs)


def test_formal_production_entry_generates_provenance_and_bound_evidence(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_id = f"provenance-positive-{uuid.uuid4().hex}"
    session_dir = tmp_path / "sessions"
    log_dir = tmp_path / "logs"
    session = telegram_live_bridge.default_session(chat_id)
    session["whiteboard"]["project_summary"] = (
        "生成一个真实可运行的静态网页工具，包含 pytest，并执行真实浏览器截图。"
    )
    session["whiteboard"]["requires_user_evidence_review"] = True
    session["messages"] = [
        {
            "role": "user",
            "text": session["whiteboard"]["project_summary"],
        }
    ]
    session["generation"] = {"status": "idle"}
    monkeypatch.setattr(
        telegram_live_bridge, "DEFAULT_MEMORY_DIR", tmp_path / "project_memory"
    )
    monkeypatch.setenv(
        "CGNK_LOCAL_STUDIO_CONVERSATION_ROOT",
        str(tmp_path / "conversations"),
    )
    telegram_live_bridge.save_session(session_dir, session)

    provider_out_dirs: list[pathlib.Path] = []

    def reproducible_provider(args):
        project = pathlib.Path(args.out_dir)
        provider_out_dirs.append(project.resolve())
        assert (
            pathlib.Path(args.run_dir)
            / provider_causal_trace.CAUSAL_DIR_NAME
            / provider_causal_trace.REQUEST_FILE
        ).is_file()
        project.mkdir(parents=True, exist_ok=True)
        (project / "README.md").write_text(
            "# Production candidate\n\nOpen index.html.\n", encoding="utf-8"
        )
        (project / "TEST_PLAN.md").write_text(
            "# Test plan\n\nRun pytest.\n", encoding="utf-8"
        )
        (project / "index.html").write_text(
            "<main><h1>Production provenance</h1>"
            "<button id='run'>Run</button></main>",
            encoding="utf-8",
        )
        tests = project / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_candidate.py").write_text(
            "def test_candidate():\n    assert True\n", encoding="utf-8"
        )
        return {
            "status": "PASS",
            "generated_files": [
                "README.md",
                "TEST_PLAN.md",
                "index.html",
                "tests/test_candidate.py",
            ],
            "provider_semantic_review": {"status": "pass"},
            "artifact_refs": {},
            "agent_usage": {
                "status": "pass",
                "events": [{"command": "python -m pytest tests"}],
            },
            "example_outputs": {},
        }

    monkeypatch.setattr(
        telegram_live_bridge.provider_project_pipeline,
        "execute",
        reproducible_provider,
    )
    client = _NoTelegramTransport()
    project_parent = (
        telegram_live_bridge.ROOT
        / "generated"
        / "telegram_provider_projects"
        / telegram_live_bridge.safe_id(chat_id)
    )
    try:
        started = telegram_live_bridge.start_generation_from_income(
            client,
            chat_id,
            session_dir,
            log_dir,
            "gpt-test",
            180,
            session,
            reason="formal_production_positive",
        )
        assert started is True
        deadline = time.monotonic() + 180
        final_session = telegram_live_bridge.load_session(session_dir, chat_id)
        while (
            str(final_session.get("generation", {}).get("status", "")).lower()
            in {"queued", "running"}
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
            final_session = telegram_live_bridge.load_session(
                session_dir, chat_id
            )
        assert str(
            final_session.get("generation", {}).get("status", "")
        ).lower() not in {"queued", "running"}
        generation = final_session["generation"]
        candidate = pathlib.Path(generation["project_dir"])
        run_root = pathlib.Path(generation["provider_run_dir"])
        provenance_ref = run_root / production_candidate_provenance.FILE_NAME
        inspection = production_candidate_provenance.inspect(
            provenance_ref,
            expected_candidate_dir=candidate,
            expected_production_run_dir=run_root,
            expected_run_id=generation["run_id"],
            expected_candidate_id=generation["candidate_id"],
            expected_commit_sha=generation["commit_sha"],
        )
        assert inspection["status"] == "PASS", inspection
        identity = inspection["identity"]
        assert provider_out_dirs == [
            (
                telegram_live_bridge.ROOT
                / "generated"
                / "provider_response_staging"
                / generation["run_id"]
            ).resolve()
        ]
        assert provider_out_dirs[0] != candidate.resolve()
        causal_ref = run_root / provider_causal_trace.FILE_NAME
        causal_inspection = provider_causal_trace.inspect(
            causal_ref,
            expected_candidate_dir=candidate,
            expected_production_run_dir=run_root,
            expected_run_id=generation["run_id"],
            expected_candidate_id=generation["candidate_id"],
            expected_candidate_hash=identity["candidate_hash"],
            expected_commit_sha=generation["commit_sha"],
        )
        assert causal_inspection["status"] == "PASS", causal_inspection
        assert causal_inspection["identity"] == identity
        assert causal_inspection["patch_hunk_count"] == 4
        assert causal_inspection["response_content_hash_recomputed"].startswith(
            "sha256:"
        )
        assert causal_inspection[
            "patch_after_candidate_hash_recomputed"
        ].startswith("sha256:")
        assert (
            causal_inspection["after_candidate_hash_recomputed"]
            == identity["candidate_hash"]
        )
        test_doc = json.loads(
            (candidate / "test_execution.json").read_text(encoding="utf-8")
        )
        runtime_doc = json.loads(
            (candidate / "customer_runtime.json").read_text(encoding="utf-8")
        )
        visual_doc = json.loads(
            (candidate / "visual_evidence.json").read_text(encoding="utf-8")
        )
        for evidence in (test_doc, runtime_doc, visual_doc):
            assert {
                field: evidence[field]
                for field in (
                    "run_id",
                    "candidate_id",
                    "candidate_hash",
                    "commit_sha",
                )
            } == identity
            assert evidence["production_provenance_ref"] == str(
                provenance_ref.resolve()
            )
            assert evidence["production_provenance_hash"] == inspection[
                "provenance_hash"
            ]
        assert test_doc["status"] == "PASS"
        assert runtime_doc["status"] == "PASS"
        assert runtime_doc["shutdown_result"]["stopped"] is True
        assert runtime_doc["cleanup_result"]["removed"] is True
        assert visual_doc["status"] == "PASS"
        assert visual_doc["runtime_pid"] == runtime_doc["pid"]
        assert visual_doc["runtime_url"] == runtime_doc["url"]
        acceptance = formal_mainline_acceptance.build_acceptance(
            tmp_path / "formal-acceptance",
            candidate_dir=candidate,
            production_run_dir=run_root,
        )
        assert acceptance["status"] == "NEEDS_REWORK"
        assert {
            gate: acceptance["gates"][gate]["status"]
            for gate in (
                "provider_causal_trace",
                "test_execution",
                "customer_runtime",
                "visual_evidence",
            )
        } == {
            "provider_causal_trace": "PASS",
            "test_execution": "PASS",
            "customer_runtime": "PASS",
            "visual_evidence": "PASS",
        }
        assert client.photos_sent == 0
        assert client.documents_sent == 0
    finally:
        shutil.rmtree(project_parent, ignore_errors=True)
