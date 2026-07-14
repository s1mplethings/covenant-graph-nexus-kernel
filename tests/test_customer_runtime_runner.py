from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import customer_runtime_runner
from scripts import canonical_evidence_hash


def test_static_project_runtime_passes_and_shuts_down(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<h1>Hello runtime</h1>\n", encoding="utf-8")
    candidate_hash = canonical_evidence_hash.candidate_source_hash(tmp_path)
    evidence = customer_runtime_runner.run(tmp_path, run_id="runtime-a", candidate_hash=candidate_hash, commit_sha="commit-a")
    assert evidence["kind"] == "CGKNCustomerRuntimeEvidence"
    assert evidence["status"] == "PASS"
    assert evidence["pid"] > 0
    assert evidence["health_probe"]["status_code"] == 200
    assert evidence["shutdown_result"]["stopped"]
    result = customer_runtime_runner.inspect(tmp_path, candidate_hash=candidate_hash, commit_sha="commit-a")
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
