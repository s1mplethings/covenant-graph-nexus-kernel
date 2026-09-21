from __future__ import annotations

import builtins
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import browser_visual_evidence, canonical_evidence_hash, customer_runtime_runner


def _make_static_project(project: pathlib.Path) -> None:
    (project / "index.html").write_text("<main><h1>Browser Evidence</h1><button>Run</button></main>", encoding="utf-8")
    (project / "assets").mkdir()
    (project / "assets" / "product.txt").write_text("asset\n", encoding="utf-8")
    (project / "tests").mkdir()
    (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _run_with_visual(project: pathlib.Path, *, monkeypatch=None) -> tuple[dict, dict, list[dict]]:
    popen_calls: list[dict] = []
    if monkeypatch is not None:
        real_start_process = customer_runtime_runner._start_process

        def recording_start_process(argv, cwd):
            proc = real_start_process(argv, cwd)
            popen_calls.append({"pid": proc.pid, "cwd": pathlib.Path(cwd).resolve(), "argv": list(argv)})
            return proc

        monkeypatch.setattr(customer_runtime_runner, "_start_process", recording_start_process)
    candidate_hash = canonical_evidence_hash.candidate_source_hash(project)
    runtime = customer_runtime_runner.run(
        project,
        run_id="run-browser",
        candidate_hash=candidate_hash,
        commit_sha="commit-browser",
        live_consumer=browser_visual_evidence.capture_live_runtime,
        browser_capture_required=True,
    )
    visual = browser_visual_evidence.finalize_evidence(
        project,
        runtime_result=runtime,
        capture_receipt=runtime["browser_capture_receipt"],
        required=True,
    )
    return runtime, visual, popen_calls


def _rewrite_visual(project: pathlib.Path, updates: dict) -> dict:
    doc = json.loads((project / "visual_evidence.json").read_text(encoding="utf-8"))
    doc.update(updates)
    doc["artifact_hash"] = canonical_evidence_hash.canonical_json_hash(doc, ("artifact_hash",))
    (project / "visual_evidence.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def test_real_browser_visual_evidence_uses_same_live_runtime(tmp_path: pathlib.Path, monkeypatch) -> None:
    _make_static_project(tmp_path)
    runtime, visual, popen_calls = _run_with_visual(tmp_path, monkeypatch=monkeypatch)
    execution_root = pathlib.Path(runtime["execution_root"])

    assert runtime["status"] == "PASS", runtime
    assert visual["status"] == "PASS", visual
    assert len(popen_calls) == 1
    assert popen_calls[0]["pid"] == runtime["pid"]
    assert popen_calls[0]["cwd"] == execution_root.resolve()
    assert runtime["pid"] == visual["runtime_pid"]
    assert runtime["url"] == visual["runtime_url"]
    assert runtime["port"] == visual["runtime_port"]
    assert runtime["execution_root"] == visual["runtime_execution_root"]
    assert runtime["browser_capture_id"] == visual["browser_capture_id"]
    assert runtime["browser_capture_hash"] == visual["browser_capture_hash"]
    assert visual["runtime_alive_before_capture"] is True
    assert visual["runtime_alive_after_capture"] is True
    assert pathlib.Path(visual["screenshot_path"]).exists()
    assert visual["network_origin"] == browser_visual_evidence._origin(runtime["url"])
    assert runtime["shutdown_result"]["stopped"] is True
    assert runtime["cleanup_result"]["removed"] is True
    assert not execution_root.exists()
    assert customer_runtime_runner.inspect(tmp_path)["status"] == "PASS"
    assert browser_visual_evidence.inspect(tmp_path)["status"] == "PASS"


def test_runtime_stopped_capture_fails_without_starting_second_server(tmp_path: pathlib.Path, monkeypatch) -> None:
    _make_static_project(tmp_path)
    popen_count = {"count": 0}
    real_start_process = customer_runtime_runner._start_process

    def counting_start_process(argv, cwd):
        popen_count["count"] += 1
        return real_start_process(argv, cwd)

    monkeypatch.setattr(customer_runtime_runner, "_start_process", counting_start_process)
    runtime = customer_runtime_runner.run(tmp_path)
    before = popen_count["count"]
    legacy = browser_visual_evidence.run(tmp_path, runtime_ref=runtime["result_file"])
    assert legacy["status"] == "NOT_EVALUATED"
    assert legacy["reason"] == "live_runtime_required"
    assert popen_count["count"] == before


def test_capture_live_runtime_rejects_stopped_runtime(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)

    class StoppedProcess:
        pid = 12345

        def poll(self):
            return 0

    handle = customer_runtime_runner.LiveRuntimeHandle(
        run_id="run",
        candidate_id="candidate",
        candidate_hash="sha256:" + "1" * 64,
        commit_sha="commit",
        source_project_root=tmp_path,
        execution_root=tmp_path.parent / "missing-runtime-root",
        pid=12345,
        port=1,
        url="http://127.0.0.1:1/",
        process=StoppedProcess(),
        startup_argv=[],
        started_at="now",
        source_candidate_hash="sha256:" + "1" * 64,
        copied_candidate_hash="sha256:" + "1" * 64,
        copied_manifest_hash="sha256:" + "2" * 64,
    )
    receipt = browser_visual_evidence.capture_live_runtime(handle)
    assert receipt["capture_status"] == "FAIL"
    assert receipt["error"] == "runtime_not_live"


def test_visual_runtime_pid_mismatch_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    _rewrite_visual(tmp_path, {"runtime_pid": 1})
    assert "runtime_pid" in browser_visual_evidence.inspect(tmp_path)["missing"]


def test_visual_runtime_url_mismatch_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    _rewrite_visual(tmp_path, {"runtime_url": "http://127.0.0.1:1/"})
    assert "runtime_url" in browser_visual_evidence.inspect(tmp_path)["missing"]


def test_visual_runtime_port_mismatch_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    _rewrite_visual(tmp_path, {"runtime_port": 1})
    assert "runtime_port" in browser_visual_evidence.inspect(tmp_path)["missing"]


def test_visual_runtime_execution_root_mismatch_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    _rewrite_visual(tmp_path, {"runtime_execution_root": str(tmp_path)})
    assert "runtime_execution_root" in browser_visual_evidence.inspect(tmp_path)["missing"]


def test_visual_capture_id_mismatch_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    _rewrite_visual(tmp_path, {"browser_capture_id": "other-capture"})
    assert "browser_capture_id" in browser_visual_evidence.inspect(tmp_path)["missing"]


def test_visual_capture_hash_mismatch_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    _rewrite_visual(tmp_path, {"browser_capture_hash": "sha256:" + "0" * 64})
    assert "browser_capture_hash" in browser_visual_evidence.inspect(tmp_path)["missing"]


def test_runtime_exits_during_capture_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)

    def stop_then_capture(handle: customer_runtime_runner.LiveRuntimeHandle) -> dict:
        handle.process.terminate()
        handle.process.wait(timeout=3)
        return browser_visual_evidence.capture_live_runtime(handle)

    runtime = customer_runtime_runner.run(
        tmp_path,
        live_consumer=stop_then_capture,
        browser_capture_required=True,
    )
    visual = browser_visual_evidence.finalize_evidence(
        tmp_path,
        runtime_result=runtime,
        capture_receipt=runtime["browser_capture_receipt"],
        required=True,
    )
    assert runtime["status"] == "FAIL"
    assert visual["status"] == "FAIL"
    assert runtime["shutdown_result"]["stopped"] is True
    assert runtime["cleanup_result"]["removed"] is True
    assert not pathlib.Path(runtime["execution_root"]).exists()


def test_playwright_exception_fails_and_runtime_cleans_up(tmp_path: pathlib.Path, monkeypatch) -> None:
    _make_static_project(tmp_path)
    real_import = builtins.__import__

    def failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "playwright.sync_api":
            raise RuntimeError("playwright boom")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    runtime = customer_runtime_runner.run(
        tmp_path,
        live_consumer=browser_visual_evidence.capture_live_runtime,
        browser_capture_required=True,
    )
    visual = browser_visual_evidence.finalize_evidence(
        tmp_path,
        runtime_result=runtime,
        capture_receipt=runtime["browser_capture_receipt"],
        required=True,
    )
    assert runtime["status"] == "FAIL"
    assert visual["status"] == "FAIL"
    assert "playwright boom" in visual["capture_error"]
    assert runtime["shutdown_result"]["stopped"] is True
    assert runtime["cleanup_result"]["removed"] is True
    assert not pathlib.Path(runtime["execution_root"]).exists()


def test_visual_runtime_reference_tamper_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    runtime_doc = json.loads((tmp_path / "customer_runtime.json").read_text(encoding="utf-8"))
    runtime_doc["observed_result"] = "tampered runtime"
    (tmp_path / "customer_runtime.json").write_text(json.dumps(runtime_doc), encoding="utf-8")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "customer_runtime_hash" in result["missing"]
    assert "customer_runtime_ref_inspect" in result["missing"]


def test_visual_screenshot_file_tamper_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _runtime, visual, _calls = _run_with_visual(tmp_path)
    pathlib.Path(visual["screenshot_path"]).write_bytes(b"tampered screenshot")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "screenshot_hash" in result["missing"]


def test_visual_fake_artifact_hash_fails(tmp_path: pathlib.Path) -> None:
    _make_static_project(tmp_path)
    _run_with_visual(tmp_path)
    doc = json.loads((tmp_path / "visual_evidence.json").read_text(encoding="utf-8"))
    doc["artifact_hash"] = "sha256:" + "4" * 64
    (tmp_path / "visual_evidence.json").write_text(json.dumps(doc), encoding="utf-8")
    result = browser_visual_evidence.inspect(tmp_path)
    assert result["status"] == "FAIL"
    assert "artifact_hash_mismatch" in result["missing"]
