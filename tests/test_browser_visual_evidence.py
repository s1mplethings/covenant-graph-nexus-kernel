from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import browser_visual_evidence, customer_runtime_runner


def test_real_browser_visual_evidence_passes(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main><h1>Browser Evidence</h1><button>Run</button></main>", encoding="utf-8")
    runtime = customer_runtime_runner.run(tmp_path)
    evidence = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    if evidence["status"] != "PASS" and "Executable doesn't exist" in evidence.get("error", ""):
        pytest.skip("Playwright browser binaries are not installed")
    assert evidence["status"] == "PASS", evidence
    assert pathlib.Path(evidence["screenshot_path"]).exists()
    assert evidence["dom_assertions"]
    assert browser_visual_evidence.inspect(tmp_path)["status"] == "PASS"


def test_screenshot_without_visual_evidence_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "screenshots").mkdir()
    (tmp_path / "screenshots" / "app_home.png").write_bytes(b"not-real")
    assert browser_visual_evidence.inspect(tmp_path)["status"] == "FAIL"


def test_screenshot_hash_tamper_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main><h1>Browser Evidence</h1></main>", encoding="utf-8")
    runtime = customer_runtime_runner.run(tmp_path)
    evidence = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    if evidence["status"] != "PASS" and "Executable doesn't exist" in evidence.get("error", ""):
        pytest.skip("Playwright browser binaries are not installed")
    doc = json.loads((tmp_path / "visual_evidence.json").read_text(encoding="utf-8"))
    doc["screenshot_hash"] = "sha256:bad"
    (tmp_path / "visual_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "screenshot_hash" in result["missing"]


def test_visual_json_dom_action_status_tamper_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main><h1>Browser Evidence</h1></main>", encoding="utf-8")
    runtime = customer_runtime_runner.run(tmp_path)
    evidence = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    if evidence["status"] != "PASS" and "Executable doesn't exist" in evidence.get("error", ""):
        pytest.skip("Playwright browser binaries are not installed")
    doc = json.loads((tmp_path / "visual_evidence.json").read_text(encoding="utf-8"))
    doc["dom_assertions"] = []
    doc["actions"] = [{"type": "goto", "url": "http://127.0.0.1:1/"}]
    doc["status"] = "PASS"
    (tmp_path / "visual_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "dom_assertions" in result["missing"]
    assert "artifact_hash_mismatch" in result["missing"]


def test_visual_screenshot_file_tamper_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main><h1>Browser Evidence</h1></main>", encoding="utf-8")
    runtime = customer_runtime_runner.run(tmp_path)
    evidence = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    if evidence["status"] != "PASS" and "Executable doesn't exist" in evidence.get("error", ""):
        pytest.skip("Playwright browser binaries are not installed")
    pathlib.Path(evidence["screenshot_path"]).write_bytes(b"tampered screenshot")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "screenshot_hash" in result["missing"]


def test_visual_runtime_reference_tamper_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main><h1>Browser Evidence</h1></main>", encoding="utf-8")
    runtime = customer_runtime_runner.run(tmp_path)
    evidence = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    if evidence["status"] != "PASS" and "Executable doesn't exist" in evidence.get("error", ""):
        pytest.skip("Playwright browser binaries are not installed")
    runtime_doc = json.loads((tmp_path / "customer_runtime.json").read_text(encoding="utf-8"))
    runtime_doc["observed_result"] = "tampered runtime"
    (tmp_path / "customer_runtime.json").write_text(json.dumps(runtime_doc), encoding="utf-8")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "customer_runtime_hash" in result["missing"]
    assert "customer_runtime_ref_inspect" in result["missing"]


def test_visual_fake_artifact_hash_fails(tmp_path: pathlib.Path) -> None:
    (tmp_path / "index.html").write_text("<main><h1>Browser Evidence</h1></main>", encoding="utf-8")
    runtime = customer_runtime_runner.run(tmp_path)
    evidence = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    if evidence["status"] != "PASS" and "Executable doesn't exist" in evidence.get("error", ""):
        pytest.skip("Playwright browser binaries are not installed")
    doc = json.loads((tmp_path / "visual_evidence.json").read_text(encoding="utf-8"))
    doc["artifact_hash"] = "sha256:" + "4" * 64
    (tmp_path / "visual_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]
