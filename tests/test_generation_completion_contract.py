from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as backend_dialogue_loop
import scripts.check_connectivity as check_connectivity
import scripts.local_packager as local_packager
import scripts.run_local_pipeline as run_local_pipeline
import scripts.codex_conversation as bridge


class FakeCodexConversation:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, conversation_id: int | str, text: str) -> bool:
        self.messages.append((str(conversation_id), text))
        return True

    def send_chat_action(self, conversation_id: int | str, action: str) -> None:
        self.actions.append((str(conversation_id), action))


class CaptureThread:
    target = None

    def __init__(self, target, args=(), kwargs=None, daemon=None):
        type(self).target = target

    def start(self) -> None:
        return None


def valid_provider_doc() -> dict:
    return {
        "project_type": "local task board",
        "summary": "A runnable task board with persisted tasks.",
        "files": [
            {"path": "README.md", "content": "# Task Board\n\nRun `python app.py`.\n"},
            {"path": "TEST_PLAN.md", "content": "# Test Plan\n\n- `python -m pytest tests`\n"},
            {"path": "app.py", "content": "def main():\n    print('task board')\n\nif __name__ == '__main__':\n    main()\n"},
            {"path": "tests/test_app.py", "content": "def test_app():\n    assert True\n"},
        ],
    }


class GenerationCompletionContractTests(unittest.TestCase):
    def test_clear_project_requests_are_ready_to_generate(self) -> None:
        requests = (
            "帮我做一个本地网页工具，可以整理任务并导出 CSV",
            "帮我做一个视觉小说助手，可以编辑时间线并生成背景",
            "帮我做一个数据分析平台，可以导入 CSV 并生成图表报告",
        )
        for index, text in enumerate(requests):
            session = {"conversation_id": f"ready-{index}", "messages": [{"role": "user", "text": text}], "whiteboard": {}}
            analysis = backend_dialogue_loop.summarize_locally(session, text)
            self.assertTrue(analysis["ready_to_generate"], text)
            self.assertTrue(analysis["start_allowed_with_assumptions"], text)

    def test_codex_generation_starts_reviewed_provider_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            session = bridge.default_session("provider-start")
            session["messages"].append({"role": "user", "text": "做一个本地任务工具"})
            bridge.save_session(session_dir, session)
            original_thread = bridge.threading.Thread
            original_commit_sha = bridge.repository_commit_sha
            bridge.threading.Thread = CaptureThread
            bridge.repository_commit_sha = lambda: "0123456789abcdef0123456789abcdef01234567"
            try:
                bridge.start_agent_generation(
                    FakeCodexConversation(),
                    "provider-start",
                    session_dir,
                    log_dir,
                    "gpt-test",
                    30,
                    announce_start=False,
                )
            finally:
                bridge.threading.Thread = original_thread
                bridge.repository_commit_sha = original_commit_sha
            saved = bridge.load_session(session_dir, "provider-start")
            self.assertIs(CaptureThread.target, bridge.run_provider_generation_job)
            self.assertEqual("api_provider_project_generation", saved["generation"]["driver"])

    def test_simulator_entry_is_retired_and_unconfigured_session_cannot_deliver(self) -> None:
        self.assertFalse(hasattr(bridge,'run_simulator_preflight'))
        with tempfile.TemporaryDirectory() as temp_dir:
            root=pathlib.Path(temp_dir)
            with self.assertRaisesRegex(ValueError,'PROJECT_SESSION_PROFILE_REQUIRED'):
                bridge.run_formal_generation_once(root,goal='task board')
            self.assertFalse((root/'final_project_bundle.zip').exists())

    def test_provider_json_validates_and_writes_bounded_project(self) -> None:
        doc = valid_provider_doc()
        files = run_local_pipeline.validate_provider_files(doc)
        run_local_pipeline.validate_provider_project_contract(doc, files)
        generated_root = ROOT / "generated"
        generated_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=generated_root) as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            written = run_local_pipeline.write_provider_files(project, files)
            self.assertIn("README.md", written)
            self.assertTrue((project / "app.py").is_file())
            self.assertTrue((project / "TEST_PLAN.md").is_file())

    def test_provider_writes_only_exact_project_local_agent_kit_output(self) -> None:
        doc = valid_provider_doc()
        files = run_local_pipeline.validate_provider_files(doc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project_local = root / "project" / ".cgkn" / "agent-kit" / "generated-project"
            written = run_local_pipeline.write_provider_files(project_local, files)
            self.assertIn("README.md", written)
            self.assertTrue((project_local / "app.py").is_file())

            with self.assertRaisesRegex(RuntimeError, "outside generated root"):
                run_local_pipeline.write_provider_files(root / "project" / "generated-project", files)

    def test_empty_placeholder_and_generic_projects_are_rejected(self) -> None:
        empty = valid_provider_doc()
        empty["files"][2]["content"] = "   "
        with self.assertRaisesRegex(RuntimeError, "empty file"):
            run_local_pipeline.validate_provider_files(empty)

        placeholder = valid_provider_doc()
        placeholder["files"][2]["content"] = "raise NotImplementedError()\n"
        files = run_local_pipeline.validate_provider_files(placeholder)
        with self.assertRaisesRegex(RuntimeError, "placeholder project content"):
            run_local_pipeline.validate_provider_project_contract(placeholder, files)

        generic = valid_provider_doc()
        generic["project_type"] = "generic app"
        files = run_local_pipeline.validate_provider_files(generic)
        with self.assertRaisesRegex(RuntimeError, "generic/template"):
            run_local_pipeline.validate_provider_project_contract(generic, files)

    def test_packager_zip_and_manifest_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            (project / "screenshots").mkdir(parents=True)
            (project / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project / "TEST_PLAN.md").write_text("# Plan\n", encoding="utf-8")
            (project / "TEST_REPORT.md").write_text("commands_run:\n- python app.py\n", encoding="utf-8")
            (project / "DELIVERY_NOTES.md").write_text("delivery_status: PASS\n", encoding="utf-8")
            (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
            preview = project / "screenshots" / "app_home.png"
            preview.write_bytes(b"nonempty-preview")
            manifest = local_packager.package_project(project, screenshot_path=preview)
            artifacts = manifest["artifacts"]
            self.assertEqual("NEEDS_REWORK", manifest["status"])
            self.assertFalse(pathlib.Path(manifest["package_path"]).is_file())
            self.assertEqual("README.md", artifacts["readme"])
            self.assertEqual("app.py", artifacts["startup_entrypoint"])
            self.assertEqual("TEST_PLAN.md", artifacts["test_plan"])
            self.assertEqual("TEST_REPORT.md", artifacts["test_report"])
            self.assertIn("screenshots/app_home.png", artifacts["preview_evidence"])
            self.assertIn("README.md", {item["relative_path"] for item in manifest["inclusion_manifest"]})

    def test_missing_api_key_has_explicit_blocked_diagnostic(self) -> None:
        with mock.patch.object(
            run_local_pipeline.check_connectivity,
            "_resolve_api_credentials",
            return_value={"api_key": "", "base_url": "https://api.gptsapi.net/v1"},
        ):
            with self.assertRaisesRegex(RuntimeError, "missing OpenAI-compatible API key") as raised:
                run_local_pipeline.provider_text([{"role": "user", "content": "ping"}], "gpt-test", 1)
        self.assertEqual("PROVIDER_MISSING_CONFIG", bridge.provider_error_type(raised.exception))
        self.assertEqual(["CGKN_OPENAI_API_KEY or OPENAI_API_KEY"], bridge.provider_missing_config(raised.exception))

    def test_final_provider_failure_is_recoverable_blocked_result(self) -> None:
        from cgkn.application.software_project.service import SoftwareProjectGenerationService
        with tempfile.TemporaryDirectory() as temp_dir:
            root=pathlib.Path(temp_dir)
            session={'project_session_profile':str(root/'profile.json'),
                     'whiteboard':{'project_summary':'Build a task board'}}
            error=RuntimeError('provider_api_request_failed: TLS failure')
            with (mock.patch.object(bridge,'load_session',return_value=session),
                  mock.patch.object(bridge,'save_session'),
                  mock.patch.object(SoftwareProjectGenerationService,'__init__',return_value=None),
                  mock.patch.object(SoftwareProjectGenerationService,'run_profile',side_effect=error) as run,
                  mock.patch.object(bridge,'send_delivery_from_manifest') as delivery):
                with self.assertRaises(RuntimeError) as raised:
                    bridge.run_provider_generation_job(None,'completion',root,root,'ignored',30)
                self.assertIs(raised.exception,error)
                self.assertEqual(run.call_count,1)
                delivery.assert_not_called()
            self.assertEqual(session['generation']['status'],'blocked')
            self.assertEqual(session['generation']['delivery_status'],'NOT_EVALUATED')
            self.assertFalse((root/'final_project_bundle.zip').exists())

    def test_missing_local_image_model_cannot_claim_real_image_pass(self) -> None:
        session = bridge.default_session("missing-local-image")
        session["messages"].append(
            {"role": "user", "text": "做一个本地模型生成背景和立绘的视觉小说助手"}
        )
        session["whiteboard"]["local_image_model_discovery"] = {"checked": True, "available": False}
        self.assertEqual(["local_image_model_backend"], bridge.required_image_backend_missing_config(session))
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir) / "project"
            project.mkdir()
            result = bridge.collect_provider_image_evidence(project, {"example_outputs": {}}, {"copied": {}})
            self.assertFalse(result["ok"])
            self.assertFalse(result["background"])
            self.assertFalse(result["sprite"])
            self.assertFalse(any("fallback" in path.name.lower() for path in project.rglob("*") if path.is_file()))


if __name__ == "__main__":
    unittest.main()
