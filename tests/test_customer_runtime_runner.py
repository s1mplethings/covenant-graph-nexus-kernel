from __future__ import annotations

import json
import os
import pathlib
import tempfile
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import customer_runtime_runner
from scripts import canonical_evidence_hash


def _rewrite_runtime_doc(project: pathlib.Path, updates: dict) -> dict:
    doc = json.loads((project / "customer_runtime.json").read_text(encoding="utf-8"))
    doc.update(updates)
    doc["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",))
    (project / "customer_runtime.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def test_static_project_runtime_passes_from_isolated_copy_and_shuts_down(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_cwd: list[pathlib.Path] = []
    real_popen = customer_runtime_runner.subprocess.Popen

    def recording_popen(*args, **kwargs):
        captured_cwd.append(pathlib.Path(kwargs["cwd"]).resolve())
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(customer_runtime_runner.subprocess, "Popen", recording_popen)
    (tmp_path / "index.html").write_text("<h1>Hello isolated runtime</h1>\n", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "product.txt").write_text("asset copied\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    candidate_hash = canonical_evidence_hash.candidate_source_hash(tmp_path)
    evidence = customer_runtime_runner.run(tmp_path, run_id="runtime-a", candidate_hash=candidate_hash, commit_sha="commit-a")
    execution_root = pathlib.Path(evidence["execution_root"])
    assert evidence["kind"] == "CGKNCustomerRuntimeEvidence"
    assert evidence["status"] == "PASS"
    assert evidence["pid"] > 0
    assert evidence["health_probe"]["status_code"] == 200
    assert evidence["execution_root_isolated"] is True
    assert pathlib.Path(evidence["cwd"]).resolve() == execution_root.resolve()
    assert pathlib.Path(evidence["cwd"]).resolve() != tmp_path.resolve()
    assert captured_cwd == [execution_root.resolve()]
    assert evidence["source_candidate_hash"] == candidate_hash
    assert evidence["copied_candidate_hash"] == candidate_hash
    assert evidence["candidate_hash"] == candidate_hash
    assert evidence["copied_file_count"] > 0
    assert "Hello isolated runtime" in evidence["observed_result"]
    assert evidence["shutdown_result"]["stopped"]
    assert evidence["cleanup_result"]["removed"] is True
    assert not execution_root.exists()
    result = customer_runtime_runner.inspect(tmp_path, candidate_hash=candidate_hash, commit_sha="commit-a")
    assert result["status"] == "PASS"


def test_long_runtime_body_hashes_the_stored_truncated_observation(
    tmp_path: pathlib.Path,
) -> None:
    body = "<main>" + ("runtime evidence " * 500) + "</main>\n"
    (tmp_path / "index.html").write_text(body, encoding="utf-8")

    evidence = customer_runtime_runner.run(tmp_path)
    result = customer_runtime_runner.inspect(tmp_path)

    assert evidence["status"] == "PASS"
    assert len(evidence["observed_result"]) == 4000
    assert evidence["observed_result_hash"] == canonical_evidence_hash.sha256_bytes(
        evidence["observed_result"].encode("utf-8")
    )
    assert result["status"] == "PASS"


def test_handwritten_four_field_pass_runtime_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "customer_runtime.json").write_text('{"status":"PASS","pid":1,"health_probe":{"status_code":200},"observed_result":"ok"}', encoding="utf-8")
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "kind" in result["missing"]


def test_observed_hash_tampering_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    doc = json.loads((tmp_path / "customer_runtime.json").read_text(encoding="utf-8"))
    doc["observed_result_hash"] = "sha256:bad"
    (tmp_path / "customer_runtime.json").write_text(json.dumps(doc), encoding="utf-8")
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "observed_result_hash" in result["missing"]


def test_runtime_observed_result_tampering_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    doc = json.loads((tmp_path / "customer_runtime.json").read_text(encoding="utf-8"))
    doc["observed_result"] = "tampered body"
    (tmp_path / "customer_runtime.json").write_text(json.dumps(doc), encoding="utf-8")
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "observed_result_hash" in result["missing"]
    assert "artifact_hash_mismatch" in result["missing"]


def test_runtime_status_pid_health_tamper_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    doc = json.loads((tmp_path / "customer_runtime.json").read_text(encoding="utf-8"))
    doc["status"] = "PASS"
    doc["pid"] = 0
    doc["health_probe"]["status_code"] = 0
    (tmp_path / "customer_runtime.json").write_text(json.dumps(doc), encoding="utf-8")
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "pid" in result["missing"]
    assert "health_probe" in result["missing"]
    assert "artifact_hash_mismatch" in result["missing"]


def test_runtime_fake_artifact_hash_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    doc = json.loads((tmp_path / "customer_runtime.json").read_text(encoding="utf-8"))
    doc["artifact_hash"] = "sha256:" + "3" * 64
    (tmp_path / "customer_runtime.json").write_text(json.dumps(doc), encoding="utf-8")
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]


def test_runtime_evidence_with_source_as_execution_root_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    _rewrite_runtime_doc(
        tmp_path,
        {
            "execution_root": str(tmp_path.resolve()),
            "clean_environment_root": str(tmp_path.resolve()),
            "cwd": str(tmp_path.resolve()),
        },
    )
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "execution_root" in result["missing"]


def test_runtime_evidence_with_source_cwd_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    _rewrite_runtime_doc(tmp_path, {"cwd": str(tmp_path.resolve())})
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "cwd" in result["missing"]


def test_runtime_evidence_without_isolation_flag_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    _rewrite_runtime_doc(tmp_path, {"execution_root_isolated": False})
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "execution_root_isolated" in result["missing"]


def test_runtime_copy_hash_mismatch_fails_run_and_inspect(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    real_copy = customer_runtime_runner._copy_candidate_source

    def mismatched_copy(source_project, execution_root, source_manifest):
        result = real_copy(source_project, execution_root, source_manifest)
        result["copied_candidate_hash"] = "sha256:" + "9" * 64
        return result

    monkeypatch.setattr(customer_runtime_runner, "_copy_candidate_source", mismatched_copy)
    evidence = customer_runtime_runner.run(tmp_path)
    result = customer_runtime_runner.inspect(tmp_path)
    assert evidence["status"] == "FAIL"
    assert result["status"] == "FAIL"
    assert "copied_candidate_hash" in result["missing"]


def test_runtime_evidence_with_zero_copied_files_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    _rewrite_runtime_doc(tmp_path, {"copied_file_count": 0})
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "copied_file_count" in result["missing"]


def test_runtime_evidence_without_cleanup_removed_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    _rewrite_runtime_doc(tmp_path, {"cleanup_result": {"removed": False}})
    result = customer_runtime_runner.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "cleanup_result" in result["missing"]


def test_runtime_evidence_claims_cleanup_but_execution_root_exists_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    customer_runtime_runner.run(tmp_path)
    leaked_root = pathlib.Path(tempfile.mkdtemp(prefix="cgkn_leaked_runtime_")).resolve()
    try:
        _rewrite_runtime_doc(
            tmp_path,
            {
                "execution_root": str(leaked_root),
                "clean_environment_root": str(leaked_root),
                "cwd": str(leaked_root),
                "cleanup_result": {"removed": True},
            },
        )
        result = customer_runtime_runner.inspect(tmp_path)
        assert result["status"] == "FAIL"
        assert "execution_root_cleanup" in result["missing"]
    finally:
        leaked_root.rmdir()


def test_runtime_external_symlink_fails_without_copying_project_outside(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    linked = tmp_path / "linked-secret.txt"
    try:
        os.symlink(outside, linked)
    except OSError:
        monkeypatch.setattr(
            customer_runtime_runner,
            "_external_symlink_failures",
            lambda _project: [f"linked-secret.txt -> {outside}"],
        )
    evidence = customer_runtime_runner.run(tmp_path)
    result = customer_runtime_runner.inspect(tmp_path)
    assert evidence["status"] == "FAIL"
    assert "external_symlink:" in evidence["observed_result"]
    assert result["status"] == "FAIL"


def test_runtime_missing_index_in_isolated_copy_fails_without_source_fallback(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    real_copy = customer_runtime_runner._copy_candidate_source

    def copy_without_index(source_project, execution_root, source_manifest):
        result = real_copy(source_project, execution_root, source_manifest)
        (execution_root / "index.html").unlink()
        result["copied_file_count"] -= 1
        result["copied_candidate_hash"] = canonical_evidence_hash.candidate_source_hash(execution_root)
        result["copied_manifest_hash"] = "sha256:" + "8" * 64
        return result

    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("runtime must not fall back to the source project")

    monkeypatch.setattr(customer_runtime_runner, "_copy_candidate_source", copy_without_index)
    monkeypatch.setattr(customer_runtime_runner.subprocess, "Popen", fail_if_started)
    evidence = customer_runtime_runner.run(tmp_path)
    result = customer_runtime_runner.inspect(tmp_path)
    assert evidence["status"] == "FAIL"
    assert evidence["startup_argv"] == []
    assert pathlib.Path(evidence["cwd"]).resolve() != tmp_path.resolve()
    assert result["status"] == "FAIL"
