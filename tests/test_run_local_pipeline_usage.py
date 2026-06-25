from __future__ import annotations

import os
import json
import pathlib
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_local_pipeline as run_local_pipeline
import scripts.local_packager as local_packager
import scripts.check_test_environment as check_test_environment
import scripts.run_candidate_smoke_benchmark as run_candidate_smoke_benchmark


def tiny_nonblank_png() -> bytes:
    import binascii
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    width = 640
    height = 360
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend((20, 20, 20) if x < 220 and y < 140 else (255, 255, 255))
        rows.append(b"\x00" + bytes(row))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def tiny_blank_png() -> bytes:
    import binascii
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    width = 640
    height = 360
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes([255, 255, 255]) * width
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b"")


def make_temp_candidate_project(tmp_root: pathlib.Path) -> pathlib.Path:
    project = tmp_root / "candidate"
    project.mkdir(parents=True)
    (project / "README.md").write_text("# Candidate\n", encoding="utf-8")
    (project / "index.html").write_text("<!doctype html><title>Task Board</title><body>Task Board Todo Doing Done</body>\n", encoding="utf-8")
    return project


def install_fake_playwright(screenshot_bytes: bytes, *, body_text: str = "Task Board", title: str = "Task Board", opened_urls: list[str] | None = None) -> dict[str, object]:
    opened_urls = opened_urls if opened_urls is not None else []
    old_modules = {name: sys.modules.get(name) for name in ("playwright", "playwright.sync_api")}

    class FakePage:
        def on(self, event, callback):
            return None

        def goto(self, url, wait_until=None, timeout=None):
            opened_urls.append(str(url))

        def wait_for_timeout(self, _ms):
            return None

        def title(self):
            return title

        def evaluate(self, _script):
            return body_text

        def screenshot(self, path, full_page=True):
            pathlib.Path(path).write_bytes(screenshot_bytes)

    class FakeBrowser:
        def new_page(self, **_kwargs):
            return FakePage()

        def close(self):
            return None

    class FakeChromium:
        def launch(self):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    package = types.ModuleType("playwright")
    package.__version__ = "fake"
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: FakePlaywright()
    sys.modules["playwright"] = package
    sys.modules["playwright.sync_api"] = sync_api
    return old_modules


def restore_fake_playwright(old_modules: dict[str, object]) -> None:
    for name, module in old_modules.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class RunLocalPipelineUsageTests(unittest.TestCase):
    def test_usage_plan_placeholders_expand_project_file_url(self) -> None:
        project_dir = ROOT / "generated" / "demo_project"
        run_dir = ROOT / "examples" / "runtime_runs" / "demo_project"
        plan = {
            "wait_url": "file://{project_dir}/index.html",
            "browser_steps": [
                {"action": "goto", "url": "file://{project_dir}/index.html"},
                {"action": "fill", "selector": "textarea", "text": "{project_dir}"},
            ],
            "pre_commands": [["python", "{project_dir}\\scripts\\demo.py"]],
        }
        normalized = run_local_pipeline.normalize_usage_plan_placeholders(plan, project_dir, run_dir)
        self.assertEqual(project_dir.resolve().as_uri() + "/index.html", normalized["wait_url"])
        self.assertEqual(project_dir.resolve().as_uri() + "/index.html", normalized["browser_steps"][0]["url"])
        self.assertIn(str(project_dir.resolve()), normalized["browser_steps"][1]["text"])
        self.assertIn(str(project_dir.resolve()), normalized["pre_commands"][0][1])

    def test_pip_install_pre_command_is_skipped_without_failure(self) -> None:
        result = run_local_pipeline.run_allowed_command(["python", "-m", "pip", "install", "-r", "requirements.txt"], ROOT)
        self.assertEqual("pass", result["status"])
        self.assertTrue(result["skipped"])
        self.assertIn("shared runtime", result["reason"])

    def test_frozen_user_intent_prefers_original_requirement_over_compressed_goal(self) -> None:
        original = "做一个工具，通过 CSGO2 demo 文件分析鼠标键盘动作和视角，用于鉴别外挂行为。"
        compressed = "# CGNK Requirement Blueprint Generator\n\n## Current Project Summary\n" + original

        intent = run_local_pipeline.frozen_user_intent(
            {
                "original_requirement": original,
                "pipeline_plan": {"payload": {"requirement": compressed}},
            },
            compressed,
        )

        self.assertEqual("data_analysis_tool", intent["project_type"])
        self.assertEqual(original, intent["raw_user_message"])

    def test_usage_planning_writes_diagnostics_and_phase_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = pathlib.Path(temp_dir)
            project_dir = base / "project"
            run_dir = base / "run"
            project_dir.mkdir()
            (project_dir / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
            phase_log = run_dir / "artifacts" / "generation_phase_log.jsonl"

            result = run_local_pipeline.run_project_usage_agent(
                "本地静态页面",
                project_dir,
                run_dir,
                ["index.html"],
                {"project_type": "local_application"},
                {},
                "unused",
                30,
                phase_log_path=phase_log,
            )

            self.assertIn(result["status"], {"partial", "pass", "failed"})
            diagnostics = run_dir / "agent_usage" / "usage_planning_diagnostics.json"
            self.assertTrue(diagnostics.exists())
            log_text = phase_log.read_text(encoding="utf-8")
            self.assertIn("usage_planning_local", log_text)
            self.assertIn("usage_plan.json written", log_text)

    def test_provider_plan_doc_strips_internal_context_prompt(self) -> None:
        plan = {
            "goal": "做一个真实项目",
            "internal_context_prompt": "CGNK_CONTEXT_PROMPT requirement_blueprint",
            "pipeline_plan": {"payload": {"requirement": "做一个真实项目"}},
        }

        sanitized = run_local_pipeline.provider_plan_doc(plan)

        self.assertNotIn("internal_context_prompt", sanitized)
        self.assertEqual("做一个真实项目", sanitized["goal"])

    def test_provider_blueprint_context_is_marked_as_supporting_only(self) -> None:
        context = run_local_pipeline.provider_blueprint_context({"raw_requirement": "做一个真实项目"})

        self.assertEqual("supporting_requirement_analysis_only", context["role"])
        self.assertIn("not a blueprint generator", context["warning"])
        self.assertEqual("做一个真实项目", context["doc"]["raw_requirement"])

    def test_remaining_timeout_is_capped_by_deadline(self) -> None:
        deadline = time.time() + 6

        value = run_local_pipeline.remaining_timeout(deadline, 120, floor=1, cap=90)

        self.assertLessEqual(value, 6)
        self.assertGreaterEqual(value, 1)

    def test_progress_deadline_extends_after_meaningful_work(self) -> None:
        deadline = run_local_pipeline.ProgressDeadline(time.time() - 1, extension_seconds=60)

        deadline.mark_progress("project_generation", "component returned files", ["app.py"])
        value = run_local_pipeline.remaining_timeout(deadline, 120, floor=5, cap=90)

        self.assertGreaterEqual(value, 5)
        self.assertEqual("project_generation", deadline.progress_events[-1]["phase"])

    def test_provider_component_progress_refreshes_deadline_between_components(self) -> None:
        original = run_local_pipeline.provider_generate_project_component
        calls: list[str] = []

        def fake_provider_component(**kwargs):
            component_id = kwargs["component"]["id"]
            calls.append(component_id)
            time.sleep(1.2)
            return {
                "component_id": component_id,
                "summary": f"{component_id} done",
                "files": [{"path": f"{component_id}.py", "content": "print('ok')\n"}],
            }

        run_local_pipeline.provider_generate_project_component = fake_provider_component
        try:
            deadline = run_local_pipeline.ProgressDeadline(time.time() + 6, extension_seconds=60)
            result = run_local_pipeline.provider_generate_project_by_components(
                "build a project",
                {
                    "components": [{"id": "app"}, {"id": "tests"}],
                    "merge_policy": {"required_final_files": ["app.py", "tests.py"]},
                },
                {},
                {},
                {},
                {},
                [],
                "unused",
                30,
                deadline=deadline,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original

        self.assertEqual(["app", "tests"], calls)
        self.assertEqual(2, len(result["files"]))
        self.assertTrue(deadline.progress_events)

    def test_provider_component_checkpoint_resumes_completed_components(self) -> None:
        original = run_local_pipeline.provider_generate_project_component
        original_fast = os.environ.get("CGKN_PROVIDER_RETRY_FAST")
        os.environ["CGKN_PROVIDER_RETRY_FAST"] = "1"
        calls: list[str] = []

        def first_run_component(**kwargs):
            component_id = kwargs["component"]["id"]
            calls.append(component_id)
            if component_id == "backend":
                raise RuntimeError("provider_api_request_failed: HTTP 520: upstream failed [retryable=true]")
            return {
                "component_id": component_id,
                "summary": "foundation done",
                "files": [{"path": "app.py", "content": "print('ok')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass", "checks": ["validated"]},
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_dir = pathlib.Path(temp_dir) / "artifacts" / "provider_components"
            pipeline = {
                "components": [{"id": "foundation"}, {"id": "backend"}],
                "merge_policy": {"required_final_files": ["app.py", "src/backend.py"]},
            }
            run_local_pipeline.provider_generate_project_component = first_run_component
            try:
                with self.assertRaises(RuntimeError):
                    run_local_pipeline.provider_generate_project_by_components(
                        "build a project",
                        pipeline,
                        {},
                        {},
                        {},
                        {},
                        [],
                        "unused",
                        30,
                        checkpoint_dir=checkpoint_dir,
                    )
                self.assertEqual(["foundation", "backend", "backend", "backend"], calls)
                self.assertTrue((checkpoint_dir / "foundation.json").exists())
                calls.clear()

                def second_run_component(**kwargs):
                    component_id = kwargs["component"]["id"]
                    calls.append(component_id)
                    if component_id == "foundation":
                        raise AssertionError("foundation should have been loaded from checkpoint")
                    return {
                        "component_id": component_id,
                        "summary": "backend done",
                        "files": [{"path": "src/backend.py", "content": "def ok():\n    return True\n"}],
                        "quality_gate": {"status": "pass"},
                        "self_test": {"status": "pass", "checks": ["validated"]},
                    }

                run_local_pipeline.provider_generate_project_component = second_run_component
                result = run_local_pipeline.provider_generate_project_by_components(
                    "build a project",
                    pipeline,
                    {},
                    {},
                    {},
                    {},
                    [],
                    "unused",
                    30,
                    checkpoint_dir=checkpoint_dir,
                )
                self.assertTrue((checkpoint_dir / "component_checkpoint_summary.json").exists())
            finally:
                run_local_pipeline.provider_generate_project_component = original
                if original_fast is None:
                    os.environ.pop("CGKN_PROVIDER_RETRY_FAST", None)
                else:
                    os.environ["CGKN_PROVIDER_RETRY_FAST"] = original_fast

        self.assertEqual(["backend"], calls)
        self.assertEqual(["foundation"], result["component_checkpoint_summary"]["skipped_from_checkpoint"])
        self.assertIn("foundation", result["component_checkpoint_summary"]["completed_components"])
        self.assertIn("backend", result["component_checkpoint_summary"]["completed_components"])

    def test_component_merge_generates_test_plan_from_real_tests(self) -> None:
        original = run_local_pipeline.provider_generate_project_component

        def fake_provider_component(**kwargs):
            component_id = kwargs["component"]["id"]
            if component_id == "docs":
                return {
                    "component_id": component_id,
                    "summary": "docs",
                    "files": [{"path": "README.md", "content": "# App\n"}],
                    "quality_gate": {"status": "pass"},
                    "self_test": {"status": "pass", "checks": ["validated"]},
                }
            return {
                "component_id": component_id,
                "summary": "tests",
                "files": [{"path": "tests/test_app.py", "content": "def test_ok():\n    assert True\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass", "checks": ["validated"]},
            }

        run_local_pipeline.provider_generate_project_component = fake_provider_component
        try:
            result = run_local_pipeline.provider_generate_project_by_components(
                "build a project",
                {
                    "components": [{"id": "docs"}, {"id": "tests"}],
                    "merge_policy": {"required_final_files": ["README.md", "TEST_PLAN.md"]},
                },
                {},
                {},
                {},
                {},
                [],
                "unused",
                30,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original

        files = {item["path"]: item["content"] for item in result["files"]}
        self.assertIn("TEST_PLAN.md", files)
        self.assertIn("tests/test_app.py", files["TEST_PLAN.md"])

    def test_component_merge_combines_document_conflicts_only(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "foundation", "files": [{"path": "README.md", "content": "# App\n"}]},
                {"component_id": "docs", "files": [{"path": "README.md", "content": "# Usage\n"}]},
            ]
        )
        readme = {item["path"]: item["content"] for item in files}["README.md"]
        self.assertIn("# App", readme)
        self.assertIn("# Usage", readme)

        with self.assertRaises(RuntimeError):
            run_local_pipeline.merge_component_files(
                [
                    {"component_id": "one", "files": [{"path": "src/app.py", "content": "print(1)\n"}]},
                    {"component_id": "two", "files": [{"path": "src/app.py", "content": "print(2)\n"}]},
                ]
            )

    def test_component_merge_allows_frontend_asset_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "foundation", "files": [{"path": "app/index.html", "content": "<h1>base</h1>\n"}]},
                {"component_id": "frontend", "files": [{"path": "app/index.html", "content": "<h1>frontend</h1>\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("<h1>frontend</h1>\n", merged["app/index.html"])

    def test_component_merge_allows_template_asset_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "foundation", "files": [{"path": "templates/index.html", "content": "<h1>base</h1>\n"}]},
                {"component_id": "execution", "files": [{"path": "templates/index.html", "content": "<h1>execution</h1>\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("<h1>execution</h1>\n", merged["templates/index.html"])

    def test_component_merge_allows_top_level_entrypoint_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "generation", "files": [{"path": "app.py", "content": "print('base')\n"}]},
                {"component_id": "execution", "files": [{"path": "app.py", "content": "print('runnable')\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("print('runnable')\n", merged["app.py"])

    def test_component_merge_allows_src_file_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "init", "files": [{"path": "src/task_store.py", "content": "TASKS = []\n"}]},
                {"component_id": "generate_project", "files": [{"path": "src/task_store.py", "content": "TASKS = ['ready']\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("TASKS = ['ready']\n", merged["src/task_store.py"])

    def test_component_merge_allows_test_file_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "init", "files": [{"path": "tests/test_app.py", "content": "def test_placeholder(): pass\n"}]},
                {"component_id": "generate_project", "files": [{"path": "tests/test_app.py", "content": "def test_home(): pass\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("def test_home(): pass\n", merged["tests/test_app.py"])

    def test_component_merge_accepts_test_report_as_qa_evidence(self) -> None:
        original = run_local_pipeline.provider_generate_project_component

        def fake_component(**kwargs):
            component_id = kwargs["component"]["id"]
            if component_id == "docs":
                return {"component_id": "docs", "files": [{"path": "README.md", "content": "# Demo\n"}]}
            return {
                "component_id": "execution",
                "files": [
                    {"path": "app.py", "content": "print('ok')\n"},
                    {"path": "TEST_REPORT.md", "content": "commands_run: pytest\nexit_code: 0\n"},
                ],
            }

        run_local_pipeline.provider_generate_project_component = fake_component
        try:
            result = run_local_pipeline.provider_generate_project_by_components(
                goal="做一个小工具",
                component_pipeline={
                    "components": [
                        {"id": "docs", "goal": "Write docs", "acceptance": []},
                        {"id": "execution", "goal": "Write runnable app and test report", "acceptance": []},
                    ],
                    "merge_policy": {"required_final_files": ["README.md", "TEST_PLAN.md"]},
                },
                plan_doc={},
                blueprint={},
                online_inputs={},
                market_research={},
                repair_errors=[],
                model="gpt-test",
                timeout=5,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original

        files = {item["path"]: item["content"] for item in result["files"]}
        assert "README.md" in files
        assert "TEST_REPORT.md" in files

    def test_provider_semantic_review_retry_on_frontend_backend_mismatch(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project
        original_split = os.environ.get("CGNK_SPLIT_FRONTEND_COMPONENT")
        calls: list[str] = []

        def fake_component(**kwargs):
            component_id = kwargs["component"]["id"]
            repairs = "\n".join(kwargs.get("repair_errors", []))
            calls.append(component_id)
            if component_id == "foundation":
                return {
                    "component_id": component_id,
                    "files": [{"path": "package.json", "content": '{"type":"module","scripts":{"test":"node --test"}}\n'}],
                    "quality_gate": {"status": "pass"},
                    "self_test": {"status": "pass", "checks": ["module system ok"]},
                }
            if component_id == "backend":
                return {
                    "component_id": component_id,
                    "files": [{"path": "backend/server.mjs", "content": "import fs from 'node:fs/promises';\nexport async function save(tasks){ await fs.writeFile('data/tasks.json', JSON.stringify(tasks)); }\n"}],
                    "quality_gate": {"status": "pass"},
                    "self_test": {"status": "pass", "checks": ["json persistence ok"]},
                }
            if component_id == "frontend":
                content = "localStorage.setItem('tasks', JSON.stringify([]));\n"
                if "fetch" in repairs:
                    content = "export async function load(){ return fetch('/api/tasks').then(r => r.json()); }\n"
                return {
                    "component_id": component_id,
                    "files": [{"path": "frontend/app.js", "content": content}],
                    "quality_gate": {"status": "pass"},
                    "self_test": {"status": "pass", "checks": ["frontend ok"]},
                }
            return {
                "component_id": component_id,
                "files": [{"path": "README.md", "content": "# Task Board\n\nRun `npm test`.\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass", "checks": ["docs ok"]},
            }

        def fake_review(*args, **kwargs):
            files = {item["path"]: item["content"] for item in args[6]}
            if "fetch('/api/tasks')" not in files.get("frontend/app.js", ""):
                return {
                    "status": "fail",
                    "issues": ["前端未调用后端 API，仍使用 localStorage；后端 JSON 持久化未形成闭环"],
                    "review_summary": "frontend/backend mismatch",
                }
            self.assertIn("writeFile('data/tasks.json'", files["backend/server.mjs"])
            return {"status": "pass", "issues": [], "review_summary": "fixed"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = "0"
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={
                        "components": [{"id": "foundation"}, {"id": "backend"}, {"id": "frontend"}, {"id": "docs"}],
                        "merge_policy": {"required_final_files": ["README.md"]},
                    },
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review
                if original_split is None:
                    os.environ.pop("CGNK_SPLIT_FRONTEND_COMPONENT", None)
                else:
                    os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = original_split

        files = {item["path"]: item["content"] for item in result["files"]}
        self.assertEqual("pass", result["status"])
        self.assertIn("fetch('/api/tasks')", files["frontend/app.js"])
        self.assertGreaterEqual(calls.count("frontend"), 2)
        self.assertGreaterEqual(calls.count("backend"), 2)
        self.assertEqual(["backend", "frontend"], result["attempted_repairs"][0]["affected_components"])

    def test_provider_semantic_review_retry_on_test_coverage_blocker(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project

        def fake_component(**kwargs):
            component_id = kwargs["component"]["id"]
            repairs = "\n".join(kwargs.get("repair_errors", []))
            if component_id == "tests":
                content = "def test_smoke():\n    assert True\n"
                if "CRUD" in repairs or "crud" in repairs.lower():
                    content = "def test_crud_filter_json_persistence_api():\n    assert {'status':'Done'}['status'] == 'Done'\n"
                return {"component_id": component_id, "files": [{"path": "tests/test_app.py", "content": content}], "quality_gate": {"status": "pass"}, "self_test": {"status": "pass"}}
            return {"component_id": component_id, "files": [{"path": "README.md", "content": "# App\n"}], "quality_gate": {"status": "pass"}, "self_test": {"status": "pass"}}

        def fake_review(*args, **kwargs):
            files = {item["path"]: item["content"] for item in args[6]}
            if "test_crud_filter_json_persistence_api" not in files.get("tests/test_app.py", ""):
                return {"status": "fail", "issues": ["自动化测试未覆盖 CRUD、状态筛选、JSON 持久化/API"], "review_summary": "tests superficial"}
            return {"status": "pass", "issues": [], "review_summary": "tests fixed"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={
                        "components": [{"id": "docs"}, {"id": "tests"}],
                        "merge_policy": {"required_final_files": ["README.md", "TEST_PLAN.md"]},
                    },
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review

        self.assertEqual("pass", result["status"])
        self.assertEqual(["tests"], result["attempted_repairs"][0]["affected_components"])
        self.assertIn("test_crud_filter_json_persistence_api", {item["path"]: item["content"] for item in result["files"]}["tests/test_app.py"])

    def test_provider_review_failure_writes_diagnostics_without_materializing(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project

        def fake_component(**kwargs):
            return {
                "component_id": kwargs["component"]["id"],
                "files": [{"path": "README.md", "content": "# Broken App\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_review(*args, **kwargs):
            return {"status": "fail", "issues": ["README 仍然是占位说明"], "review_summary": "still blocked"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            out_dir = root / "generated" / "project"
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "docs"}], "merge_policy": {"required_final_files": ["README.md"]}},
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=out_dir,
                    result_path=root / "result.json",
                    max_repair_attempts=1,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review

            diagnostics_path = root / "run" / "artifacts" / "provider_semantic_review_failure.json"
            self.assertEqual("blocked", result["status"])
            self.assertFalse(out_dir.exists())
            self.assertFalse((out_dir / "final_project_bundle.zip").exists())
            self.assertTrue(diagnostics_path.exists())
            diagnostics = run_local_pipeline.load_json(diagnostics_path)
            self.assertFalse(diagnostics["materialized"])
            self.assertIsNone(diagnostics["project_dir"])
            self.assertIn("README 仍然是占位说明", diagnostics["remaining_blockers"])

    def test_rejected_project_preview_not_delivery_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            preview = pathlib.Path(temp_dir) / "artifacts" / "rejected_project_preview"
            run_local_pipeline.write_rejected_project_preview(
                preview,
                [{"path": "README.md", "content": "# Rejected\n"}, {"path": "app.py", "content": "print('debug only')\n"}],
            )

            with self.assertRaises(RuntimeError):
                local_packager.package_project(preview)

    def test_compile_repair_plan_for_component_file_conflict(self) -> None:
        plan = run_local_pipeline.compile_repair_plan(
            ["component file conflict: src/app.js from foundation and frontend"],
            {},
            component_pipeline={"components": [{"id": "foundation"}, {"id": "frontend"}]},
        )

        parsed = plan["parsed_blockers"][0]
        self.assertEqual("component_file_conflict", parsed["kind"])
        self.assertEqual("frontend", parsed["legal_owner"])
        self.assertEqual(["foundation"], parsed["illegal_owners"])
        self.assertIn(
            {"action": "remove_file_from_component", "component": "foundation", "path": "src/app.js"},
            plan["deterministic_actions"],
        )

    def test_deterministic_repair_removes_illegal_foundation_source(self) -> None:
        component_files = {
            "foundation": [
                {"path": "package.json", "content": "{}\n"},
                {"path": "src/app.js", "content": "console.log('wrong owner')\n"},
            ],
            "frontend": [{"path": "src/app.js", "content": "console.log('frontend')\n"}],
        }
        plan = run_local_pipeline.compile_repair_plan(
            ["component file conflict: src/app.js from foundation and frontend"],
            component_files,
            component_pipeline={"components": [{"id": "foundation"}, {"id": "frontend"}]},
        )

        result = run_local_pipeline.apply_deterministic_repair_actions(component_files, plan)

        self.assertTrue(result["changed"])
        self.assertEqual(["package.json"], [item["path"] for item in component_files["foundation"]])
        self.assertEqual(["src/app.js"], [item["path"] for item in component_files["frontend"]])

    def test_repair_prompt_is_component_scoped_and_file_specific(self) -> None:
        plan = run_local_pipeline.compile_repair_plan(
            ["前端只用 localStorage，未调用后端 API"],
            {},
            component_pipeline={"components": [{"id": "frontend"}, {"id": "backend"}]},
        )
        prompt = run_local_pipeline.repair_plan_component_instructions(plan)["frontend"][0]

        self.assertIn("regenerating frontend_files only", prompt)
        self.assertIn("You own src/app.js", prompt)
        self.assertIn("Do not use localStorage as the primary persistence layer", prompt)

    def test_repair_invariant_failed_on_repeated_blocker(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project
        original_split = os.environ.get("CGNK_SPLIT_FRONTEND_COMPONENT")

        def fake_component(**kwargs):
            component_id = kwargs["component"]["id"]
            return {
                "component_id": component_id,
                "files": [{"path": "README.md" if component_id == "docs" else "src/app.js", "content": "localStorage.setItem('tasks','[]')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_review(*args, **kwargs):
            return {"status": "fail", "issues": ["前端只用 localStorage，未调用后端 API"], "review_summary": "same blocker"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = "0"
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review
                if original_split is None:
                    os.environ.pop("CGNK_SPLIT_FRONTEND_COMPONENT", None)
                else:
                    os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = original_split

        self.assertEqual("blocked", result["status"])
        self.assertEqual("repair_invariant_check", result["diagnostics"]["stage"])
        self.assertIn("REPAIR_INVARIANT_FAILED", result["provider_review"]["issues"])

    def test_transport_error_does_not_consume_semantic_repair_attempt(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component

        def fake_component(**kwargs):
            raise RuntimeError("provider_api_request_failed: HTTP 522: timeout [endpoint=https://api.gptsapi.net, retryable=true]")

        pending = run_local_pipeline.compile_repair_plan(
            ["前端只用 localStorage，未调用后端 API"],
            {},
            component_pipeline={"components": [{"id": "frontend"}, {"id": "backend"}]},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    initial_repair_plan=pending,
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component

            diagnostics = result["diagnostics"]
            self.assertEqual("provider_semantic_repair", diagnostics["stage"])
            self.assertEqual("provider_transport_failed", diagnostics["block_reason"])
            self.assertEqual(0, diagnostics["semantic_repair_attempts"])
            self.assertEqual([], result["attempted_repairs"])
            self.assertTrue((root / "run" / "artifacts" / "pending_repair_plan.json").exists())

    def test_resume_continues_pending_frontend_repair(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project
        calls: list[str] = []
        pending = run_local_pipeline.compile_repair_plan(
            ["component file conflict: src/app.js from foundation and frontend"],
            {},
            component_pipeline={"components": [{"id": "foundation"}, {"id": "frontend"}]},
        )
        pending["raw_user_goal"] = "做任务看板"

        def fake_component(**kwargs):
            calls.append(kwargs["component"]["id"])
            return {
                "component_id": kwargs["component"]["id"],
                "files": [{"path": "src/app.js", "content": "fetch('/api/tasks')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_review(*args, **kwargs):
            return {"status": "pass", "issues": [], "review_summary": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_dir = root / "run"
            (run_dir / "artifacts").mkdir(parents=True)
            run_local_pipeline.write_json(run_dir / "artifacts" / "pending_repair_plan.json", pending)
            loaded = run_local_pipeline.load_pending_repair_plan(run_dir)
            pipeline = {"components": [{"id": "foundation"}, {"id": "backend"}, {"id": "frontend"}], "merge_policy": {"required_final_files": ["package.json", "backend/server.py", "src/app.js"]}}
            checkpoint_dir = run_dir / "artifacts" / "provider_components"
            for component_id, rel in (("foundation", "package.json"), ("backend", "backend/server.py")):
                component = {"id": component_id}
                files = [{"path": rel, "content": "{}\n" if rel == "package.json" else "print('api')\n"}]
                run_local_pipeline.write_provider_component_checkpoint(
                    checkpoint_dir,
                    component_id=component_id,
                    spec_hash=run_local_pipeline.provider_component_spec_hash("做任务看板", pipeline, component),
                    status="pass",
                    raw_output="{}",
                    parsed_result={"component_id": component_id, "files": files, "quality_gate": {"status": "pass"}, "self_test": {"status": "pass"}},
                    files=files,
                    semantic_review={"status": "pass"},
                )
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal=loaded["raw_user_goal"],
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline=pipeline,
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=run_dir,
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    initial_repair_plan=loaded,
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review

        self.assertEqual("pass", result["status"])
        self.assertEqual(["frontend"], calls)

    def test_pending_repair_plan_written_before_provider_call(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        pending = run_local_pipeline.compile_repair_plan(
            ["component file conflict: src/app.js from foundation and frontend"],
            {"frontend": [{"path": "src/app.js", "content": "old\n"}]},
            component_pipeline={"components": [{"id": "foundation"}, {"id": "frontend"}]},
        )
        pending["raw_user_goal"] = "做任务看板"
        pipeline = {"components": [{"id": "foundation"}, {"id": "frontend"}], "merge_policy": {"required_final_files": ["package.json", "src/app.js"]}}

        def fake_component(**kwargs):
            pending_path = root / "run" / "artifacts" / "pending_repair_plan.json"
            self.assertTrue(pending_path.exists())
            doc = run_local_pipeline.load_json(pending_path)
            self.assertNotEqual({}, doc)
            self.assertEqual("做任务看板", doc["raw_user_goal"])
            self.assertEqual("frontend", doc["failed_component"])
            self.assertIn("src/app.js", doc["affected_files"])
            self.assertIn("frontend_repair_attempt_", doc["provider_prompt_path"])
            raise RuntimeError('provider_api_request_failed: HTTP 504: timeout [endpoint=https://api.gptsapi.net, retryable=true, provider_headers={"cf-ray":"ray-1","x-trace-id":"trace-1"}]')

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            checkpoint_dir = root / "run" / "artifacts" / "provider_components"
            run_local_pipeline.write_provider_component_checkpoint(
                checkpoint_dir,
                component_id="foundation",
                spec_hash=run_local_pipeline.provider_component_spec_hash(
                    "做任务看板",
                    pipeline,
                    {"id": "foundation"},
                ),
                status="pass",
                raw_output="{}",
                parsed_result={"component_id": "foundation", "files": [{"path": "package.json", "content": "{}\n"}]},
                files=[{"path": "package.json", "content": "{}\n"}],
                semantic_review={"status": "pass"},
            )
            run_local_pipeline.provider_generate_project_component = fake_component
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline=pipeline,
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    initial_repair_plan=pending,
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component

            self.assertEqual("blocked", result["status"])
            diagnostics = result["diagnostics"]
            self.assertEqual("provider_transport_failed", diagnostics["block_reason"])
            self.assertEqual(0, diagnostics["semantic_repair_attempts"])
            self.assertEqual("ray-1", diagnostics["provider_headers"]["cf-ray"])

    def test_resume_uses_run_context_when_pending_plan_exists(self) -> None:
        original_compose = run_local_pipeline.compose_local_pipeline.compose
        original_blueprint = run_local_pipeline.requirement_blueprint.build_requirement_blueprint
        original_online = run_local_pipeline.online_input_agent.collect_online_inputs
        original_market = run_local_pipeline.market_research_agent.run_market_research
        original_semantic = run_local_pipeline.run_provider_semantic_review_with_repair
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_dir = root / "run"
            (run_dir / "artifacts").mkdir(parents=True)
            run_local_pipeline.write_json(
                run_dir / "artifacts" / "pending_repair_plan.json",
                {"status": "pending", "stage": "provider_semantic_repair", "provider_actions": [{"component": "frontend", "path": "src/app.js", "instruction": "fix"}]},
            )
            run_local_pipeline.write_run_context(
                run_dir,
                raw_user_goal="做任务看板",
                model="unused",
                base_url="https://api.gptsapi.net/v1",
                generation_mode="api",
                requested_project_dir=root / "generated" / "project",
            )
            run_local_pipeline.compose_local_pipeline.compose = lambda *args, **kwargs: {"original_requirement": args[0], "pipeline_plan": {"payload": {"component_pipeline": {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}}}}}
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = lambda *args, **kwargs: {}
            run_local_pipeline.online_input_agent.collect_online_inputs = lambda *args, **kwargs: {}
            run_local_pipeline.market_research_agent.run_market_research = lambda *args, **kwargs: {}

            def fake_semantic(**kwargs):
                self.assertEqual("做任务看板", kwargs["user_goal"])
                self.assertTrue(kwargs["initial_repair_plan"])
                return {"status": "blocked", "generation": {}, "files": [], "provider_review": {"status": "fail", "issues": ["stop"]}, "attempted_repairs": [], "diagnostics": {"stage": "test"}}

            run_local_pipeline.run_provider_semantic_review_with_repair = fake_semantic
            try:
                result = run_local_pipeline.execute(
                    type(
                        "Args",
                        (),
                        {
                            "resume_run_dir": str(run_dir),
                            "run_dir": str(run_dir),
                            "out_dir": str(root / "generated" / "project"),
                            "result": str(root / "result.json"),
                            "plan": "",
                            "goal": "",
                            "use_api": False,
                            "allow_network": False,
                            "allow_provider": False,
                            "model": "unused",
                            "timeout": 30,
                            "provider_semantic_repair_attempts": 1,
                            "phase_log_path": "",
                        },
                    )()
                )
            finally:
                run_local_pipeline.compose_local_pipeline.compose = original_compose
                run_local_pipeline.requirement_blueprint.build_requirement_blueprint = original_blueprint
                run_local_pipeline.online_input_agent.collect_online_inputs = original_online
                run_local_pipeline.market_research_agent.run_market_research = original_market
                run_local_pipeline.run_provider_semantic_review_with_repair = original_semantic

            self.assertEqual("BLOCKED", result["status"])

    def test_resume_fails_with_specific_error_when_goal_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = pathlib.Path(temp_dir) / "run"
            (run_dir / "artifacts").mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "RESUME_CONTEXT_MISSING_GOAL"):
                run_local_pipeline.execute(
                    type(
                        "Args",
                        (),
                        {
                            "resume_run_dir": str(run_dir),
                            "run_dir": str(run_dir),
                            "out_dir": str(pathlib.Path(temp_dir) / "generated" / "project"),
                            "result": str(pathlib.Path(temp_dir) / "result.json"),
                            "plan": "",
                            "goal": "",
                            "use_api": False,
                            "allow_network": False,
                            "allow_provider": False,
                            "model": "unused",
                            "timeout": 30,
                            "provider_semantic_repair_attempts": 1,
                            "phase_log_path": "",
                        },
                    )()
                )

    def test_repair_prompt_budget_limits_payload(self) -> None:
        payload = {
            "pipeline_plan": {"huge": "x" * 50000},
            "requirement_blueprint": {"huge": "y" * 50000},
            "online_input_examples": {"huge": "z" * 50000},
            "market_research": {"huge": "m" * 50000},
        }
        scoped = run_local_pipeline.apply_repair_prompt_budget(
            payload,
            component_id="frontend",
            repair_actions=[{"component": "frontend", "path": "src/app.js"}],
            component_files=[
                {"path": "src/app.js", "content": "fetch('/api/tasks')\n"},
                {"path": "src/other.js", "content": "x\n"},
                {"path": "src/extra.js", "content": "y\n"},
                {"path": "src/ignored.js", "content": "z\n"},
            ],
        )

        self.assertTrue(scoped["repair_prompt_budget_applied"])
        self.assertEqual(["src/app.js"], scoped["repair_scope"]["target_files"])
        self.assertEqual(["src/app.js"], [item["path"] for item in scoped["repair_scope"]["relevant_existing_files"]])

    def test_file_level_repair_prompt_for_frontend_app_conflict(self) -> None:
        plan = run_local_pipeline.compile_repair_plan(
            ["component file conflict: src/app.js from foundation and frontend"],
            {},
            component_pipeline={"components": [{"id": "foundation"}, {"id": "frontend"}]},
        )
        prompt = run_local_pipeline.repair_plan_component_instructions(plan)["frontend"][0]

        self.assertIn("File-level repair mode", prompt)
        self.assertIn("Regenerate only src/app.js", prompt)
        self.assertIn("Return exactly 1 file", prompt)
        self.assertNotIn("foundation/backend/tests/docs", prompt)

    def test_transport_error_records_provider_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            pending = {"status": "pending", "raw_user_goal": "做任务看板", "provider_actions": [{"component": "frontend", "path": "src/app.js"}]}
            run_local_pipeline.write_pending_repair_context(root / "run" / "artifacts" / "pending_repair_plan.json", pending)
            diagnostics = run_local_pipeline.write_provider_transport_blocked_failure(
                root / "run",
                root / "generated" / "project",
                'provider_api_request_failed: HTTP 504: timeout [endpoint=https://api.gptsapi.net, retryable=true, provider_headers={"cf-ray":"ray-2","x-request-id":"req-2","server":"cloudflare"}]',
                pending,
                [],
                root / "run" / "artifacts" / "provider_components",
                failed_component="frontend",
            )

            self.assertEqual("ray-2", diagnostics["provider_headers"]["cf-ray"])
            self.assertEqual("req-2", diagnostics["provider_headers"]["x-request-id"])
            self.assertTrue(diagnostics["pending_repair_plan_path"].endswith("pending_repair_plan.json"))

    def test_transport_error_without_repair_plan_writes_unavailable_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            diagnostics = run_local_pipeline.write_provider_transport_blocked_failure(
                root / "run",
                root / "generated" / "project",
                "component frontend provider_api_request_failed after transport attempts: 3: provider_api_request_failed: HTTP 504: timeout [endpoint=https://api.gptsapi.net, retryable=true]",
                {},
                [],
                root / "run" / "artifacts" / "provider_components",
            )
            pending_path = root / "run" / "artifacts" / "pending_repair_plan.json"
            pending = run_local_pipeline.load_json(pending_path)

            self.assertNotEqual({}, pending)
            self.assertEqual("pending_repair_plan_unavailable", pending["status"])
            self.assertEqual("pending_repair_plan_unavailable", diagnostics["pending_repair_plan"]["status"])
            self.assertEqual(3, diagnostics["transport_attempts"])

    def test_resume_continues_file_level_frontend_repair_only(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project
        calls: list[tuple[str, list[str]]] = []
        pipeline = {"components": [{"id": "foundation"}, {"id": "backend"}, {"id": "frontend"}], "merge_policy": {"required_final_files": ["package.json", "backend/server.py", "src/app.js"]}}
        plan = run_local_pipeline.compile_repair_plan(
            ["component file conflict: src/app.js from foundation and frontend"],
            {"frontend": [{"path": "src/app.js", "content": "old\n"}, {"path": "src/helper.js", "content": "keep\n"}]},
            component_pipeline=pipeline,
        )
        plan["raw_user_goal"] = "做任务看板"

        def fake_component(**kwargs):
            calls.append((kwargs["component"]["id"], [action.get("path") for action in kwargs.get("repair_actions", [])]))
            return {
                "component_id": kwargs["component"]["id"],
                "files": [{"path": "src/app.js", "content": "fetch('/api/tasks')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_review(*args, **kwargs):
            return {"status": "pass", "issues": [], "review_summary": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            checkpoint_dir = root / "run" / "artifacts" / "provider_components"
            for component_id, files in (
                ("foundation", [{"path": "package.json", "content": "{}\n"}]),
                ("backend", [{"path": "backend/server.py", "content": "print('api')\n"}]),
                ("frontend", [{"path": "src/app.js", "content": "old\n"}, {"path": "src/helper.js", "content": "keep\n"}]),
            ):
                run_local_pipeline.write_provider_component_checkpoint(
                    checkpoint_dir,
                    component_id=component_id,
                    spec_hash=run_local_pipeline.provider_component_spec_hash("做任务看板", pipeline, {"id": component_id}),
                    status="pass",
                    raw_output="{}",
                    parsed_result={"component_id": component_id, "files": files, "quality_gate": {"status": "pass"}, "self_test": {"status": "pass"}},
                    files=files,
                    semantic_review={"status": "pass"},
                )
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline=pipeline,
                    repair_errors=[],
                    model="unused",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    initial_repair_plan=plan,
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review

            self.assertEqual("pass", result["status"])
            self.assertEqual([("frontend", ["src/app.js"])], calls)
            _, files_path = run_local_pipeline.provider_component_checkpoint_paths(checkpoint_dir, "frontend")
            files = run_local_pipeline.load_json(files_path)["files"]
            self.assertIn("src/helper.js", [item["path"] for item in files])

    def test_choose_provider_model_small_payload_uses_nano(self) -> None:
        route = run_local_pipeline.choose_provider_model(
            "component_generation",
            12000,
            "gpt-4.1",
            run_local_pipeline.ProviderModelRoutingPolicy(),
        )

        self.assertEqual("gpt-5.4-nano", route["selected_model"])

    def test_choose_provider_model_large_payload_uses_large_model(self) -> None:
        route = run_local_pipeline.choose_provider_model(
            "component_generation",
            45000,
            "gpt-5.4-nano",
            run_local_pipeline.ProviderModelRoutingPolicy(),
        )

        self.assertEqual("gpt-5.5", route["selected_model"])
        self.assertEqual("large_payload", route["model_routing_reason"])

    def test_transport_error_upgrades_model_without_consuming_semantic_attempt(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project
        original_fast = os.environ.get("CGKN_PROVIDER_RETRY_FAST")
        os.environ["CGKN_PROVIDER_RETRY_FAST"] = "1"
        calls: list[str] = []
        pipeline = {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}}
        pending = {
            "status": "pending",
            "raw_user_goal": "做任务看板",
            "provider_actions": [{"component": "frontend", "path": "src/app.js", "instruction": "fix frontend"}],
        }

        def fake_component(**kwargs):
            calls.append(kwargs["model"])
            if len(calls) == 1:
                raise RuntimeError("provider_api_request_failed: SSLV3_ALERT_BAD_RECORD_MAC [retryable=true]")
            return {
                "component_id": "frontend",
                "files": [{"path": "src/app.js", "content": "console.log('ok')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_review(*args, **kwargs):
            return {"status": "pass", "issues": [], "review_summary": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline=pipeline,
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    initial_repair_plan=pending,
                    routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review
                if original_fast is None:
                    os.environ.pop("CGKN_PROVIDER_RETRY_FAST", None)
                else:
                    os.environ["CGKN_PROVIDER_RETRY_FAST"] = original_fast

            self.assertEqual("pass", result["status"])
            self.assertEqual(["gpt-5.4-nano", "gpt-5.5"], calls)
            self.assertEqual([], result["attempted_repairs"])

    def test_provider_phase_log_records_selected_model(self) -> None:
        original_creds = run_local_pipeline.check_connectivity._resolve_api_credentials
        original_post = run_local_pipeline.check_connectivity._post_json
        original_extract = run_local_pipeline.check_connectivity._extract_text

        def fake_creds():
            return {"api_key": "sk-secret-test-key", "base_url": "https://example.test/v1"}

        def fake_post(endpoint, payload, token, timeout):
            self.assertEqual("gpt-5.5", payload["model"])
            self.assertEqual("sk-secret-test-key", token)
            return {"ok": True}, ""

        with tempfile.TemporaryDirectory() as temp_dir:
            phase_log = pathlib.Path(temp_dir) / "provider_phase_log.jsonl"
            run_local_pipeline.check_connectivity._resolve_api_credentials = fake_creds
            run_local_pipeline.check_connectivity._post_json = fake_post
            run_local_pipeline.check_connectivity._extract_text = lambda doc: "ok"
            try:
                text = run_local_pipeline.provider_text(
                    [{"role": "user", "content": "x" * 45000}],
                    "gpt-5.4-nano",
                    5,
                    max_attempts=1,
                    stage="semantic_repair",
                    component="frontend",
                    max_tokens=3000,
                    payload_mode="split_file",
                    phase_log_path=phase_log,
                    routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                )
            finally:
                run_local_pipeline.check_connectivity._resolve_api_credentials = original_creds
                run_local_pipeline.check_connectivity._post_json = original_post
                run_local_pipeline.check_connectivity._extract_text = original_extract

            self.assertEqual("ok", text)
            log_text = phase_log.read_text(encoding="utf-8")
            event = json.loads(log_text.strip().splitlines()[-1])
            self.assertEqual("provider_request", event["event"])
            self.assertEqual("gpt-5.4-nano", event["requested_model"])
            self.assertEqual("gpt-5.5", event["selected_model"])
            self.assertEqual("large_payload", event["model_routing_reason"])
            self.assertNotIn("sk-secret-test-key", log_text)

    def test_pending_repair_plan_preserves_model_route(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            context = run_local_pipeline.build_pending_repair_context(
                run_dir=root / "run",
                raw_user_goal="做任务看板",
                model="gpt-5.4-nano",
                base_url="https://api.example/v1",
                repair_plan={"affected_components": ["frontend"], "provider_actions": [{"component": "frontend", "path": "src/app.js"}]},
                failed_component="frontend",
                attempt=1,
                semantic_repair_attempts_used=0,
                transport_attempt=2,
                provider_prompt_path=str(root / "prompt.txt"),
                requested_model="gpt-5.4-nano",
                selected_model="gpt-5.5",
                model_routing_reason="transport_error_ssl_bad_record_mac",
                last_transport_error="SSLV3_ALERT_BAD_RECORD_MAC",
                next_retry_model="gpt-5.5",
            )

            self.assertEqual("gpt-5.4-nano", context["requested_model"])
            self.assertEqual("gpt-5.5", context["selected_model"])
            self.assertEqual("SSLV3_ALERT_BAD_RECORD_MAC", context["last_transport_error"])
            self.assertEqual("gpt-5.5", context["next_retry_model"])

    def test_resume_uses_next_retry_model_from_pending_plan(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_review = run_local_pipeline.provider_review_project
        calls: list[str] = []
        pipeline = {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}}
        pending = {
            "status": "pending",
            "raw_user_goal": "做任务看板",
            "last_transport_error": "SSLV3_ALERT_BAD_RECORD_MAC",
            "next_retry_model": "gpt-5.5",
            "provider_actions": [{"component": "frontend", "path": "src/app.js", "instruction": "fix"}],
        }

        def fake_component(**kwargs):
            calls.append(kwargs["model"])
            return {
                "component_id": "frontend",
                "files": [{"path": "src/app.js", "content": "console.log('resumed')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_review(*args, **kwargs):
            return {"status": "pass", "issues": [], "review_summary": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline=pipeline,
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=1,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    initial_repair_plan=pending,
                    routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_review_project = original_review

            self.assertEqual("pass", result["status"])
            self.assertEqual(["gpt-5.5"], calls)

    def test_disable_model_routing_preserves_single_model_behavior(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_split = os.environ.get("CGNK_SPLIT_FRONTEND_COMPONENT")
        calls: list[str] = []

        def fake_component(**kwargs):
            calls.append(kwargs["model"])
            component_id = kwargs["component"]["id"]
            return {
                "component_id": component_id,
                "files": [{"path": f"{component_id}.py", "content": "print('ok')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        policy = run_local_pipeline.ProviderModelRoutingPolicy(enable_model_routing=False)
        os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = "0"
        run_local_pipeline.provider_generate_project_component = fake_component
        try:
            result = run_local_pipeline.provider_generate_project_by_components(
                "build a project",
                {"components": [{"id": "frontend"}, {"id": "backend"}], "merge_policy": {"required_final_files": ["frontend.py", "backend.py"]}},
                {},
                {},
                {},
                {},
                [],
                "gpt-custom",
                30,
                routing_policy=policy,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original_component
            if original_split is None:
                os.environ.pop("CGNK_SPLIT_FRONTEND_COMPONENT", None)
            else:
                os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = original_split

        self.assertEqual(2, len(result["files"]))
        self.assertEqual(["gpt-custom", "gpt-custom"], calls)

    def test_component_generation_over_hard_limit_uses_split_before_provider_call(self) -> None:
        original_provider_text = run_local_pipeline.provider_text
        calls: list[dict[str, object]] = []

        def fake_provider_text(messages, model, timeout, **kwargs):
            calls.append({"stage": kwargs.get("stage"), "payload_mode": kwargs.get("payload_mode"), "prompt_chars": sum(len(m.get("content", "")) for m in messages)})
            if kwargs.get("stage") == "component_file_manifest":
                return json.dumps({"component": "frontend", "files": [{"path": "src/app.js", "purpose": "task board UI"}]})
            return json.dumps({"path": kwargs.get("target_file"), "content": "export function boot(){ return 'task-board'; }\n"})

        run_local_pipeline.provider_text = fake_provider_text
        try:
            result = run_local_pipeline.provider_generate_project_by_components(
                "做任务看板",
                {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                {"pipeline_plan": {"payload": {"huge": "x" * 150000}}},
                {},
                {},
                {},
                [],
                "gpt-5.4-nano",
                30,
            )
        finally:
            run_local_pipeline.provider_text = original_provider_text

        self.assertEqual(["src/app.js"], [item["path"] for item in result["files"]])
        self.assertNotIn("component_generation", [call["stage"] for call in calls])
        self.assertIn("component_file_manifest", [call["stage"] for call in calls])
        self.assertIn("component_file_generation", [call["stage"] for call in calls])

    def test_frontend_component_uses_split_by_default(self) -> None:
        original_provider_text = run_local_pipeline.provider_text
        calls: list[str] = []

        def fake_provider_text(messages, model, timeout, **kwargs):
            calls.append(str(kwargs.get("stage")))
            if kwargs.get("stage") == "component_file_manifest":
                return json.dumps({"component": "frontend", "files": [{"path": "src/app.js", "purpose": "UI"}]})
            return json.dumps({"path": "src/app.js", "content": "export const status = 'ready';\n"})

        run_local_pipeline.provider_text = fake_provider_text
        try:
            run_local_pipeline.provider_generate_project_by_components(
                "做任务看板",
                {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                {},
                {},
                {},
                {},
                [],
                "gpt-5.4-nano",
                30,
            )
        finally:
            run_local_pipeline.provider_text = original_provider_text

        self.assertEqual(["component_file_manifest", "component_file_generation"], calls)

    def test_component_file_manifest_prompt_is_small(self) -> None:
        original_provider_text = run_local_pipeline.provider_text
        manifest_prompt_chars: list[int] = []

        def fake_provider_text(messages, model, timeout, **kwargs):
            if kwargs.get("stage") == "component_file_manifest":
                text = "\n".join(message.get("content", "") for message in messages)
                manifest_prompt_chars.append(len(text))
                self.assertNotIn("x" * 1000, text)
                return json.dumps({"component": "frontend", "files": [{"path": "src/app.js", "purpose": "UI"}]})
            return json.dumps({"path": "src/app.js", "content": "export const ok = true;\n"})

        run_local_pipeline.provider_text = fake_provider_text
        try:
            run_local_pipeline.provider_generate_project_by_components(
                "做任务看板",
                {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                {"pipeline_plan": {"payload": {"huge": "x" * 150000}}},
                {},
                {},
                {},
                [],
                "gpt-5.4-nano",
                30,
            )
        finally:
            run_local_pipeline.provider_text = original_provider_text

        self.assertTrue(manifest_prompt_chars)
        self.assertLess(manifest_prompt_chars[0], 20000)

    def test_per_file_generation_requests_exactly_one_file(self) -> None:
        original_provider_text = run_local_pipeline.provider_text

        def fake_provider_text(messages, model, timeout, **kwargs):
            prompt = "\n".join(message.get("content", "") for message in messages)
            self.assertEqual("component_file_generation", kwargs.get("stage"))
            self.assertEqual("src/app.js", kwargs.get("target_file"))
            self.assertIn("Generate exactly one file", prompt)
            self.assertIn("The only allowed path is src/app.js", prompt)
            return json.dumps({"path": "src/app.js", "content": "export const app = 'one-file';\n"})

        run_local_pipeline.provider_text = fake_provider_text
        try:
            item, _raw = run_local_pipeline.provider_generate_component_file(
                goal="做任务看板",
                component={"id": "frontend"},
                component_pipeline={"components": [{"id": "frontend"}]},
                manifest_entry={"path": "src/app.js", "purpose": "main UI"},
                prior_manifest=[],
                completed_files=[],
                repair_errors=[],
                model="gpt-5.4-nano",
                timeout=30,
                phase_log_path="",
                routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
            )
        finally:
            run_local_pipeline.provider_text = original_provider_text

        self.assertEqual("src/app.js", item["path"])

    def test_split_file_checkpoint_and_resume(self) -> None:
        original_provider_text = run_local_pipeline.provider_text
        original_attempts = os.environ.get("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS")
        os.environ["CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS"] = "1"
        calls: list[str] = []

        def failing_provider_text(messages, model, timeout, **kwargs):
            calls.append(str(kwargs.get("stage")))
            if kwargs.get("stage") == "component_file_manifest":
                return json.dumps({"component": "frontend", "files": [{"path": "src/app.js", "purpose": "UI"}, {"path": "src/styles.css", "purpose": "styles"}]})
            if kwargs.get("target_file") == "src/app.js":
                raise RuntimeError("provider_api_request_failed: HTTP 504: timeout [retryable=true]")
            return json.dumps({"path": kwargs.get("target_file"), "content": "body { color: #111; }\n"})

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_text = failing_provider_text
            try:
                with self.assertRaises(RuntimeError):
                    run_local_pipeline.provider_generate_project_component_split(
                        goal="做任务看板",
                        component={"id": "frontend"},
                        component_pipeline={"components": [{"id": "frontend"}]},
                        prior_manifest=[],
                        repair_errors=[],
                        model="gpt-5.4-nano",
                        timeout=30,
                        deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                        checkpoint_dir=root / "run" / "artifacts" / "provider_components",
                        run_dir=root / "run",
                        spec_hash="spec",
                        phase_log_path=root / "run" / "provider_phase_log.jsonl",
                        routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                        split_reason="test",
                        original_prompt_chars=150000,
                    )
                pending = run_local_pipeline.load_json(root / "run" / "artifacts" / "pending_repair_plan.json")
                self.assertEqual("component_file_generation", pending["stage"])
                self.assertEqual("src/app.js", pending["target_file"])
                self.assertEqual([], pending["completed_files"])
                self.assertIn("src/app.js", pending["remaining_files"])

                def resume_provider_text(messages, model, timeout, **kwargs):
                    calls.append(str(kwargs.get("stage")))
                    self.assertNotEqual("component_file_manifest", kwargs.get("stage"))
                    if kwargs.get("target_file") == "src/app.js":
                        return json.dumps({"path": "src/app.js", "content": "export const resumed = true;\n"})
                    return json.dumps({"path": "src/styles.css", "content": "body { color: #111; }\n"})

                run_local_pipeline.provider_text = resume_provider_text
                result = run_local_pipeline.provider_generate_project_component_split(
                    goal="做任务看板",
                    component={"id": "frontend"},
                    component_pipeline={"components": [{"id": "frontend"}]},
                    prior_manifest=[],
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    checkpoint_dir=root / "run" / "artifacts" / "provider_components",
                    run_dir=root / "run",
                    spec_hash="spec",
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                    split_reason="pending_component_file_generation",
                    original_prompt_chars=150000,
                    pending_context=pending,
                )
            finally:
                run_local_pipeline.provider_text = original_provider_text
                if original_attempts is None:
                    os.environ.pop("CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS", None)
                else:
                    os.environ["CGNK_PROVIDER_REPAIR_TRANSPORT_ATTEMPTS"] = original_attempts

            self.assertEqual(["src/app.js", "src/styles.css"], [item["path"] for item in result["files"]])

    def test_split_file_ownership_validation_blocks_wrong_path(self) -> None:
        original_provider_text = run_local_pipeline.provider_text

        def fake_provider_text(messages, model, timeout, **kwargs):
            return json.dumps({"path": "backend/server.py", "content": "print('wrong owner')\n"})

        run_local_pipeline.provider_text = fake_provider_text
        try:
            with self.assertRaisesRegex(RuntimeError, "wrong path|ownership violation"):
                run_local_pipeline.provider_generate_component_file(
                    goal="做任务看板",
                    component={"id": "frontend"},
                    component_pipeline={"components": [{"id": "frontend"}]},
                    manifest_entry={"path": "src/app.js", "purpose": "main UI"},
                    prior_manifest=[],
                    completed_files=[],
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    phase_log_path="",
                    routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                )
        finally:
            run_local_pipeline.provider_text = original_provider_text

    def test_provider_phase_log_never_records_oversized_component_request(self) -> None:
        original_provider_text = run_local_pipeline.provider_text

        def fake_provider_text(messages, model, timeout, **kwargs):
            run_local_pipeline.append_provider_event_log(
                phase_log,
                {
                    "event": "provider_request",
                    "stage": kwargs.get("stage"),
                    "component": kwargs.get("component"),
                    "target_file": kwargs.get("target_file", ""),
                    "payload_mode": kwargs.get("payload_mode"),
                    "prompt_chars": sum(len(message.get("content", "")) for message in messages),
                    "selected_model": model,
                },
            )
            if kwargs.get("stage") == "component_file_manifest":
                return json.dumps({"component": "frontend", "files": [{"path": "src/app.js", "purpose": "UI"}]})
            return json.dumps({"path": "src/app.js", "content": "export const safe = true;\n"})

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            phase_log = root / "provider_phase_log.jsonl"
            run_local_pipeline.provider_text = fake_provider_text
            try:
                run_local_pipeline.provider_generate_project_by_components(
                    "做任务看板",
                    {"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                    {"pipeline_plan": {"payload": {"huge": "x" * 150000}}},
                    {},
                    {},
                    {},
                    [],
                    "gpt-5.4-nano",
                    30,
                    run_dir=root,
                )
            finally:
                run_local_pipeline.provider_text = original_provider_text

            events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            oversized = [
                event
                for event in events
                if event.get("event") == "provider_request"
                and event.get("stage") == "component_generation"
                and event.get("payload_mode") == "component"
                and int(event.get("prompt_chars") or 0) > 40000
            ]
            self.assertEqual([], oversized)
            self.assertTrue(any(event.get("event") == "component_generation_split_started" for event in events))

    def test_completed_split_component_enters_semantic_review(self) -> None:
        original_provider_text = run_local_pipeline.provider_text
        original_review = run_local_pipeline.provider_review_project
        review_called = {"value": False}

        def fake_provider_text(messages, model, timeout, **kwargs):
            if kwargs.get("stage") == "component_file_manifest":
                return json.dumps({"component": "frontend", "files": [{"path": "src/app.js", "purpose": "UI"}]})
            return json.dumps({"path": "src/app.js", "content": "export const app = 'ready';\n"})

        def fake_review(*args, **kwargs):
            review_called["value"] = True
            files = {item["path"]: item["content"] for item in args[6]}
            self.assertIn("src/app.js", files)
            return {"status": "pass", "issues": [], "review_summary": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_text = fake_provider_text
            run_local_pipeline.provider_review_project = fake_review
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=1,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_text = original_provider_text
                run_local_pipeline.provider_review_project = original_review

            self.assertEqual("pass", result["status"])
            self.assertTrue(review_called["value"])

    def test_oversized_semantic_review_uses_split_pipeline(self) -> None:
        original_provider_text = run_local_pipeline.provider_text
        calls: list[tuple[str, int]] = []

        def fake_provider_text(messages, model, timeout, **kwargs):
            prompt_chars = sum(len(message.get("content", "")) for message in messages)
            calls.append((str(kwargs.get("stage")), prompt_chars))
            self.assertFalse(kwargs.get("stage") == "semantic_review" and prompt_chars > 40000)
            if kwargs.get("stage") == "semantic_component_review":
                return json.dumps({"component": kwargs.get("component"), "verdict": "pass", "blockers": [], "summary": "ok"})
            if kwargs.get("stage") == "semantic_cross_component_review":
                return json.dumps({"component": "cross_component", "verdict": "pass", "blockers": [], "integration_failures": [], "repair_targets": []})
            return json.dumps({"verdict": "pass", "blockers": [], "affected_components": [], "affected_files": [], "repair_priority": []})

        files = [
            {"path": f"src/file{i}.js", "content": "x" * 10000}
            for i in range(8)
        ]
        run_local_pipeline.provider_text = fake_provider_text
        try:
            review = run_local_pipeline.provider_review_project(
                "做任务看板",
                {},
                {},
                {},
                {},
                {"component_pipeline": {"components": [{"id": "frontend"}]}},
                files,
                "gpt-5.4-nano",
                30,
            )
        finally:
            run_local_pipeline.provider_text = original_provider_text

        self.assertEqual("pass", review["status"])
        self.assertNotIn("semantic_review", [stage for stage, _chars in calls])
        self.assertIn("semantic_component_review", [stage for stage, _chars in calls])
        self.assertIn("semantic_cross_component_review", [stage for stage, _chars in calls])
        self.assertIn("semantic_final_reducer", [stage for stage, _chars in calls])

    def test_component_self_review_prompt_under_budget(self) -> None:
        payload = run_local_pipeline.semantic_component_review_payload(
            goal="做任务看板",
            component_id="frontend",
            component_files=[
                {"path": f"src/file{i}.js", "content": f"export const v{i} = '{'x' * 10000}';\n"}
                for i in range(8)
            ],
            component_pipeline={"components": [{"id": "frontend"}]},
        )
        prompt = json.dumps(payload, ensure_ascii=False)

        self.assertLess(len(prompt), 20000)
        self.assertLessEqual(len(payload["selected_file_contents"]), 3)
        self.assertTrue(payload["semantic_review_budget_applied"])

    def test_cross_component_review_uses_summaries_not_full_source(self) -> None:
        sentinel = "FULL_SOURCE_SENTINEL_" * 1000
        payload = run_local_pipeline.semantic_cross_review_payload(
            goal="做任务看板",
            files=[{"path": "src/app.js", "content": sentinel}, {"path": "server/index.js", "content": sentinel}],
            component_reviews=[{"component": "frontend", "verdict": "pass", "summary": "frontend ok", "blockers": []}],
            component_pipeline={"components": [{"id": "frontend"}, {"id": "backend"}]},
        )
        raw = json.dumps(payload, ensure_ascii=False)

        self.assertNotIn(sentinel, raw)
        self.assertIn("file_manifest", payload)
        self.assertIn("component_review_summaries", payload)

    def test_final_reducer_uses_review_json_not_full_files(self) -> None:
        original_provider_text = run_local_pipeline.provider_text

        def fake_provider_text(messages, model, timeout, **kwargs):
            prompt = "\n".join(message.get("content", "") for message in messages)
            self.assertEqual("semantic_final_reducer", kwargs.get("stage"))
            self.assertIn("component_reviews", prompt)
            self.assertNotIn("function hugeSource", prompt)
            return json.dumps({"verdict": "fail", "blockers": [{"kind": "missing_entry_html", "component": "frontend", "files": ["index.html"], "message": "missing entry", "repair_hint": "add index"}]})

        run_local_pipeline.provider_text = fake_provider_text
        try:
            doc = run_local_pipeline.provider_semantic_final_reducer(
                component_reviews=[{"component": "frontend", "summary": "review summary only"}],
                cross_review={"component": "cross_component", "blockers": []},
                model="gpt-5.4-nano",
                timeout=30,
                phase_log_path="",
                routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
            )
        finally:
            run_local_pipeline.provider_text = original_provider_text

        self.assertEqual("fail", doc["verdict"])
        self.assertEqual("missing_entry_html", doc["blockers"][0]["kind"])

    def test_structured_blockers_compile_to_repair_plan(self) -> None:
        blockers = [
            {"kind": "missing_entry_html", "component": "frontend", "files": ["index.html"], "message": "missing entry HTML", "repair_hint": "generate index.html"},
            {"kind": "frontend_backend_mismatch", "files": ["src/app.js", "server/index.js"], "message": "status mismatch", "repair_hint": "align status enum"},
            {"kind": "inaccurate_test_report_claims", "component": "docs", "files": ["TEST_REPORT.md"], "message": "claims tests passed", "repair_hint": "remove false claims"},
        ]
        plan = run_local_pipeline.compile_repair_plan(
            blockers,
            {},
            component_pipeline={"components": [{"id": "frontend"}, {"id": "backend"}, {"id": "docs"}]},
        )

        actions = {(item["component"], item["path"]) for item in plan["provider_actions"]}
        self.assertIn(("frontend", "index.html"), actions)
        self.assertIn(("frontend", "src/app.js"), actions)
        self.assertIn(("backend", "server/index.js"), actions)
        self.assertIn(("docs", "TEST_REPORT.md"), actions)

    def test_fake_zip_blocker_routes_to_docs_or_media_not_packager_delivery(self) -> None:
        plan = run_local_pipeline.compile_repair_plan(
            [{"kind": "fake_artifact_claim", "files": ["scripts/bundle.js", "TEST_REPORT.md"], "message": "fake zip behavior", "repair_hint": "remove fake zip claim"}],
            {},
            component_pipeline={"components": [{"id": "docs"}, {"id": "media"}]},
        )
        components = {item["component"] for item in plan["provider_actions"]}
        text = json.dumps(plan, ensure_ascii=False).lower()

        self.assertTrue(components <= {"docs", "media"})
        self.assertNotIn("local_packager", text)
        self.assertNotIn("delivery", components)

    def test_semantic_review_log_records_split_and_budget(self) -> None:
        original_provider_text = run_local_pipeline.provider_text

        def fake_provider_text(messages, model, timeout, **kwargs):
            run_local_pipeline.append_provider_event_log(
                phase_log,
                {
                    "event": "provider_request",
                    "stage": kwargs.get("stage"),
                    "component": kwargs.get("component", ""),
                    "prompt_chars": sum(len(message.get("content", "")) for message in messages),
                    "payload_mode": kwargs.get("payload_mode"),
                    "selected_model": model,
                },
            )
            if kwargs.get("stage") == "semantic_component_review":
                return json.dumps({"component": kwargs.get("component"), "verdict": "pass", "blockers": [], "summary": "ok"})
            if kwargs.get("stage") == "semantic_cross_component_review":
                return json.dumps({"component": "cross_component", "verdict": "pass", "blockers": [], "integration_failures": [], "repair_targets": []})
            return json.dumps({"verdict": "pass", "blockers": [], "affected_components": [], "affected_files": []})

        with tempfile.TemporaryDirectory() as temp_dir:
            phase_log = pathlib.Path(temp_dir) / "provider_phase_log.jsonl"
            run_local_pipeline.provider_text = fake_provider_text
            try:
                run_local_pipeline.provider_review_project(
                    "做任务看板",
                    {},
                    {},
                    {},
                    {},
                    {"component_pipeline": {"components": [{"id": "frontend"}]}},
                    [
                        {"path": f"src/file{i}.js", "content": "x" * 10000}
                        for i in range(8)
                    ],
                    "gpt-5.4-nano",
                    30,
                    phase_log_path=phase_log,
                )
            finally:
                run_local_pipeline.provider_text = original_provider_text

            events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertTrue(any(event.get("event") == "semantic_review_split_started" for event in events))
            oversized = [event for event in events if event.get("stage") == "semantic_review" and int(event.get("prompt_chars") or 0) > 40000]
            self.assertEqual([], oversized)

    def test_split_semantic_review_repair_loop_rechecks_after_repair(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_provider_text = run_local_pipeline.provider_text
        original_split = os.environ.get("CGNK_SPLIT_FRONTEND_COMPONENT")
        os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = "0"
        state = {"review_calls": 0}

        def fake_component(**kwargs):
            repairs = "\n".join(kwargs.get("repair_errors", []))
            content = ("<div>fixed</div>\n" if "index.html" in repairs else "export const app = 'missing html';\n") + ("x" * 10000)
            return {
                "component_id": "frontend",
                "files": (
                    [{"path": "src/app.js", "content": content}]
                    + [{"path": f"src/file{i}.js", "content": content} for i in range(8)]
                    + [{"path": "index.html", "content": content}]
                ),
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_provider_text(messages, model, timeout, **kwargs):
            if kwargs.get("stage") == "semantic_component_review":
                return json.dumps({"component": kwargs.get("component"), "verdict": "pass", "blockers": [], "summary": "ok"})
            if kwargs.get("stage") == "semantic_cross_component_review":
                state["review_calls"] += 1
                if state["review_calls"] == 1:
                    return json.dumps({"component": "cross_component", "verdict": "fail", "blockers": [{"kind": "missing_entry_html", "component": "frontend", "files": ["index.html"], "message": "missing entry HTML", "repair_hint": "generate index.html"}], "integration_failures": [], "repair_targets": ["frontend"]})
                return json.dumps({"component": "cross_component", "verdict": "pass", "blockers": [], "integration_failures": [], "repair_targets": []})
            if kwargs.get("stage") == "semantic_final_reducer":
                if state["review_calls"] == 1:
                    return json.dumps({"verdict": "fail", "blockers": [{"kind": "missing_entry_html", "component": "frontend", "files": ["index.html"], "message": "missing entry HTML", "repair_hint": "generate index.html"}], "affected_components": ["frontend"], "affected_files": ["index.html"]})
                return json.dumps({"verdict": "pass", "blockers": [], "affected_components": [], "affected_files": []})
            raise AssertionError(f"unexpected provider stage {kwargs.get('stage')}")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_text = fake_provider_text
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js", "index.html"]}},
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_text = original_provider_text
                if original_split is None:
                    os.environ.pop("CGNK_SPLIT_FRONTEND_COMPONENT", None)
                else:
                    os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = original_split

            self.assertEqual("pass", result["status"])
            self.assertGreaterEqual(state["review_calls"], 2)

    def test_split_semantic_review_transport_block_writes_pending_route(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_provider_text = run_local_pipeline.provider_text
        original_split = os.environ.get("CGNK_SPLIT_FRONTEND_COMPONENT")
        os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = "0"

        def fake_component(**kwargs):
            content = "export const app = true;\n" + ("x" * 10000)
            return {
                "component_id": "frontend",
                "files": (
                    [{"path": "src/app.js", "content": content}]
                    + [{"path": f"src/file{i}.js", "content": content} for i in range(8)]
                ),
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_provider_text(messages, model, timeout, **kwargs):
            run_local_pipeline.append_provider_event_log(
                kwargs.get("phase_log_path"),
                {
                    "event": "provider_request",
                    "stage": kwargs.get("stage"),
                    "component": kwargs.get("component", ""),
                    "prompt_chars": sum(len(message.get("content", "")) for message in messages),
                    "requested_model": model,
                    "selected_model": "gpt-5.4-nano",
                    "model_routing_reason": "small_payload",
                    "payload_mode": kwargs.get("payload_mode"),
                },
            )
            raise RuntimeError("provider_api_request_failed: SSLV3_ALERT_BAD_RECORD_MAC [retryable=true]")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_text = fake_provider_text
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                    routing_policy=run_local_pipeline.ProviderModelRoutingPolicy(),
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_text = original_provider_text
                if original_split is None:
                    os.environ.pop("CGNK_SPLIT_FRONTEND_COMPONENT", None)
                else:
                    os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = original_split

            pending = run_local_pipeline.load_json(root / "run" / "artifacts" / "pending_repair_plan.json")
            self.assertEqual("blocked", result["status"])
            self.assertEqual(0, result["diagnostics"]["semantic_repair_attempts"])
            self.assertEqual("semantic_component_review", pending["stage"])
            self.assertEqual("gpt-5.4-nano", pending["selected_model"])
            self.assertEqual("gpt-5.5", pending["next_retry_model"])
            self.assertEqual("review_component", pending["payload_mode"])

    def test_non_json_semantic_review_preserves_files_for_candidate(self) -> None:
        original_component = run_local_pipeline.provider_generate_project_component
        original_provider_text = run_local_pipeline.provider_text
        original_split = os.environ.get("CGNK_SPLIT_FRONTEND_COMPONENT")
        os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = "0"

        def fake_component(**kwargs):
            return {
                "component_id": "frontend",
                "files": [{"path": "src/app.js", "content": "export const app = true;\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass"},
            }

        def fake_provider_text(messages, model, timeout, **kwargs):
            return "not json"

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            run_local_pipeline.provider_generate_project_component = fake_component
            run_local_pipeline.provider_text = fake_provider_text
            try:
                result = run_local_pipeline.run_provider_semantic_review_with_repair(
                    user_goal="做任务看板",
                    plan_doc={},
                    blueprint={},
                    online_inputs={},
                    market_research={},
                    component_pipeline={"components": [{"id": "frontend"}], "merge_policy": {"required_final_files": ["src/app.js"]}},
                    repair_errors=[],
                    model="gpt-5.4-nano",
                    timeout=30,
                    internal_context="",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    run_dir=root / "run",
                    out_dir=root / "generated" / "project",
                    result_path=root / "result.json",
                    max_repair_attempts=2,
                    phase_log_path=root / "run" / "provider_phase_log.jsonl",
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original_component
                run_local_pipeline.provider_text = original_provider_text
                if original_split is None:
                    os.environ.pop("CGNK_SPLIT_FRONTEND_COMPONENT", None)
                else:
                    os.environ["CGNK_SPLIT_FRONTEND_COMPONENT"] = original_split

            self.assertEqual("blocked", result["status"])
            self.assertEqual([], result["attempted_repairs"])
            self.assertEqual("src/app.js", result["files"][0]["path"])
            classes = run_local_pipeline.classify_semantic_blockers(result["provider_review"])
            self.assertEqual([], classes["fatal_fact_blocker"])
            self.assertEqual("provider_review_format_error", classes["warning"][0]["kind"])

    def test_semantic_review_quality_blockers_do_not_prevent_candidate_materialization(self) -> None:
        original_compose = run_local_pipeline.compose_local_pipeline.compose
        original_blueprint = run_local_pipeline.requirement_blueprint.build_requirement_blueprint
        original_online = run_local_pipeline.online_input_agent.collect_online_inputs
        original_market = run_local_pipeline.market_research_agent.run_market_research
        original_semantic = run_local_pipeline.run_provider_semantic_review_with_repair
        original_examples = run_local_pipeline.make_example_outputs
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize

        def fake_semantic(**kwargs):
            return {
                "status": "blocked",
                "generation": {"summary": "candidate"},
                "files": [{"path": "README.md", "content": "# Candidate\n"}, {"path": "src/app.js", "content": "console.log('candidate')\n"}],
                "provider_review": {"status": "fail", "issues": [{"kind": "frontend_backend_mismatch", "message": "status mismatch"}]},
                "attempted_repairs": [],
                "diagnostics": {"stage": "provider_semantic_review"},
            }

        try:
            run_local_pipeline.compose_local_pipeline.compose = lambda *args, **kwargs: {"original_requirement": args[0], "pipeline_plan": {"payload": {}}}
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = lambda *args, **kwargs: {}
            run_local_pipeline.online_input_agent.collect_online_inputs = lambda *args, **kwargs: {}
            run_local_pipeline.market_research_agent.run_market_research = lambda *args, **kwargs: {}
            run_local_pipeline.run_provider_semantic_review_with_repair = fake_semantic
            run_local_pipeline.make_example_outputs = lambda *args, **kwargs: {"status": "skipped"}
            run_local_pipeline.run_candidate_post_build_finalize = lambda **kwargs: {"status": "pass", "screenshots": ["shot.png"], "known_limits": [], "diagnostic_package": "candidate_diagnostic_bundle.zip"}
            with tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                original_test_root = os.environ.get("CGNK_TEST_GENERATED_ROOT")
                os.environ["CGNK_TEST_GENERATED_ROOT"] = str(root / "generated")
                try:
                    result = run_local_pipeline.execute(
                        type(
                            "Args",
                            (),
                            {
                                "resume_run_dir": "",
                                "run_dir": str(root / "run"),
                                "out_dir": str(root / "generated" / "project"),
                                "result": str(root / "result.json"),
                                "plan": "",
                                "goal": "做任务看板",
                                "use_api": True,
                                "allow_network": True,
                                "allow_provider": True,
                                "model": "unused",
                                "small_model": "",
                                "large_model": "",
                                "disable_model_routing": False,
                                "timeout": 30,
                                "provider_semantic_repair_attempts": 1,
                                "phase_log_path": "",
                                "allow_model_usage_planning": False,
                            },
                        )()
                    )
                finally:
                    if original_test_root is None:
                        os.environ.pop("CGNK_TEST_GENERATED_ROOT", None)
                    else:
                        os.environ["CGNK_TEST_GENERATED_ROOT"] = original_test_root
        finally:
            run_local_pipeline.compose_local_pipeline.compose = original_compose
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = original_blueprint
            run_local_pipeline.online_input_agent.collect_online_inputs = original_online
            run_local_pipeline.market_research_agent.run_market_research = original_market
            run_local_pipeline.run_provider_semantic_review_with_repair = original_semantic
            run_local_pipeline.make_example_outputs = original_examples
            run_local_pipeline.run_candidate_post_build_finalize = original_finalize

        self.assertTrue(result["candidate_materialized"])
        self.assertEqual("ASK_USER_REVIEW", result["final_verdict"])
        self.assertEqual("needs_rework", result["semantic_review_status"])
        self.assertTrue(result["candidate_only"])
        self.assertNotEqual(str(run_local_pipeline.DEFAULT_CANDIDATE_DIR), result["candidate_project_dir"])

    def test_runtime_blockers_do_not_prevent_candidate_materialization(self) -> None:
        original_compose = run_local_pipeline.compose_local_pipeline.compose
        original_blueprint = run_local_pipeline.requirement_blueprint.build_requirement_blueprint
        original_online = run_local_pipeline.online_input_agent.collect_online_inputs
        original_market = run_local_pipeline.market_research_agent.run_market_research
        original_semantic = run_local_pipeline.run_provider_semantic_review_with_repair
        original_examples = run_local_pipeline.make_example_outputs
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize

        def fake_semantic(**kwargs):
            return {
                "status": "blocked",
                "generation": {"summary": "candidate"},
                "files": [
                    {"path": "README.md", "content": "# Candidate\n"},
                    {"path": "package.json", "content": json.dumps({"scripts": {"test": "node missing-test.js"}})},
                    {"path": "src/app.js", "content": "console.log('candidate')\n"},
                ],
                "provider_review": {"status": "fail", "issues": [{"kind": "missing_backend_deps", "message": "missing express runtime dependency"}]},
                "attempted_repairs": [],
                "diagnostics": {"stage": "provider_semantic_review"},
            }

        try:
            run_local_pipeline.compose_local_pipeline.compose = lambda *args, **kwargs: {"original_requirement": args[0], "pipeline_plan": {"payload": {}}}
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = lambda *args, **kwargs: {}
            run_local_pipeline.online_input_agent.collect_online_inputs = lambda *args, **kwargs: {}
            run_local_pipeline.market_research_agent.run_market_research = lambda *args, **kwargs: {}
            run_local_pipeline.run_provider_semantic_review_with_repair = fake_semantic
            run_local_pipeline.make_example_outputs = lambda *args, **kwargs: {"status": "skipped"}
            run_local_pipeline.run_candidate_post_build_finalize = lambda **kwargs: {"status": "needs_rework", "screenshots": [], "known_limits": ["runtime missing"], "diagnostic_package": "candidate_diagnostic_bundle.zip"}
            with tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                original_test_root = os.environ.get("CGNK_TEST_GENERATED_ROOT")
                os.environ["CGNK_TEST_GENERATED_ROOT"] = str(root / "generated")
                try:
                    result = run_local_pipeline.execute(
                        type(
                            "Args",
                            (),
                            {
                                "resume_run_dir": "",
                                "run_dir": str(root / "run"),
                                "out_dir": str(root / "generated" / "project"),
                                "result": str(root / "result.json"),
                                "plan": "",
                                "goal": "做任务看板",
                                "use_api": True,
                                "allow_network": True,
                                "allow_provider": True,
                                "model": "unused",
                                "small_model": "",
                                "large_model": "",
                                "disable_model_routing": False,
                                "timeout": 30,
                                "provider_semantic_repair_attempts": 1,
                                "phase_log_path": "",
                                "allow_model_usage_planning": False,
                            },
                        )()
                    )
                finally:
                    if original_test_root is None:
                        os.environ.pop("CGNK_TEST_GENERATED_ROOT", None)
                    else:
                        os.environ["CGNK_TEST_GENERATED_ROOT"] = original_test_root
        finally:
            run_local_pipeline.compose_local_pipeline.compose = original_compose
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = original_blueprint
            run_local_pipeline.online_input_agent.collect_online_inputs = original_online
            run_local_pipeline.market_research_agent.run_market_research = original_market
            run_local_pipeline.run_provider_semantic_review_with_repair = original_semantic
            run_local_pipeline.make_example_outputs = original_examples
            run_local_pipeline.run_candidate_post_build_finalize = original_finalize

        self.assertTrue(result["candidate_materialized"])
        self.assertTrue(result["runtime_blockers"])
        self.assertEqual([], result["fatal_fact_blockers"])
        self.assertEqual("NEEDS_REWORK", result["final_verdict"])
        self.assertEqual("", result["final_project_bundle"])
        self.assertEqual("", result["delivery_manifest"])

    def test_fatal_unsafe_path_still_blocks_candidate(self) -> None:
        blockers = run_local_pipeline.detect_provider_hard_fact_blockers(
            [{"path": "../escape.js", "content": "console.log('escape')\n"}]
        )
        verdict = run_local_pipeline.decide_adaptive_final_verdict(
            candidate_materialized=False,
            hard_fact_blockers=blockers,
            runtime_blockers=[],
            quality_blockers=[],
            warnings=[],
            post_build={},
            final_delivery_allowed=False,
            final_bundle_exists=False,
            delivery_manifest_exists=False,
        )

        self.assertEqual("FACT_BLOCKED", verdict)
        self.assertTrue(any("unsafe path" in item for item in blockers))

    def test_candidate_project_cannot_be_public_delivered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            run_local_pipeline.write_json(project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json", {"candidate_only": True})
            (project / "README.md").write_text("# Candidate\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "candidate-only"):
                local_packager.package_project(project)

    def test_candidate_project_can_run_post_build_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "test_candidate_post_build"
            run_dir = root / "run"
            project.mkdir(parents=True)
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(0)\""}}), encoding="utf-8")
            (project / "README.md").write_text("# Candidate\n", encoding="utf-8")
            result = run_local_pipeline.run_candidate_post_build_finalize(
                project_dir=project,
                run_dir=run_dir,
                user_goal="做任务看板",
                generated_files=["package.json", "README.md"],
                online_inputs={},
                example_outputs={"status": "skipped"},
                model="unused",
                timeout=30,
                phase_log_path=run_dir / "provider_phase_log.jsonl",
                deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
            )

            self.assertTrue((project / "TEST_REPORT.md").exists())
            self.assertTrue((project / "DELIVERY_NOTES.md").exists())
            self.assertTrue((run_dir / "artifacts" / "candidate_diagnostic_bundle.zip").exists())
            self.assertFalse((project / "final_project_bundle.zip").exists())
            self.assertIn(result["status"], {"pass", "needs_rework"})

    def test_focused_pytest_does_not_delete_formal_candidate_dir(self) -> None:
        formal = run_local_pipeline.DEFAULT_CANDIDATE_DIR
        existed_before = formal.exists()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            out_dir = root / "generated" / "project"
            candidate = run_local_pipeline.candidate_project_dir_for(out_dir)
            candidate.mkdir(parents=True)
            (candidate / "sentinel.txt").write_text("owned by focused test\n", encoding="utf-8")
            shutil.rmtree(candidate)

        self.assertEqual(existed_before, formal.exists())

    def test_cleanup_only_removes_isolated_tmp_dirs(self) -> None:
        formal = run_local_pipeline.DEFAULT_CANDIDATE_DIR
        existed_before = formal.exists()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            candidate = make_temp_candidate_project(root)
            self.assertTrue(candidate.exists())
            shutil.rmtree(candidate)
            self.assertFalse(candidate.exists())

        self.assertEqual(existed_before, formal.exists())

    def test_candidate_project_dir_default_is_not_used_by_unit_tests(self) -> None:
        original = os.environ.get("CGNK_TEST_GENERATED_ROOT")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                generated = pathlib.Path(temp_dir) / "generated"
                os.environ["CGNK_TEST_GENERATED_ROOT"] = str(generated)
                candidate = run_local_pipeline.candidate_project_dir_for(generated / "cgnk_generated_project")

            self.assertNotEqual(run_local_pipeline.DEFAULT_CANDIDATE_DIR.resolve(), candidate.resolve())
            self.assertTrue(str(candidate).startswith(str(generated)))
        finally:
            if original is None:
                os.environ.pop("CGNK_TEST_GENERATED_ROOT", None)
            else:
                os.environ["CGNK_TEST_GENERATED_ROOT"] = original

    def test_run_candidate_smoke_benchmark_read_only_on_existing_candidate(self) -> None:
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = make_temp_candidate_project(root)
            sentinel = project / "sentinel.txt"
            sentinel.write_text("keep\n", encoding="utf-8")

            def fake_finalize(**kwargs):
                return {
                    "test_result": {"status": "pass", "returncode": 0},
                    "ui_smoke": {"status": "pass"},
                    "screenshots": [],
                    "video": "",
                    "artifact_integrity": {"status": "pass", "issues": []},
                    "candidate_review_ready": False,
                }

            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            try:
                report = run_candidate_smoke_benchmark.run_benchmark(project, root / "run")
            finally:
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

            self.assertTrue(sentinel.exists())
            self.assertFalse((project / "final_project_bundle.zip").exists())
            self.assertFalse((project / "delivery_manifest.json").exists())
            self.assertEqual("NEEDS_REWORK", report["verdict"])

    def test_candidate_screenshot_generated_after_tests_pass(self) -> None:
        original_capture = run_local_pipeline.capture_candidate_screenshot
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(0)\""}}), encoding="utf-8")
            (project / "README.md").write_text("# Candidate\n", encoding="utf-8")

            def fake_capture(project_dir, run_dir, timeout=60):
                screenshot = project_dir / "artifacts" / "screenshots" / "candidate_home.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(tiny_nonblank_png())
                return {"status": "pass", "screenshots": [str(screenshot)], "screenshot_blocked": "", "attempts": []}

            run_local_pipeline.capture_candidate_screenshot = fake_capture
            try:
                result = run_local_pipeline.run_candidate_post_build_finalize(
                    project_dir=project,
                    run_dir=run_dir,
                    user_goal="task board",
                    generated_files=["package.json", "README.md"],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
                )
            finally:
                run_local_pipeline.capture_candidate_screenshot = original_capture

            self.assertEqual("pass", result["status"])
            self.assertTrue(result["screenshots"])
            self.assertTrue(run_local_pipeline.real_image_file(pathlib.Path(result["screenshots"][0])))

    def test_screenshot_blocked_written_when_browser_unavailable(self) -> None:
        original_capture = run_local_pipeline.capture_candidate_screenshot
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(0)\""}}), encoding="utf-8")

            def fake_capture(project_dir, run_dir, timeout=60):
                blocked = run_local_pipeline.write_screenshot_blocked(project_dir, "playwright unavailable", failure_type="browser_unavailable")
                return {"status": "blocked", "screenshots": [], "screenshot_blocked": blocked, "attempts": []}

            run_local_pipeline.capture_candidate_screenshot = fake_capture
            try:
                result = run_local_pipeline.run_candidate_post_build_finalize(
                    project_dir=project,
                    run_dir=run_dir,
                    user_goal="task board",
                    generated_files=["package.json"],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
                )
            finally:
                run_local_pipeline.capture_candidate_screenshot = original_capture

            blocked_doc = json.loads((project / "screenshot_blocked.json").read_text(encoding="utf-8"))

        self.assertEqual("needs_rework", result["status"])
        self.assertEqual([], result["screenshots"])
        self.assertEqual("browser_unavailable", blocked_doc["failure_type"])
        self.assertTrue(result["candidate_review_ready"])

    def test_candidate_review_summary_created_for_ask_user_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            blocked = run_local_pipeline.write_screenshot_blocked(project, "browser unavailable", failure_type="browser_unavailable")
            summary = run_local_pipeline.write_candidate_review_summary(
                project,
                verdict="ASK_USER_REVIEW",
                test_status="pass",
                screenshots=[],
                video_blocked=blocked,
                known_limits=["video blocked"],
            )
            verdict = run_local_pipeline.decide_adaptive_final_verdict(
                candidate_materialized=True,
                hard_fact_blockers=[],
                runtime_blockers=[],
                quality_blockers=[],
                warnings=[],
                post_build={"status": "needs_rework", "candidate_review_ready": True, "test_result": {"status": "pass"}, "screenshots": []},
                final_delivery_allowed=False,
                final_bundle_exists=False,
                delivery_manifest_exists=False,
            )
            doc = json.loads(pathlib.Path(summary).read_text(encoding="utf-8"))

        self.assertEqual("ASK_USER_REVIEW", verdict)
        self.assertEqual("ASK_USER_REVIEW", doc["verdict"])
        self.assertFalse(doc["final_delivery"])
        self.assertIn("delivery_manifest.json not generated", doc["warnings"])

    def test_candidate_diagnostic_bundle_contains_screenshot_or_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            project.mkdir()
            blocked = run_local_pipeline.write_screenshot_blocked(project, "browser unavailable", failure_type="browser_unavailable")
            run_local_pipeline.write_candidate_review_summary(
                project,
                verdict="ASK_USER_REVIEW",
                test_status="pass",
                screenshots=[],
                video_blocked=blocked,
                known_limits=[],
            )
            run_local_pipeline.write_json(project / "known_limits.json", {"known_limits": []})
            run_local_pipeline.write_json(project / "repair_plan.json", {"stage": "post_build_repair"})
            invalid_shot = project / "artifacts" / "screenshots" / "blank.png"
            invalid_shot.parent.mkdir(parents=True)
            invalid_shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
            run_local_pipeline.write_json(run_dir / "artifacts" / "candidate_post_build_finalize.json", {"status": "needs_rework"})

            bundle = run_local_pipeline.create_candidate_diagnostic_package(project, run_dir)
            with zipfile.ZipFile(bundle) as zf:
                names = set(zf.namelist())

        self.assertIn("screenshot_blocked.json", names)
        self.assertIn("candidate_review_summary.json", names)
        self.assertIn("known_limits.json", names)
        self.assertIn("repair_plan.json", names)
        self.assertIn("_run_artifacts/candidate_post_build_finalize.json", names)
        self.assertNotIn("artifacts/screenshots/blank.png", names)

    def test_ask_user_review_does_not_generate_delivery_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            run_local_pipeline.write_candidate_review_summary(
                project,
                verdict="ASK_USER_REVIEW",
                test_status="pass",
                screenshots=[],
                video_blocked="",
                known_limits=[],
            )

            self.assertFalse((project / "delivery_manifest.json").exists())
            self.assertFalse((project / "final_project_bundle.zip").exists())

    def test_screenshot_failure_can_trigger_post_build_repair_if_app_startup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(0)\"", "start": "node server.js"}}), encoding="utf-8")
            (project / "server.js").write_text("throw new Error('startup failed')\n", encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "pass", "argv": ["npm", "test"]},
                "screenshots": [],
                "screenshot_capture": {"status": "blocked", "attempts": [{"reason": "startup URL did not become ready", "candidate": {"script": "start"}}]},
                "screenshot_blocked": str(project / "screenshot_blocked.json"),
            }

            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("screenshot_failure", plan["failure_types"])
        self.assertIn("startup_failure", plan["failure_types"])
        self.assertIn("screenshot_blocked_by_runtime", plan["root_causes"])
        self.assertTrue(plan["target_files"])

    def test_screenshot_blocked_contains_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            blocked = run_local_pipeline.write_screenshot_blocked(
                project,
                "captured screenshot was missing or invalid",
                failure_type="screenshot_failure",
                details={
                    "detected_entrypoint": "index.html",
                    "startup_command": "python -m http.server 1234",
                    "opened_url": "http://127.0.0.1:1234/index.html",
                    "browser_used": "chromium",
                    "browser_available": True,
                    "page_title": "Task Board",
                    "body_text_length": 0,
                    "body_text_sample": "",
                    "console_errors": ["boom"],
                    "network_errors": ["missing.js"],
                    "screenshot_attempted": True,
                    "failure_reason": "page_blank",
                },
            )
            doc = json.loads(pathlib.Path(blocked).read_text(encoding="utf-8"))

        for key in ("opened_url", "startup_command", "browser_used", "body_text_length", "failure_reason"):
            self.assertIn(key, doc)
        self.assertEqual("http://127.0.0.1:1234/index.html", doc["opened_url"])
        self.assertEqual("page_blank", doc["failure_reason"])
        self.assertEqual(["boom"], doc["console_errors"])
        self.assertEqual(["missing.js"], doc["network_errors"])

    def test_blank_screenshot_records_page_blank_or_invalid_screenshot(self) -> None:
        opened_urls: list[str] = []
        old_modules = install_fake_playwright(tiny_blank_png(), body_text="", title="", opened_urls=opened_urls)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                project = pathlib.Path(temp_dir) / "candidate"
                project.mkdir()
                (project / "index.html").write_text("<!doctype html><body></body>\n", encoding="utf-8")
                result = run_local_pipeline.capture_candidate_screenshot(project, pathlib.Path(temp_dir) / "run", timeout=10)
                doc = json.loads((project / "screenshot_blocked.json").read_text(encoding="utf-8"))
        finally:
            restore_fake_playwright(old_modules)

        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["screenshots"])
        self.assertIn(doc["failure_reason"], {"page_blank", "invalid_screenshot"})
        self.assertTrue(doc["is_blank_or_invalid"])
        self.assertGreaterEqual(doc["blank_score"], 0.9)

    def test_browser_unavailable_does_not_trigger_provider_code_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "index.html").write_text("<!doctype html><body>Task Board</body>\n", encoding="utf-8")
            blocked = run_local_pipeline.write_screenshot_blocked(
                project,
                "playwright unavailable",
                failure_type="browser_unavailable",
                details={"failure_reason": "browser_unavailable", "browser_available": False},
            )
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "pass", "argv": ["npm", "test"]},
                "screenshots": [],
                "screenshot_blocked": blocked,
                "screenshot_capture": {"status": "blocked", "screenshot_blocked": blocked, "failure_reason": "browser_unavailable"},
            }
            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("browser_unavailable", plan["failure_types"])
        self.assertEqual([], plan["provider_actions"])
        self.assertEqual("no_actionable_file_repair", plan["status"])

    def test_startup_failed_can_trigger_screenshot_repair_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"start": "node server.js", "test": "node -e \"process.exit(0)\""}}), encoding="utf-8")
            (project / "server.js").write_text("throw new Error('startup failed')\n", encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "pass", "argv": ["npm", "test"]},
                "screenshots": [],
                "screenshot_capture": {"status": "blocked", "failure_reason": "startup_failed", "attempts": [{"reason": "startup URL did not become ready"}]},
                "screenshot_blocked": str(project / "screenshot_blocked.json"),
            }
            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("startup_failure", plan["failure_types"])
        self.assertTrue(plan["target_files"])
        self.assertTrue(plan["provider_actions"] or plan["deterministic_actions"])

    def test_static_html_uses_local_http_server_for_screenshot(self) -> None:
        opened_urls: list[str] = []
        body_text = "Task Board New Task Todo Doing Done Add Task Review task workflow and local JSON persistence"
        old_modules = install_fake_playwright(tiny_nonblank_png(), body_text=body_text, title="Task Board", opened_urls=opened_urls)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                project = pathlib.Path(temp_dir) / "candidate"
                project.mkdir()
                (project / "index.html").write_text("<!doctype html><body>Task Board</body>\n", encoding="utf-8")
                result = run_local_pipeline.capture_candidate_screenshot(project, pathlib.Path(temp_dir) / "run", timeout=10)
        finally:
            restore_fake_playwright(old_modules)

        self.assertEqual("pass", result["status"])
        self.assertTrue(opened_urls)
        self.assertTrue(opened_urls[0].startswith("http://127.0.0.1:"))
        self.assertNotIn("file://", opened_urls[0])

    def test_candidate_review_summary_mentions_screenshot_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            blocked = run_local_pipeline.write_screenshot_blocked(project, "blank page", failure_type="screenshot_failure", details={"failure_reason": "page_blank"})
            summary = run_local_pipeline.write_candidate_review_summary(
                project,
                verdict="ASK_USER_REVIEW",
                test_status="pass",
                screenshots=[],
                video_blocked="",
                known_limits=[f"screenshot_blocked: see {pathlib.Path(blocked).name}"],
            )
            doc = json.loads(pathlib.Path(summary).read_text(encoding="utf-8"))

        self.assertEqual("ASK_USER_REVIEW", doc["verdict"])
        self.assertFalse(doc["final_delivery"])
        self.assertTrue(any("screenshot_blocked" in item for item in doc["warnings"]))
        self.assertNotEqual("PASS_FINAL", doc["verdict"])

    def test_page_blank_routes_to_frontend_entry_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            (project / "src").mkdir(parents=True)
            (project / "scripts" / "util").mkdir(parents=True)
            (project / "index.html").write_text("<!doctype html><title>Task Board</title><div id=\"root\"></div>", encoding="utf-8")
            (project / "src" / "app.js").write_text("document.querySelector('#app')\n", encoding="utf-8")
            (project / "src" / "main.js").write_text("export const ok = true\n", encoding="utf-8")
            (project / "scripts" / "util" / "buildAll.js").write_text("console.log('build')\n", encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "pass", "argv": ["npm", "test"]},
                "screenshots": [],
                "screenshot_capture": {
                    "status": "blocked",
                    "failure_reason": "page_blank",
                    "attempts": [{"reason": "failure_reason=page_blank body_text_length=0 blank_score=1.0 index.html"}],
                },
                "screenshot_blocked": str(project / "screenshot_blocked.json"),
            }

            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("page_blank", plan["failure_types"])
        self.assertIn("index.html loads but body has no visible content", plan["root_causes"])
        self.assertIn("index.html", plan["target_files"])
        self.assertIn("src/app.js", plan["target_files"])
        self.assertIn("scripts/util/buildAll.js", plan["target_files"])

    def test_page_blank_repair_requires_visible_body_text(self) -> None:
        repaired_html = """
        <!doctype html>
        <html><body>
          <main>
            <h1>Task Board</h1>
            <button>Add Task</button>
            <section><h2>Todo</h2><p>New Task waiting for review.</p></section>
            <section><h2>Doing</h2><p>Screenshot repair is in progress.</p></section>
            <section><h2>Done</h2><p>npm test remains pass.</p></section>
          </main>
        </body></html>
        """
        visible_text = re.sub(r"<[^>]+>", " ", repaired_html)
        visible_text = re.sub(r"\s+", " ", visible_text)

        self.assertGreater(len(visible_text), 50)
        for token in ("Task Board", "Todo", "Doing", "Done"):
            self.assertIn(token, visible_text)

    def test_blank_page_screenshot_not_accepted_even_if_png_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            blank = pathlib.Path(temp_dir) / "blank.png"
            blank.write_bytes(tiny_blank_png())

            self.assertFalse(run_local_pipeline.real_image_file(blank))
            diag = run_local_pipeline.image_file_diagnostics(blank)

        self.assertEqual(1.0, diag["blank_score"])
        self.assertTrue(diag["is_blank_or_invalid"])

    def test_ui_smoke_check_runs_before_accepting_screenshot(self) -> None:
        opened_urls: list[str] = []
        old_modules = install_fake_playwright(tiny_nonblank_png(), body_text="", title="Task Board", opened_urls=opened_urls)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                project = pathlib.Path(temp_dir) / "candidate"
                project.mkdir()
                (project / "index.html").write_text("<!doctype html><title>Task Board</title><body><canvas></canvas></body>\n", encoding="utf-8")
                result = run_local_pipeline.capture_candidate_screenshot(project, pathlib.Path(temp_dir) / "run", timeout=10)
                doc = json.loads((project / "screenshot_blocked.json").read_text(encoding="utf-8"))
        finally:
            restore_fake_playwright(old_modules)

        self.assertEqual("blocked", result["status"])
        self.assertEqual([], result["screenshots"])
        self.assertEqual("page_blank", doc["failure_reason"])
        self.assertEqual(0, doc["body_text_length"])

    def test_page_blank_repair_does_not_generate_final_manifest_or_zip(self) -> None:
        project = ROOT / "generated" / "cgnk_generated_project_candidate"

        self.assertFalse((project / "final_project_bundle.zip").exists())
        self.assertFalse((project / "delivery_manifest.json").exists())

    def test_check_test_environment_reports_node_npm_browser_ffmpeg(self) -> None:
        report = check_test_environment.check_environment(ROOT / "generated" / "test_env_candidate")

        self.assertIn(report["status"], {"pass", "warn", "fail"})
        self.assertIn("path", report["node"])
        self.assertIn("path", report["npm"])
        self.assertIn("playwright_available", report["browser"])
        self.assertIn("available", report["ffmpeg"])

    def test_missing_node_is_environment_failure_not_project_failure(self) -> None:
        original = check_test_environment.shutil.which

        def fake_which(name):
            if name in {"node", "npm"}:
                return None
            return original(name)

        check_test_environment.shutil.which = fake_which
        try:
            report = check_test_environment.check_environment(ROOT / "generated" / "test_env_candidate")
        finally:
            check_test_environment.shutil.which = original

        self.assertEqual("fail", report["status"])
        self.assertIn("node unavailable", report["failures"])
        self.assertIn("npm unavailable", report["failures"])

    def test_missing_browser_writes_screenshot_blocked_without_provider_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            blocked = run_local_pipeline.write_screenshot_blocked(
                project,
                "playwright unavailable",
                failure_type="browser_unavailable",
                details={"failure_reason": "browser_unavailable", "browser_available": False},
            )
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "pass"},
                "screenshots": [],
                "screenshot_blocked": blocked,
                "screenshot_capture": {"status": "blocked", "failure_reason": "browser_unavailable"},
            }
            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertEqual([], plan["provider_actions"])
        self.assertIn("browser_unavailable", plan["failure_types"])

    def test_ui_smoke_requires_visible_task_board_text(self) -> None:
        fail = run_local_pipeline.candidate_ui_smoke({"page_title": "Task Board", "body_text_length": 0, "body_text_sample": "", "console_errors": [], "network_errors": []})
        ok = run_local_pipeline.candidate_ui_smoke({"page_title": "Task Board", "body_text_length": 120, "body_text_sample": "Task Board Add Task Todo Doing Done", "console_errors": [], "network_errors": []})

        self.assertEqual("fail", fail["status"])
        self.assertEqual("pass", ok["status"])
        self.assertIn("Todo", ok["keywords_found"])

    def test_valid_screenshot_requires_non_blank_image_and_body_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = pathlib.Path(temp_dir) / "shot.png"
            path.write_bytes(tiny_nonblank_png())
            diag = run_local_pipeline.image_file_diagnostics(path)
            smoke = run_local_pipeline.candidate_ui_smoke({"page_title": "Task Board", "body_text_length": 120, "body_text_sample": "Task Board Add Task Todo Doing Done", "console_errors": [], "network_errors": []})
            is_real = run_local_pipeline.real_image_file(path)

        self.assertTrue(is_real)
        self.assertFalse(diag["is_blank_or_invalid"])
        self.assertGreaterEqual(diag["image_width"], 640)
        self.assertEqual("pass", smoke["status"])

    def test_video_blocked_contains_ffmpeg_and_browser_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            blocked = run_local_pipeline.write_video_blocked(project, "no video", failure_reason="ffmpeg_unavailable", environment={"ffmpeg": "", "playwright": "available"}, browser_used="chromium")
            doc = json.loads(pathlib.Path(blocked).read_text(encoding="utf-8"))

        self.assertEqual("ffmpeg_unavailable", doc["failure_reason"])
        self.assertIn("ffmpeg_path", doc)
        self.assertTrue(doc["playwright_available"])
        self.assertEqual("chromium", doc["browser_used"])

    def test_candidate_artifact_integrity_rejects_final_manifest_inside_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            project.mkdir()
            for name in ("candidate_review_summary.json", "known_limits.json", "repair_plan.json"):
                (project / name).write_text("{}", encoding="utf-8")
            (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
            (project / "DELIVERY_NOTES.md").write_text("candidate_only: true\n", encoding="utf-8")
            (project / "screenshot_blocked.json").write_text("{}", encoding="utf-8")
            (project / "video_blocked.json").write_text("{}", encoding="utf-8")
            bundle = run_dir / "artifacts" / "candidate_diagnostic_bundle.zip"
            bundle.parent.mkdir(parents=True)
            with zipfile.ZipFile(bundle, "w") as zf:
                zf.writestr("delivery_manifest.json", "{}")

            report = run_local_pipeline.validate_candidate_review_artifacts(project, run_dir)

        self.assertEqual("fail", report["status"])
        self.assertIn("bundle contains delivery_manifest.json", report["issues"])

    def test_candidate_artifact_integrity_requires_screenshot_or_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            project.mkdir()
            for name in ("candidate_review_summary.json", "known_limits.json", "repair_plan.json"):
                (project / name).write_text("{}", encoding="utf-8")
            (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
            (project / "DELIVERY_NOTES.md").write_text("candidate_only: true\n", encoding="utf-8")
            (project / "video_blocked.json").write_text("{}", encoding="utf-8")
            bundle = run_local_pipeline.create_candidate_diagnostic_package(project, run_dir)

            report = run_local_pipeline.validate_candidate_review_artifacts(project, run_dir)
            bundle_exists = bundle.exists()

        self.assertTrue(bundle_exists)
        self.assertEqual("fail", report["status"])
        self.assertIn("missing screenshot or screenshot_blocked", report["issues"])

    def test_candidate_smoke_benchmark_outputs_report(self) -> None:
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "node -e \"process.exit(0)\""}}), encoding="utf-8")

            def fake_finalize(**kwargs):
                run_dir = pathlib.Path(kwargs["run_dir"])
                run_dir.mkdir(parents=True, exist_ok=True)
                return {
                    "test_result": {"status": "pass", "returncode": 0},
                    "ui_smoke": {"status": "pass", "body_text_length": 120, "keywords_found": ["Task Board"]},
                    "screenshots": [str(project / "shot.png")],
                    "video": "",
                    "video_blocked": "",
                    "artifact_integrity": {"status": "pass", "issues": []},
                    "candidate_review_ready": True,
                }

            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            try:
                report = run_candidate_smoke_benchmark.run_benchmark(project, pathlib.Path(temp_dir) / "run")
            finally:
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

        self.assertEqual("ASK_USER_REVIEW", report["verdict"])
        self.assertEqual("pass", report["npm_test"]["status"])
        self.assertTrue(run_candidate_smoke_benchmark.DEFAULT_REPORT.exists())

    def test_candidate_smoke_benchmark_does_not_generate_final_zip_or_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            run_local_pipeline.write_json(project / "candidate_review_summary.json", {"verdict": "ASK_USER_REVIEW", "final_delivery": False})

            self.assertFalse((project / "final_project_bundle.zip").exists())
            self.assertFalse((project / "delivery_manifest.json").exists())

    def test_missing_zip_prevents_pass_final_but_allows_ask_user_review(self) -> None:
        verdict = run_local_pipeline.decide_adaptive_final_verdict(
            candidate_materialized=True,
            hard_fact_blockers=[],
            runtime_blockers=[],
            quality_blockers=[],
            warnings=[],
            post_build={"status": "pass"},
            final_delivery_allowed=False,
            final_bundle_exists=False,
            delivery_manifest_exists=False,
        )

        self.assertEqual("ASK_USER_REVIEW", verdict)

    def test_broken_runtime_becomes_needs_rework_not_fact_blocked(self) -> None:
        classes = run_local_pipeline.classify_semantic_blockers({"status": "fail", "issues": [{"kind": "missing_backend_deps", "message": "missing express"}]})
        verdict = run_local_pipeline.decide_adaptive_final_verdict(
            candidate_materialized=True,
            hard_fact_blockers=classes["hard_fact_blocker"],
            runtime_blockers=classes["runtime_blocker"],
            quality_blockers=[],
            warnings=[],
            post_build={"status": "needs_rework"},
            final_delivery_allowed=False,
            final_bundle_exists=False,
            delivery_manifest_exists=False,
        )

        self.assertEqual([], classes["hard_fact_blocker"])
        self.assertTrue(classes["runtime_blocker"])
        self.assertEqual("NEEDS_REWORK", verdict)

    def test_fake_zip_script_is_repairable_fact_blocker(self) -> None:
        blockers = run_local_pipeline.detect_provider_repairable_fact_blockers(
            [{"path": "scripts/bundle.js", "content": "writeFileSync('final_project_bundle.zip', JSON.stringify({placeholder: true}))\n"}]
        )
        hard = run_local_pipeline.detect_provider_hard_fact_blockers(
            [{"path": "scripts/bundle.js", "content": "writeFileSync('final_project_bundle.zip', JSON.stringify({placeholder: true}))\n"}]
        )

        self.assertTrue(any("fake final zip" in item for item in blockers))
        self.assertEqual([], hard)

    def test_sanitizer_removes_fake_zip_script_before_candidate_materialization(self) -> None:
        files = [
            {"path": "scripts/util/bundle.js", "content": "writeFileSync('final_project_bundle.zip', JSON.stringify({placeholder: true}))\n"},
            {"path": "README.md", "content": "Run bundle to create final_project_bundle.zip before review.\n"},
        ]

        result = run_local_pipeline.sanitize_candidate_files_before_materialization(files, ["fake final zip behavior claimed in scripts/util/bundle.js"])
        by_path = {item["path"]: item["content"] for item in result["files"]}

        self.assertEqual("pass", result["status"])
        self.assertIn("fake_final_bundle_script", result["sanitized_fact_blockers"])
        self.assertNotIn("final_project_bundle.zip", by_path["scripts/util/bundle.js"])
        self.assertIn("local_packager", by_path["README.md"])
        self.assertIn("known_limits.json", by_path)
        self.assertIn("repair_plan.json", by_path)

    def test_sanitized_candidate_cannot_pass_final(self) -> None:
        verdict = run_local_pipeline.decide_adaptive_final_verdict(
            candidate_materialized=True,
            hard_fact_blockers=[],
            runtime_blockers=[],
            quality_blockers=[],
            warnings=["sanitized_fake_delivery_claim"],
            post_build={"status": "pass", "sanitized_fact_blockers": ["fake_final_bundle_script"]},
            final_delivery_allowed=False,
            final_bundle_exists=False,
            delivery_manifest_exists=False,
        )

        self.assertNotEqual("PASS_FINAL", verdict)
        self.assertEqual("ASK_USER_REVIEW", verdict)

    def test_candidate_post_build_runs_after_repairable_fact_sanitizer(self) -> None:
        original_compose = run_local_pipeline.compose_local_pipeline.compose
        original_blueprint = run_local_pipeline.requirement_blueprint.build_requirement_blueprint
        original_online = run_local_pipeline.online_input_agent.collect_online_inputs
        original_market = run_local_pipeline.market_research_agent.run_market_research
        original_semantic = run_local_pipeline.run_provider_semantic_review_with_repair
        original_examples = run_local_pipeline.make_example_outputs
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        seen = {"post_build": False}

        def fake_semantic(**kwargs):
            return {
                "status": "blocked",
                "generation": {"summary": "candidate"},
                "files": [
                    {"path": "README.md", "content": "# Candidate\n"},
                    {"path": "scripts/util/bundle.js", "content": "writeFileSync('final_project_bundle.zip', JSON.stringify({placeholder: true}))\n"},
                ],
                "provider_review": {"status": "fail", "issues": [{"kind": "fake_artifact_claim", "message": "fake final_project_bundle.zip behavior"}]},
                "attempted_repairs": [],
                "diagnostics": {"stage": "provider_semantic_review"},
            }

        def fake_finalize(**kwargs):
            seen["post_build"] = True
            script = pathlib.Path(kwargs["project_dir"]) / "scripts" / "util" / "bundle.js"
            self.assertTrue(script.exists())
            self.assertNotIn("final_project_bundle.zip", script.read_text(encoding="utf-8"))
            self.assertTrue((pathlib.Path(kwargs["project_dir"]) / "known_limits.json").exists())
            self.assertTrue((pathlib.Path(kwargs["project_dir"]) / "repair_plan.json").exists())
            return {"status": "needs_rework", "screenshots": [], "known_limits": ["runtime broken"], "diagnostic_package": "candidate_diagnostic_bundle.zip"}

        try:
            run_local_pipeline.compose_local_pipeline.compose = lambda *args, **kwargs: {"original_requirement": args[0], "pipeline_plan": {"payload": {}}}
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = lambda *args, **kwargs: {}
            run_local_pipeline.online_input_agent.collect_online_inputs = lambda *args, **kwargs: {}
            run_local_pipeline.market_research_agent.run_market_research = lambda *args, **kwargs: {}
            run_local_pipeline.run_provider_semantic_review_with_repair = fake_semantic
            run_local_pipeline.make_example_outputs = lambda *args, **kwargs: {"status": "skipped"}
            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            with tempfile.TemporaryDirectory() as temp_dir:
                root = pathlib.Path(temp_dir)
                original_test_root = os.environ.get("CGNK_TEST_GENERATED_ROOT")
                os.environ["CGNK_TEST_GENERATED_ROOT"] = str(root / "generated")
                try:
                    result = run_local_pipeline.execute(
                        type(
                            "Args",
                            (),
                            {
                                "resume_run_dir": "",
                                "run_dir": str(root / "run"),
                                "out_dir": str(root / "generated" / "project"),
                                "result": str(root / "result.json"),
                                "plan": "",
                                "goal": "做任务看板",
                                "use_api": True,
                                "allow_network": True,
                                "allow_provider": True,
                                "model": "unused",
                                "small_model": "",
                                "large_model": "",
                                "disable_model_routing": False,
                                "timeout": 30,
                                "provider_semantic_repair_attempts": 1,
                                "phase_log_path": "",
                                "allow_model_usage_planning": False,
                            },
                        )()
                    )
                finally:
                    if original_test_root is None:
                        os.environ.pop("CGNK_TEST_GENERATED_ROOT", None)
                    else:
                        os.environ["CGNK_TEST_GENERATED_ROOT"] = original_test_root
        finally:
            run_local_pipeline.compose_local_pipeline.compose = original_compose
            run_local_pipeline.requirement_blueprint.build_requirement_blueprint = original_blueprint
            run_local_pipeline.online_input_agent.collect_online_inputs = original_online
            run_local_pipeline.market_research_agent.run_market_research = original_market
            run_local_pipeline.run_provider_semantic_review_with_repair = original_semantic
            run_local_pipeline.make_example_outputs = original_examples
            run_local_pipeline.run_candidate_post_build_finalize = original_finalize

        self.assertTrue(seen["post_build"])
        self.assertTrue(result["candidate_materialized"])
        self.assertIn("fake_final_bundle_script", result["sanitized_fact_blockers"])
        self.assertEqual("NEEDS_REWORK", result["final_verdict"])
        self.assertEqual("", result["delivery_manifest"])

    def test_candidate_post_build_failure_compiles_repair_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "node scripts/test.js"}}), encoding="utf-8")
            (project / "scripts").mkdir()
            (project / "scripts" / "test.js").write_text("throw new Error('old')\n", encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "failed", "argv": ["npm", "test"], "stderr_tail": "AssertionError in scripts/test.js expected Todo"},
                "screenshots": [],
                "known_limits": ["tests did not pass"],
            }

            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertEqual("post_build_repair", plan["stage"])
        self.assertIn("test_failure", plan["failure_types"])
        self.assertIn("screenshot_failure", plan["failure_types"])
        self.assertIn("scripts/test.js", plan["target_files"])
        self.assertTrue(plan["provider_actions"])

    def test_post_build_repair_targets_files_from_npm_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            (project / "scripts").mkdir(parents=True)
            (project / "scripts" / "test.js").write_text("console.log('test')\n", encoding="utf-8")
            (project / "src").mkdir()
            (project / "src" / "app.js").write_text("export const app = true\n", encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "failed", "argv": ["npm", "test"], "stderr_tail": "Error: failed at src/app.js\n    at scripts/test.js:2"},
                "screenshots": [],
            }

            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("src/app.js", plan["target_files"])
        self.assertIn("scripts/test.js", plan["target_files"])
        self.assertLessEqual(len(plan["target_files"]), 3)

    def test_missing_required_package_json_classified_specific(self) -> None:
        finalize = {"test_result": {"status": "failed", "stderr_tail": "[foundation:test] missing required file: package.json"}}
        failures = run_local_pipeline.classify_post_build_failures(finalize)

        self.assertIn("missing_package_json", failures)
        self.assertIn("dependency_failure", failures)
        self.assertIn("module_setup_failure", failures)

    def test_npm_enoent_package_json_classified_missing_package_json(self) -> None:
        finalize = {"test_result": {"status": "failed", "stderr_tail": "npm ERR! enoent Could not read package.json"}}
        failures = run_local_pipeline.classify_post_build_failures(finalize)

        self.assertIn("missing_package_json", failures)

    def test_missing_package_json_targets_package_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_temp_candidate_project(pathlib.Path(temp_dir))
            plan = run_local_pipeline.compile_post_build_repair_plan(
                project,
                {"test_result": {"status": "failed", "stderr_tail": "missing required file: package.json"}, "screenshots": []},
            )

        self.assertIn("missing_package_json", plan["failure_types"])
        self.assertIn("package.json", plan["target_files"])

    def test_missing_package_json_candidate_not_runnable_when_no_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            plan = run_local_pipeline.compile_post_build_repair_plan(
                project,
                {"test_result": {"status": "failed", "stderr_tail": "npm ERR! enoent package.json not found"}, "screenshots": []},
            )

        self.assertEqual("candidate_not_runnable", plan["status"])
        self.assertIn("candidate_not_runnable", plan["failure_types"])
        self.assertEqual([], plan["provider_actions"])

    def test_missing_package_json_can_generate_minimal_package_when_sources_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_temp_candidate_project(pathlib.Path(temp_dir))
            plan = run_local_pipeline.compile_post_build_repair_plan(
                project,
                {"test_result": {"status": "failed", "stderr_tail": "Could not read package.json"}, "screenshots": []},
            )
            result = run_local_pipeline.apply_deterministic_post_build_repair(project, plan)
            package_doc = json.loads((project / "package.json").read_text(encoding="utf-8"))

        self.assertIn("package.json", result["changed_files"])
        self.assertEqual("module", package_doc["type"])
        self.assertEqual("node scripts/test.js", package_doc["scripts"]["test"])
        self.assertEqual("python -m http.server 5173 --bind 127.0.0.1", package_doc["scripts"]["start"])

    def test_windows_esm_path_error_classified_as_module_system_failure(self) -> None:
        finalize = {
            "status": "needs_rework",
            "test_result": {
                "status": "failed",
                "stderr_tail": "ERR_UNSUPPORTED_ESM_URL_SCHEME Only URLs with a scheme in: file, data, and node are supported. Received protocol 'd:'",
            },
            "screenshots": [],
        }

        failures = run_local_pipeline.classify_post_build_failures(finalize)

        self.assertIn("module_system_failure", failures)
        self.assertIn("windows_esm_path_import", failures)

    def test_windows_esm_path_import_repair_adds_path_to_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = pathlib.Path(temp_dir) / "test.mjs"
            target.write_text(
                "\n".join(
                    [
                        'import path from "node:path";',
                        "const testFile = path.resolve('tests/api_contract_test.mjs');",
                        "await import(testFile);",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            changed = run_local_pipeline.repair_windows_esm_path_import_file(target)
            updated = target.read_text(encoding="utf-8")

        self.assertTrue(changed)
        self.assertIn('import { pathToFileURL } from "node:url";', updated)
        self.assertIn("await import(pathToFileURL(testFile).href);", updated)

    def test_windows_esm_path_import_repair_does_not_rewrite_node_or_relative_imports(self) -> None:
        source = "\n".join(
            [
                'await import("node:fs");',
                'await import("data:text/javascript,export default 1");',
                'await import("./relative.js");',
                'await import("../parent.js");',
                "",
            ]
        )

        updated, changed = run_local_pipeline.rewrite_windows_esm_dynamic_imports(source)

        self.assertFalse(changed)
        self.assertEqual(source, updated)

    def test_post_build_repair_prefers_deterministic_windows_esm_fix_before_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            (project / "scripts").mkdir(parents=True)
            (project / "tests").mkdir()
            (project / "scripts" / "run-tests.mjs").write_text("const testFile = 'D:/x/tests/api_contract_test.mjs';\nawait import(testFile);\n", encoding="utf-8")
            (project / "tests" / "api_contract_test.mjs").write_text("export default true;\n", encoding="utf-8")
            (project / "tests" / "smoke_test.mjs").write_text("export default true;\n", encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {
                    "status": "failed",
                    "argv": ["npm", "test"],
                    "stderr_tail": "ERR_UNSUPPORTED_ESM_URL_SCHEME Only URLs with a scheme in: file, data, and node are supported. Received protocol 'd:' at scripts/run-tests.mjs",
                },
                "screenshots": [],
            }

            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("windows_esm_path_import", plan["failure_types"])
        self.assertEqual([], plan["provider_actions"])
        self.assertTrue(any(action.get("action") == "repair_windows_esm_path_imports" for action in plan["deterministic_actions"]))
        self.assertIn("scripts/run-tests.mjs", plan["target_files"])

    def test_windows_esm_repair_reruns_npm_test(self) -> None:
        original_repair = run_local_pipeline.provider_post_build_file_repair
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        calls = {"finalize": 0, "provider": 0}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            (project / "scripts").mkdir(parents=True)
            (project / "tests").mkdir()
            (project / "scripts" / "run-tests.mjs").write_text("const testFile = 'D:/x/tests/api_contract_test.mjs';\nawait import(testFile);\n", encoding="utf-8")
            (project / "tests" / "api_contract_test.mjs").write_text("export default true;\n", encoding="utf-8")
            (project / "tests" / "smoke_test.mjs").write_text("export default true;\n", encoding="utf-8")

            def fake_repair(**kwargs):
                calls["provider"] += 1
                return {"status": "applied", "changed_files": []}

            def fake_finalize(**kwargs):
                calls["finalize"] += 1
                return {"status": "pass", "test_result": {"status": "pass", "argv": ["npm", "test"]}, "screenshots": ["shot.png"], "known_limits": []}

            run_local_pipeline.provider_post_build_file_repair = fake_repair
            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            try:
                result = run_local_pipeline.run_candidate_post_build_repair_loop(
                    candidate_dir=project,
                    run_dir=run_dir,
                    user_goal="修 Windows ESM import",
                    generated_files=["scripts/run-tests.mjs"],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
                    routing_policy=None,
                    initial_post_build={
                        "status": "needs_rework",
                        "test_result": {"status": "failed", "stderr_tail": "ERR_UNSUPPORTED_ESM_URL_SCHEME Received protocol 'd:' at scripts/run-tests.mjs"},
                        "screenshots": [],
                    },
                    max_attempts=1,
                )
            finally:
                run_local_pipeline.provider_post_build_file_repair = original_repair
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

            updated = (project / "scripts" / "run-tests.mjs").read_text(encoding="utf-8")

        self.assertEqual(1, calls["finalize"])
        self.assertEqual(0, calls["provider"])
        self.assertEqual("pass", result["status"])
        self.assertIn("pathToFileURL(testFile).href", updated)

    def test_vitest_not_recognized_classified_as_missing_test_runner(self) -> None:
        finalize = {
            "status": "needs_rework",
            "test_result": {
                "status": "failed",
                "stderr_tail": "'vitest' is not recognized as an internal or external command,\noperable program or batch file.",
            },
            "screenshots": [],
        }

        failures = run_local_pipeline.classify_post_build_failures(finalize)

        self.assertIn("dependency_failure", failures)
        self.assertIn("missing_test_runner", failures)
        self.assertIn("missing_vitest", failures)

    def test_missing_vitest_prefers_node_builtin_test_runner_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
            finalize = {
                "status": "needs_rework",
                "test_result": {"status": "failed", "argv": ["npm", "test"], "stderr_tail": "sh: vitest: command not found"},
                "screenshots": [],
            }

            plan = run_local_pipeline.compile_post_build_repair_plan(project, finalize)

        self.assertIn("missing_vitest", plan["failure_types"])
        self.assertEqual([], plan["provider_actions"])
        self.assertTrue(any(action.get("action") == "replace_missing_vitest_with_node_runner" for action in plan["deterministic_actions"]))

    def test_missing_vitest_repair_updates_package_json_test_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")

            changed = run_local_pipeline.repair_missing_vitest_with_node_runner(project)
            package_doc = json.loads((project / "package.json").read_text(encoding="utf-8"))

        self.assertIn("package.json", changed)
        self.assertIn("scripts/test.js", changed)
        self.assertEqual("node scripts/test.js", package_doc["scripts"]["test"])

    def test_missing_vitest_repair_reruns_npm_test(self) -> None:
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        calls = {"finalize": 0}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            project.mkdir()
            (project / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")

            def fake_finalize(**kwargs):
                calls["finalize"] += 1
                return {"status": "pass", "test_result": {"status": "pass", "argv": ["npm", "test"]}, "screenshots": ["shot.png"], "known_limits": []}

            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            try:
                result = run_local_pipeline.run_candidate_post_build_repair_loop(
                    candidate_dir=project,
                    run_dir=run_dir,
                    user_goal="修 vitest",
                    generated_files=["package.json"],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
                    routing_policy=None,
                    initial_post_build={
                        "status": "needs_rework",
                        "test_result": {"status": "failed", "stderr_tail": "'vitest' is not recognized"},
                        "screenshots": [],
                    },
                    max_attempts=1,
                )
            finally:
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

            package_doc = json.loads((project / "package.json").read_text(encoding="utf-8"))

        self.assertEqual(1, calls["finalize"])
        self.assertEqual("pass", result["status"])
        self.assertEqual("node scripts/test.js", package_doc["scripts"]["test"])

    def test_tests_not_passed_writes_screenshot_blocked_and_review_summary(self) -> None:
        import scripts.post_build_finalize as post_build_finalize_module

        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()

            def fake_finalize(**kwargs):
                return {
                    "status": "needs_rework",
                    "test_result": {"status": "failed", "argv": ["npm", "test"]},
                    "screenshots": [],
                    "known_limits": ["tests did not pass"],
                    "video_blocked": str(project / "video_blocked.json"),
                }

            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            try:
                result = post_build_finalize_module.run(
                    project_dir=project,
                    run_dir=pathlib.Path(temp_dir) / "run",
                    user_goal="demo",
                    generated_files=[],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=pathlib.Path(temp_dir) / "phase.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={},
                    routing_policy=None,
                )
            finally:
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

            self.assertEqual("needs_rework", result["status"])
            self.assertTrue((project / "screenshot_blocked.json").exists())
            self.assertTrue((project / "candidate_review_summary.json").exists())
            summary = json.loads((project / "candidate_review_summary.json").read_text(encoding="utf-8"))
            self.assertEqual("NEEDS_REWORK", summary["verdict"])
            self.assertFalse(summary["final_delivery"])

    def test_post_build_repair_does_not_generate_final_zip_or_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "candidate"
            project.mkdir()

            with self.assertRaisesRegex(RuntimeError, "binary artifact|non-target|fake delivery"):
                run_local_pipeline.validate_post_build_repair_files(
                    project,
                    [{"path": "final_project_bundle.zip", "content": "not real"}],
                    ["scripts/test.js"],
                )
            with self.assertRaisesRegex(RuntimeError, "non-target|fake delivery|final delivery"):
                run_local_pipeline.validate_post_build_repair_files(
                    project,
                    [{"path": "delivery_manifest.json", "content": "{}"}],
                    ["delivery_manifest.json"],
                )

    def test_post_build_repair_reruns_finalize(self) -> None:
        original_repair = run_local_pipeline.provider_post_build_file_repair
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        calls = {"finalize": 0}
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            (project / "scripts").mkdir(parents=True)
            (project / "scripts" / "test.js").write_text("throw new Error('old')\n", encoding="utf-8")

            def fake_repair(**kwargs):
                (project / "scripts" / "test.js").write_text("console.log('fixed')\n", encoding="utf-8")
                return {"status": "applied", "changed_files": ["scripts/test.js"]}

            def fake_finalize(**kwargs):
                calls["finalize"] += 1
                return {"status": "pass", "test_result": {"status": "pass", "argv": ["npm", "test"]}, "screenshots": ["shot.png"], "known_limits": []}

            run_local_pipeline.provider_post_build_file_repair = fake_repair
            run_local_pipeline.run_candidate_post_build_finalize = fake_finalize
            try:
                result = run_local_pipeline.run_candidate_post_build_repair_loop(
                    candidate_dir=project,
                    run_dir=run_dir,
                    user_goal="做任务看板",
                    generated_files=["scripts/test.js"],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
                    routing_policy=None,
                    initial_post_build={"status": "needs_rework", "test_result": {"status": "failed", "stderr_tail": "scripts/test.js AssertionError"}, "screenshots": []},
                    max_attempts=2,
                )
            finally:
                run_local_pipeline.provider_post_build_file_repair = original_repair
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

        self.assertEqual(1, calls["finalize"])
        self.assertEqual("pass", result["status"])
        self.assertEqual("scripts/test.js", result["post_build_repair_result"]["provider"]["changed_files"][0])

    def test_post_build_repair_can_advance_needs_rework_to_ask_user_review(self) -> None:
        verdict = run_local_pipeline.decide_adaptive_final_verdict(
            candidate_materialized=True,
            hard_fact_blockers=[],
            runtime_blockers=[],
            quality_blockers=[],
            warnings=[],
            post_build={"status": "needs_rework", "candidate_review_ready": True, "test_result": {"status": "pass"}, "screenshots": []},
            final_delivery_allowed=False,
            final_bundle_exists=False,
            delivery_manifest_exists=False,
        )

        self.assertEqual("ASK_USER_REVIEW", verdict)

    def test_post_build_repair_attempt_limit(self) -> None:
        original_repair = run_local_pipeline.provider_post_build_file_repair
        original_finalize = run_local_pipeline.run_candidate_post_build_finalize
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "candidate"
            run_dir = root / "run"
            (project / "scripts").mkdir(parents=True)
            (project / "scripts" / "test.js").write_text("throw new Error('old')\n", encoding="utf-8")

            run_local_pipeline.provider_post_build_file_repair = lambda **kwargs: {"status": "applied", "changed_files": ["scripts/test.js"]}
            run_local_pipeline.run_candidate_post_build_finalize = lambda **kwargs: {"status": "needs_rework", "test_result": {"status": "failed", "stderr_tail": "scripts/test.js still failing"}, "screenshots": []}
            try:
                result = run_local_pipeline.run_candidate_post_build_repair_loop(
                    candidate_dir=project,
                    run_dir=run_dir,
                    user_goal="做任务看板",
                    generated_files=["scripts/test.js"],
                    online_inputs={},
                    example_outputs={},
                    model="unused",
                    timeout=30,
                    phase_log_path=run_dir / "provider_phase_log.jsonl",
                    deadline=run_local_pipeline.ProgressDeadline(time.time() + 60, extension_seconds=60),
                    classifications={"fatal_fact_blocker": [], "repairable_fact_blocker": [], "hard_fact_blocker": [], "runtime_blocker": [], "quality_blocker": [], "warning": []},
                    routing_policy=None,
                    initial_post_build={"status": "needs_rework", "test_result": {"status": "failed", "stderr_tail": "scripts/test.js failing"}, "screenshots": []},
                    max_attempts=1,
                )
            finally:
                run_local_pipeline.provider_post_build_file_repair = original_repair
                run_local_pipeline.run_candidate_post_build_finalize = original_finalize

        self.assertEqual(1, len(result["post_build_repair_history"]))

    def test_video_blocked_is_warning_not_fact_blocker(self) -> None:
        classes = run_local_pipeline.classify_semantic_blockers({"status": "fail", "issues": ["video_blocked: demo video was not produced"]})

        self.assertEqual([], classes["fatal_fact_blocker"])
        self.assertEqual([], classes["repairable_fact_blocker"])
        self.assertEqual(1, len(classes["warning"]))

    def test_provider_generated_final_bundle_never_counts_as_packager_zip(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "binary artifact"):
            run_local_pipeline.validate_provider_files(
                {"files": [{"path": "final_project_bundle.zip", "content": "PK fake zip bytes"}]}
            )

    def test_candidate_files_recover_from_provider_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = pathlib.Path(temp_dir) / "run"
            checkpoint = run_dir / "artifacts" / "provider_components"
            checkpoint.mkdir(parents=True)
            run_local_pipeline.write_json(
                checkpoint / "frontend_files.json",
                {"component_id": "frontend", "files": [{"path": "src/app.js", "content": "console.log('ok')\n"}]},
            )

            files = run_local_pipeline.recover_candidate_files_from_checkpoints(run_dir, [])

        self.assertEqual([{"path": "src/app.js", "content": "console.log('ok')\n"}], files)

    def test_delivered_status_still_requires_actual_sent_artifacts(self) -> None:
        verdict = run_local_pipeline.decide_adaptive_final_verdict(
            candidate_materialized=True,
            hard_fact_blockers=[],
            runtime_blockers=[],
            quality_blockers=[],
            warnings=[],
            post_build={"status": "pass"},
            final_delivery_allowed=True,
            final_bundle_exists=False,
            delivery_manifest_exists=False,
        )

        self.assertNotEqual("PASS_FINAL", verdict)
        self.assertEqual("ASK_USER_REVIEW", verdict)

    def test_semantic_blockers_are_classified(self) -> None:
        classes = run_local_pipeline.classify_semantic_blockers(
            {
                "status": "fail",
                "issues": [
                    {"kind": "fake_artifact_claim", "message": "fake zip behavior"},
                    {"kind": "missing_entry_html", "message": "missing index.html"},
                    {"kind": "frontend_backend_mismatch", "message": "status mismatch"},
                    {"kind": "generic", "message": "limited UI polish"},
                ],
            }
        )

        self.assertEqual(0, len(classes["fatal_fact_blocker"]))
        self.assertEqual(1, len(classes["repairable_fact_blocker"]))
        self.assertEqual(1, len(classes["hard_fact_blocker"]))
        self.assertEqual(1, len(classes["runtime_blocker"]))
        self.assertEqual(1, len(classes["quality_blocker"]))
        self.assertEqual(1, len(classes["warning"]))


if __name__ == "__main__":
    unittest.main()
