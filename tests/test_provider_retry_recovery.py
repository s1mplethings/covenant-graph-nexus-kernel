from __future__ import annotations

import json
import argparse
import os
import pathlib
import shutil
import ssl
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.codex_conversation as bridge


class FakeCodexConversation:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, conversation_id: int | str, text: str) -> bool:
        self.messages.append((str(conversation_id), text))
        return True

    def send_chat_action(self, conversation_id: int | str, action: str) -> None:
        self.actions.append((str(conversation_id), action))

    def send_photo(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(conversation_id), pathlib.Path(path), caption))
        return True

    def send_document(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(conversation_id), pathlib.Path(path), caption))
        return True

    def send_video(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(conversation_id), pathlib.Path(path), caption))
        return True


def seed_session(session_dir: pathlib.Path, conversation_id: str, goal: str) -> None:
    shutil.rmtree(ROOT / "generated" / "codex_provider_projects" / bridge.safe_id(conversation_id), ignore_errors=True)
    session = bridge.default_session(conversation_id)
    session["messages"].append({"role": "user", "text": goal, "created_at": bridge.now()})
    session["active_run"] = {"goal": goal, "status": "intake_open"}
    session["whiteboard"]["project_summary"] = goal
    bridge.save_session(session_dir, session)


def read_agent_events(session_dir: pathlib.Path, conversation_id: str) -> list[dict[str, object]]:
    path = bridge.agent_session_path(session_dir, conversation_id)
    events: list[dict[str, object]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


class ProviderRetryRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_execute = bridge.provider_project_pipeline.execute
        self.original_fast = os.environ.get("CGKN_PROVIDER_RETRY_FAST")
        os.environ["CGKN_PROVIDER_RETRY_FAST"] = "1"

    def tearDown(self) -> None:
        bridge.provider_project_pipeline.execute = self.original_execute
        if self.original_fast is None:
            os.environ.pop("CGKN_PROVIDER_RETRY_FAST", None)
        else:
            os.environ["CGKN_PROVIDER_RETRY_FAST"] = self.original_fast

    def test_retryable_tls_error_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            conversation_id = "chat-retry-pass"
            seed_session(session_dir, conversation_id, "做一个本地任务工具")
            calls = {"count": 0}

            def fake_execute(args):
                calls["count"] += 1
                if calls["count"] < 3:
                    raise ssl.SSLError("SSLV3_ALERT_BAD_RECORD_MAC")
                project = pathlib.Path(args.out_dir)
                project.mkdir(parents=True, exist_ok=True)
                (project / "README.md").write_text("# Tool\n", encoding="utf-8")
                (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
                (project / "tests").mkdir(exist_ok=True)
                (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
                (project / "DELIVERY_NOTES.md").write_text("delivery_status: PASS\n", encoding="utf-8")
                return {"status": "PASS", "generated_files": ["app.py"], "agent_usage": {"events": [{"command": "python app.py"}]}}

            bridge.provider_project_pipeline.execute = fake_execute
            client = FakeCodexConversation()
            bridge.run_provider_generation_job(client, conversation_id, session_dir, log_dir, "gpt-test", 30)

            session = bridge.load_session(session_dir, conversation_id)
            retry_events = [event for event in read_agent_events(session_dir, conversation_id) if event.get("kind") == "provider_retry"]
            self.assertEqual(3, calls["count"])
            self.assertEqual(2, len(retry_events))
            self.assertEqual("rework_blocked", session["generation"]["status"])

    def test_retryable_tls_error_exhausted_marks_rework_without_public_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            conversation_id = "chat-retry-fail"
            seed_session(session_dir, conversation_id, "本地可运行的 VN 项目助手，时间线，背景，立绘，本地模型，桌面界面，文件导出")
            calls = {"count": 0}

            def fake_execute(args):
                calls["count"] += 1
                raise ssl.SSLError("SSLV3_ALERT_BAD_RECORD_MAC")

            bridge.provider_project_pipeline.execute = fake_execute
            client = FakeCodexConversation()
            bridge.run_provider_generation_job(client, conversation_id, session_dir, log_dir, "gpt-test", 30)

            session = bridge.load_session(session_dir, conversation_id)
            self.assertEqual(5, calls["count"])
            self.assertEqual("rework_blocked", session["generation"]["status"])
            self.assertFalse(session["generation"]["delivery_allowed"])
            self.assertEqual([], client.photos)
            self.assertEqual([], client.documents)
            self.assertEqual([], client.videos)
            public_text = "\n".join(text for _, text in client.messages)
            for forbidden in ("TLS", "SSLError", "provider", "后台"):
                self.assertNotIn(forbidden, public_text)
            self.assertIn("继续修复", public_text)

    def test_stage_resume_after_provider_transport_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            conversation_id = "chat-stage-resume"
            seed_session(session_dir, conversation_id, "做一个本地任务工具")
            calls = {"count": 0}
            provider_staging: list[pathlib.Path] = []

            def fake_execute(args):
                calls["count"] += 1
                project = pathlib.Path(args.out_dir)
                provider_staging.append(project.resolve())
                project.mkdir(parents=True, exist_ok=True)
                if calls["count"] == 1:
                    (project / "README.md").write_text("# Existing README\n", encoding="utf-8")
                    (project / "app.py").write_text("print('existing')\n", encoding="utf-8")
                    raise ssl.SSLError("SSLV3_ALERT_BAD_RECORD_MAC")
                self.assertEqual("stage_resume", getattr(args, "provider_recovery_mode", ""))
                self.assertIn("README.md", getattr(args, "provider_partial_artifacts", []))
                self.assertEqual("# Existing README\n", (project / "README.md").read_text(encoding="utf-8"))
                self.assertEqual("print('existing')\n", (project / "app.py").read_text(encoding="utf-8"))
                (project / "tests").mkdir(exist_ok=True)
                (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
                (project / "DELIVERY_NOTES.md").write_text("delivery_status: PASS\n", encoding="utf-8")
                return {"status": "PASS", "generated_files": ["TEST_REPORT.md"], "agent_usage": {"events": [{"command": "python app.py"}]}}

            bridge.provider_project_pipeline.execute = fake_execute
            client = FakeCodexConversation()
            bridge.run_provider_generation_job(client, conversation_id, session_dir, log_dir, "gpt-test", 30)

            project = ROOT / "generated" / "codex_provider_projects" / bridge.safe_id(conversation_id)
            self.assertEqual(2, calls["count"])
            self.assertEqual(provider_staging[0], provider_staging[1])
            self.assertEqual(
                "# Existing README\n",
                (provider_staging[-1] / "README.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "print('existing')\n",
                (provider_staging[-1] / "app.py").read_text(encoding="utf-8"),
            )
            self.assertNotEqual(
                "# Existing README\n",
                (project / "README.md").read_text(encoding="utf-8"),
            )
            self.assertFalse((project / "app.py").exists())

    def test_provider_exception_never_delivers_partial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            conversation_id = "chat-partial-no-deliver"
            seed_session(session_dir, conversation_id, "做一个本地任务工具")

            def fake_execute(args):
                project = pathlib.Path(args.out_dir)
                project.mkdir(parents=True, exist_ok=True)
                (project / "README.md").write_text("# Tool\n", encoding="utf-8")
                (project / "main.py").write_text("print('ok')\n", encoding="utf-8")
                (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
                (project / "TEST_REPORT.md").write_text("# Test Report\n\ncommands_run:\n- python -m pytest tests\n\nexit_code: 0\n", encoding="utf-8")
                (project / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
                (project / "tests").mkdir(exist_ok=True)
                (project / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
                raise RuntimeError("merged component output missing required files: TEST_PLAN.md")

            bridge.provider_project_pipeline.execute = fake_execute
            client = FakeCodexConversation()
            bridge.run_provider_generation_job(client, conversation_id, session_dir, log_dir, "gpt-test", 30)

            session = bridge.load_session(session_dir, conversation_id)
            self.assertEqual("rework_blocked", session["generation"]["status"])
            self.assertFalse(session["generation"]["delivery_allowed"])
            self.assertEqual("NEEDS_REWORK", session["generation"]["delivery_gate"]["status"])
            self.assertFalse(session["generation"]["delivery_gate"]["delivery_allowed"])
            self.assertTrue(session["generation"]["delivery_gate"]["required_repairs"])
            self.assertEqual([], client.photos)
            self.assertEqual([], client.documents)
            self.assertEqual([], client.videos)

    def test_blocked_provider_result_stops_before_causal_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project_dir = root / "candidate"
            project_dir.mkdir()
            run_dir = root / "run"
            result_path = run_dir / "provider_generation_result.json"
            original_runner = bridge.run_provider_execute_with_retries
            original_candidate_root = (
                bridge.provider_causal_trace.production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT
            )

            def blocked_runner(args, **kwargs):
                return {
                    "status": "BLOCKED",
                    "diagnostics": {
                        "status": "blocked",
                        "stage": "provider_semantic_review",
                        "blockers": [
                            "provider static-only backend manifest must contain exactly app/main.py"
                        ],
                    },
                }

            bridge.run_provider_execute_with_retries = blocked_runner
            bridge.provider_causal_trace.production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = root
            try:
                with self.assertRaisesRegex(
                    RuntimeError,
                    "provider_generation_blocked.*app/main.py",
                ) as caught:
                    bridge.execute_validated_provider_round(
                        argparse.Namespace(goal="Build a local task board"),
                        session_dir=root / "sessions",
                        conversation_id="blocked-result",
                        phase_log_path=run_dir / "provider_phase_log.jsonl",
                        project_dir=project_dir,
                        provider_staging_dir=root / "missing-staging",
                        run_dir=run_dir,
                        result_path=result_path,
                        identity={
                            "run_id": "run-blocked",
                            "candidate_id": "candidate-blocked",
                            "commit_sha": "a" * 40,
                        },
                        model="gpt-test",
                        formal_entry=True,
                    )
            finally:
                bridge.run_provider_execute_with_retries = original_runner
                bridge.provider_causal_trace.production_candidate_provenance.PRODUCTION_CANDIDATE_ROOT = (
                    original_candidate_root
                )

            self.assertNotIn("causal capture", str(caught.exception))
            self.assertTrue(result_path.is_file())


if __name__ == "__main__":
    unittest.main()
