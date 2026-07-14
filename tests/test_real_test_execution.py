from __future__ import annotations

import pathlib
import sys
import json

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import real_test_execution
from scripts import canonical_evidence_hash


def test_model_written_summary_without_execution_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "TEST_REPORT.md").write_text("# Test Report\n\nlooks good\n", encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "test_execution.json" in result["missing"]


def test_real_pytest_execution_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def add(a,b): return a+b\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")
    result = real_test_execution.run_tests(tmp_path, run_id="run-a", candidate_id="candidate-a", commit_sha="commit-a")
    assert result["kind"] == "CGKNTestExecutionEvidence"
    assert result["schema_version"] == "1.0"
    assert result["status"] == "PASS"
    assert result["argv"]
    assert result["stdout_hash"].startswith("sha256:")
    assert result["stderr_hash"].startswith("sha256:")
    assert result["result_artifact_hash"].startswith("sha256:")
    report = (tmp_path / "TEST_REPORT.md").read_text(encoding="utf-8")
    assert "run_id: run-a" in report
    assert f"candidate_hash: {result['candidate_hash']}" in report
    assert "commit_sha: commit-a" in report
    assert real_test_execution.inspect_test_report(tmp_path, run_id="run-a", candidate_hash=result["candidate_hash"], commit_sha="commit-a")["verdict"] == "PASS"


def test_candidate_source_hash_excludes_evidence_outputs_not_product_assets(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "generated").mkdir()
    asset = tmp_path / "generated" / "background_scene.png"
    asset.write_bytes(b"product-asset")
    before = canonical_evidence_hash.candidate_source_hash(tmp_path)
    for name in ("test_execution.json", "TEST_REPORT.md", "test_stdout.txt", "test_stderr.txt", "customer_runtime.json", "visual_evidence.json"):
        (tmp_path / name).write_text("changed evidence output\n", encoding="utf-8")
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "browser_visual_evidence.png").write_bytes(b"screenshot output")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) == before
    asset.write_bytes(b"changed-product-asset")
    assert canonical_evidence_hash.candidate_source_hash(tmp_path) != before


def test_no_real_execution_marker_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "TEST_REPORT.md").write_text("commands_run:\n- NO REAL TEST EXECUTION\nexit_code: none\nNO REAL TEST EXECUTION\n", encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"


def test_hash_tampering_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["stdout_hash"] = "sha256:bad"
    (tmp_path / "test_execution.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "stdout_hash_mismatch" in result["missing"]


def test_test_execution_status_tamper_without_hash_update_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["status"] = "FAIL"
    (tmp_path / "test_execution.json").write_text(json.dumps(doc), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]


def test_test_execution_self_equal_fake_hashes_do_not_pass(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["artifact_hash"] = "sha256:" + "0" * 64
    doc["result_artifact_hash"] = "sha256:" + "0" * 64
    (tmp_path / "test_execution.json").write_text(json.dumps(doc), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]
    assert "result_artifact_hash" in result["missing"]


def test_stdout_and_stderr_file_tampering_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    (tmp_path / "test_stdout.txt").write_text("tampered stdout\n", encoding="utf-8")
    stdout_result = real_test_execution.inspect_test_report(tmp_path)
    assert stdout_result["verdict"] == "FAIL"
    assert "stdout_hash_mismatch" in stdout_result["missing"]
    real_test_execution.run_tests(tmp_path)
    (tmp_path / "test_stderr.txt").write_text("tampered stderr\n", encoding="utf-8")
    stderr_result = real_test_execution.inspect_test_report(tmp_path)
    assert stderr_result["verdict"] == "FAIL"
    assert "stderr_hash_mismatch" in stderr_result["missing"]


def test_test_candidate_hash_tamper_with_fake_artifact_hashes_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path)
    doc = json.loads((tmp_path / "test_execution.json").read_text(encoding="utf-8"))
    doc["candidate_hash"] = "sha256:" + "1" * 64
    doc["artifact_hash"] = "sha256:" + "2" * 64
    doc["result_artifact_hash"] = "sha256:" + "2" * 64
    (tmp_path / "test_execution.json").write_text(json.dumps(doc), encoding="utf-8")
    result = real_test_execution.inspect_test_report(tmp_path)
    assert result["verdict"] == "FAIL"
    assert "candidate_hash_current" in result["missing"]


def test_candidate_hash_mismatch_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "app.py").write_text("def ok(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import ok\n\ndef test_ok():\n    assert ok()\n", encoding="utf-8")
    real_test_execution.run_tests(tmp_path, candidate_hash="sha256:actual")
    result = real_test_execution.inspect_test_report(tmp_path, candidate_hash="sha256:other")
    assert result["verdict"] == "FAIL"
    assert "candidate_hash" in result["missing"]
