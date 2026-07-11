from __future__ import annotations

import json
import pathlib
import sys
import tempfile

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.post_build_finalize as post_build_finalize
import scripts.post_build_repair as post_build_repair
import scripts.visual_evidence as visual_evidence
import scripts.artifact_integrity as artifact_integrity


def test_agent_guide_documents_module_routing() -> None:
    text = (ROOT / "docs" / "60_pipeline_module_agent_guide.md").read_text(encoding="utf-8")

    assert "run_local_pipeline.py is orchestration only" in text
    assert "provider transport / model routing / split generation" in text
    assert "post_build_repair.py" in text
    assert "final_delivery_truth.py" in text
    assert "Do not treat `candidate_diagnostic_bundle.zip` as `final_project_bundle.zip`" in text


def test_startup_visual_contract_documents_required_fields() -> None:
    text = (ROOT / "docs" / "61_startup_and_visual_evidence_contract.md").read_text(encoding="utf-8")

    for field in ("startup_command", "startup_cwd", "startup_returncode", "startup_stdout_tail", "startup_stderr_tail", "server_ready", "opened_url"):
        assert field in text
    for field in ("failure_reason", "browser_used", "page_title", "body_text_length", "blank_score", "is_blank_or_invalid"):
        assert field in text
    assert "body_text_length > 50" in text
    assert "Task" in text and "Bug" in text and "Dashboard" in text


def test_failure_routing_cheatsheet_contains_known_failures() -> None:
    text = (ROOT / "docs" / "62_agent_failure_routing_cheatsheet.md").read_text(encoding="utf-8")

    assert "ERR_UNSUPPORTED_ESM_URL_SCHEME" in text
    assert "'vitest' is not recognized" in text
    assert "body_text_length=0" in text
    assert "startup_failed" in text
    assert "provider HTTP 504 / TLS" in text


def test_startup_failed_writes_diagnostics() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        blocked = project / "screenshot_blocked.json"
        blocked.write_text(json.dumps({"status": "blocked", "failure_reason": "startup_failed"}), encoding="utf-8")

        post_build_finalize.ensure_startup_diagnostics(blocked, project)
        doc = json.loads(blocked.read_text(encoding="utf-8"))

    assert doc["startup_cwd"]
    assert "startup_command" in doc
    assert "startup_returncode" in doc
    assert "startup_stdout_tail" in doc
    assert "startup_stderr_tail" in doc
    assert doc["server_ready"] is False
    assert doc["failure_reason"] == "startup_failed"


def test_tests_pass_but_startup_failed_writes_candidate_review_summary(monkeypatch) -> None:
    class FakeLegacy:
        @staticmethod
        def write_candidate_review_summary(project_dir, *, verdict, test_status, screenshots, video_blocked, known_limits):
            path = pathlib.Path(project_dir) / "candidate_review_summary.json"
            path.write_text(json.dumps({"verdict": verdict, "test_status": test_status, "final_delivery": False}), encoding="utf-8")
            return str(path)

        @staticmethod
        def write_screenshot_blocked(*args, **kwargs):  # pragma: no cover - not used in this test
            raise AssertionError("tests already passed with existing screenshot_blocked")

    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        blocked = project / "screenshot_blocked.json"
        blocked.write_text(json.dumps({"status": "blocked", "failure_reason": "startup_failed"}), encoding="utf-8")
        monkeypatch.setattr(post_build_finalize, "_legacy", lambda: FakeLegacy)

        result = {"test_result": {"status": "pass"}, "screenshots": [], "screenshot_blocked": str(blocked), "known_limits": ["startup failed"]}
        post_build_finalize.ensure_candidate_review_artifacts(project, result)
        summary = json.loads((project / "candidate_review_summary.json").read_text(encoding="utf-8"))

    assert summary["verdict"] == "ASK_USER_REVIEW"
    assert summary["final_delivery"] is False


def test_missing_start_script_uses_pipeline_static_server_or_repairs_package_script() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "index.html").write_text("<!doctype html><title>Task Board</title><div id='root'>Task Bug Todo Doing Done Open Fixed Add Dashboard</div>", encoding="utf-8")
        (project / "package.json").write_text(json.dumps({"scripts": {"test": "node scripts/test.js"}}), encoding="utf-8")
        finalize = {
            "test_result": {"status": "pass", "argv": ["npm", "test"]},
            "screenshots": [],
            "screenshot_capture": {"status": "blocked", "failure_reason": "missing_start_script", "attempts": [{"reason": "missing script: start"}]},
            "known_limits": ["missing script: start"],
        }

        plan = post_build_repair.compile_post_build_repair_plan(project, finalize)
        result = post_build_repair.apply_deterministic_post_build_repair(project, plan)
        package_doc = json.loads((project / "package.json").read_text(encoding="utf-8"))
        candidates = visual_evidence.startup_entry_candidates(project)

    assert "missing_start_script" in plan["failure_types"]
    assert "package.json" in result["changed_files"]
    assert package_doc["scripts"]["start"].startswith("python -m http.server")
    assert candidates[0]["mode"] == "static_html"


def test_no_tests_ran_uses_node_builtin_test_runner_repair() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "tests").mkdir()
        (project / "tests" / "smoke_test.mjs").write_text("export {};\n", encoding="utf-8")
        finalize = {
            "test_result": {"status": "failed", "argv": [sys.executable, "-m", "pytest", "-q"], "stdout_tail": "no tests ran in 0.03s"},
            "screenshots": [],
        }

        plan = post_build_repair.compile_post_build_repair_plan(project, finalize)
        result = post_build_repair.apply_deterministic_post_build_repair(project, plan)
        package_doc = json.loads((project / "package.json").read_text(encoding="utf-8"))

    assert "no_tests_ran" in plan["failure_types"]
    assert "package.json" in result["changed_files"]
    assert "scripts/test.js" in result["changed_files"]
    assert package_doc["scripts"]["test"] == "node scripts/test.js"


def test_page_blank_routes_to_visual_evidence_and_post_build_repair() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "index.html").write_text("<!doctype html><title>Task Board</title><body></body>", encoding="utf-8")
        finalize = {
            "test_result": {"status": "pass", "argv": ["npm", "test"]},
            "screenshots": [],
            "screenshot_capture": {"status": "blocked", "failure_reason": "page_blank", "attempts": [{"reason": "body_text_length=0 page_blank"}]},
        }

        plan = post_build_repair.compile_post_build_repair_plan(project, finalize)
        result = post_build_repair.apply_deterministic_post_build_repair(project, plan)
        main = (project / "src" / "main.js").read_text(encoding="utf-8")

    assert "page_blank" in plan["failure_types"]
    assert any(action["action"] == "repair_page_blank_demo_ui" for action in plan["deterministic_actions"])
    assert "src/main.js" in result["changed_files"]
    assert "Game Team Task and Bug Dashboard" in main


def test_frontend_backend_start_mismatch_uses_demo_data_for_static_preview() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "index.html").write_text("<!doctype html><html><head></head><body><div id='root'></div></body></html>", encoding="utf-8")
        finalize = {
            "test_result": {"status": "pass", "argv": ["npm", "test"]},
            "screenshots": [],
            "screenshot_capture": {"status": "blocked", "failure_reason": "startup_failed", "attempts": [{"reason": "requestfailed /api net::ERR_CONNECTION_REFUSED"}]},
        }

        plan = post_build_repair.compile_post_build_repair_plan(project, finalize)
        result = post_build_repair.apply_deterministic_post_build_repair(project, plan)
        index = (project / "index.html").read_text(encoding="utf-8")

    assert "frontend_backend_start_mismatch" in plan["failure_types"]
    assert "index.html" in result["changed_files"]
    assert "CGNK_STATIC_PREVIEW_DEMO_DATA" in index


def test_run_local_pipeline_does_not_grow_with_startup_repair() -> None:
    source_path = ROOT / "scripts" / "run_local_pipeline.py"
    source = source_path.read_text(encoding="utf-8", errors="replace")
    line_count = len(source.splitlines())

    assert line_count <= 300
    assert "def startup_base_details" not in source
    assert "def repair_page_blank_demo_ui" not in source
    assert "def repair_missing_start_script" not in source


def test_video_requested_by_default_for_formal_project(monkeypatch) -> None:
    monkeypatch.delenv("CGNK_DISABLE_VIDEO", raising=False)

    assert visual_evidence.video_requested() is True


def test_video_not_requested_only_when_explicitly_disabled(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_DISABLE_VIDEO", "1")

    assert visual_evidence.video_requested() is False
    assert visual_evidence.video_requested(True) is True
    assert visual_evidence.video_requested(False) is False


def test_video_blocked_reason_not_not_requested_when_default(monkeypatch) -> None:
    monkeypatch.delenv("CGNK_DISABLE_VIDEO", raising=False)
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        blocked = visual_evidence.write_video_blocked(project, "default video failed", failure_reason="not_requested", video_requested_value=True)
        doc = json.loads(pathlib.Path(blocked).read_text(encoding="utf-8"))

    assert doc["video_requested"] is True
    assert doc["failure_reason"] != "not_requested"


def test_no_video_flag_records_not_requested() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        run_dir = project / "run"
        result = visual_evidence.capture_candidate_video(project, run_dir, explicit_requested=False)
        doc = json.loads(pathlib.Path(result["video_blocked"]).read_text(encoding="utf-8"))

    assert result["failure_reason"] == "not_requested"
    assert doc["video_requested"] is False
    assert doc["failure_reason"] == "not_requested"


def test_video_file_validation_rejects_placeholder_or_zero_byte() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        zero = root / "zero.webm"
        fake = root / "fake.webm"
        zero.write_bytes(b"")
        fake.write_bytes(b"placeholder video" * 300)

        zero_diag = visual_evidence.video_file_diagnostics(zero)
        fake_diag = visual_evidence.video_file_diagnostics(fake)

    assert zero_diag["valid"] is False
    assert fake_diag["valid"] is False


def test_visual_evidence_attempts_video_when_browser_available(monkeypatch) -> None:
    pytest.importorskip("playwright.sync_api")
    monkeypatch.delenv("CGNK_DISABLE_VIDEO", raising=False)
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "candidate"
        run_dir = pathlib.Path(temp_dir) / "run"
        project.mkdir()
        (project / "index.html").write_text(
            "<!doctype html><title>Task Board</title><body><h1>Task Board Dashboard</h1><p>Task Bug Todo Doing Done Open Fixed Add Dashboard local JSON persistence filters owners priorities tags due dates.</p></body>",
            encoding="utf-8",
        )

        result = visual_evidence.capture_candidate_video(project, run_dir, timeout=30)
        if result["status"] == "pass":
            assert visual_evidence.video_file_diagnostics(pathlib.Path(result["video"]))["valid"] is True

    assert result["video_requested"] is True
    assert result.get("failure_reason") != "not_requested"


def test_candidate_review_summary_includes_video_status(monkeypatch) -> None:
    class FakeLegacy:
        @staticmethod
        def create_candidate_diagnostic_package(project_dir, run_dir):
            bundle = pathlib.Path(run_dir) / "artifacts" / "candidate_diagnostic_bundle.zip"
            bundle.parent.mkdir(parents=True, exist_ok=True)
            bundle.write_bytes(b"PK\x05\x06" + b"\0" * 18)
            return bundle

    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "candidate"
        run_dir = pathlib.Path(temp_dir) / "run"
        project.mkdir()
        summary = project / "candidate_review_summary.json"
        summary.write_text(json.dumps({"verdict": "ASK_USER_REVIEW", "final_delivery": False}), encoding="utf-8")
        blocked = visual_evidence.write_video_blocked(project, "startup failed", failure_reason="startup_failed", video_requested_value=True)
        monkeypatch.setattr(post_build_finalize, "_legacy", lambda: FakeLegacy)

        result = {"video": "", "video_blocked": blocked, "video_requested": True, "video_status": "blocked"}
        post_build_finalize.update_candidate_review_video_status(project, result)
        doc = json.loads(summary.read_text(encoding="utf-8"))

    assert doc["video_requested"] is True
    assert doc["video_status"] == "blocked"
    assert doc["video_blocked_path"] == blocked
    assert doc["video_failure_reason"] == "startup_failed"


def test_candidate_bundle_includes_video_or_video_blocked() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        bundle = root / "candidate_diagnostic_bundle.zip"
        import zipfile

        with zipfile.ZipFile(bundle, "w") as zf:
            for name in ("candidate_review_summary.json", "TEST_REPORT.md", "known_limits.json", "repair_plan.json", "screenshot_blocked.json"):
                zf.writestr(name, "{}")
        result = artifact_integrity.validate_candidate_bundle(bundle, require_video=True)

    assert result["status"] == "fail"
    assert "candidate bundle missing video or video_blocked" in result["blockers"]


def test_video_blocked_allows_deliver_with_warnings_but_not_pass_final() -> None:
    post_build = {
        "test_result": {"status": "pass"},
        "ui_smoke": {"status": "pass"},
        "screenshots": ["candidate_home.png"],
        "video": "",
        "video_blocked": "video_blocked.json",
    }

    pass_final = bool(post_build["test_result"]["status"] == "pass" and post_build["screenshots"] and post_build["video"])
    deliver_with_warnings = bool(post_build["test_result"]["status"] == "pass" and post_build["screenshots"] and post_build["video_blocked"])

    assert deliver_with_warnings is True
    assert pass_final is False
