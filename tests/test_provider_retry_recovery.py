from __future__ import annotations

import json
import os
import pathlib
import shutil
import ssl
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(chat_id), pathlib.Path(path), caption))
        return True


def seed_session(session_dir: pathlib.Path, chat_id: str, goal: str) -> None:
    shutil.rmtree(ROOT / "generated" / "telegram_provider_projects" / bridge.safe_id(chat_id), ignore_errors=True)
    session = bridge.default_session(chat_id)
    session["messages"].append({"role": "user", "text": goal, "created_at": bridge.now()})
    session["active_run"] = {"goal": goal, "status": "intake_open"}
    session["whiteboard"]["project_summary"] = goal
    bridge.save_session(session_dir, session)


def read_agent_events(session_dir: pathlib.Path, chat_id: str) -> list[dict[str, object]]:
    path = bridge.agent_session_path(session_dir, chat_id)
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
            chat_id = "chat-retry-pass"
            seed_session(session_dir, chat_id, "做一个本地任务工具")
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
            client = FakeTelegramClient()
            bridge.run_provider_generation_job(client, chat_id, session_dir, log_dir, "gpt-test", 30)

            session = bridge.load_session(session_dir, chat_id)
            retry_events = [event for event in read_agent_events(session_dir, chat_id) if event.get("kind") == "provider_retry"]
            self.assertEqual(3, calls["count"])
            self.assertEqual(2, len(retry_events))
            self.assertNotEqual("rework_blocked", session["generation"]["status"])

    def test_retryable_tls_error_exhausted_marks_rework_without_public_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            chat_id = "chat-retry-fail"
            seed_session(session_dir, chat_id, "本地可运行的 VN 项目助手，时间线，背景，立绘，本地模型，桌面界面，文件导出")
            calls = {"count": 0}

            def fake_execute(args):
                calls["count"] += 1
                raise ssl.SSLError("SSLV3_ALERT_BAD_RECORD_MAC")

            bridge.provider_project_pipeline.execute = fake_execute
            client = FakeTelegramClient()
            bridge.run_provider_generation_job(client, chat_id, session_dir, log_dir, "gpt-test", 30)

            session = bridge.load_session(session_dir, chat_id)
            self.assertEqual(5, calls["count"])
            self.assertEqual("rework_blocked", session["generation"]["status"])
            self.assertFalse(session["generation"]["delivery_allowed"])
            self.assertEqual([], client.photos)
            self.assertEqual([], client.documents)
            self.assertEqual([], client.videos)
            public_text = "\n".join(text for _, text in client.messages)
            for forbidden in ("TLS", "SSLError", "provider", "后台"):
                self.assertNotIn(forbidden, public_text)
            self.assertIn("事实级问题", public_text)

    def test_stage_resume_after_provider_transport_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            chat_id = "chat-stage-resume"
            seed_session(session_dir, chat_id, "做一个本地任务工具")
            calls = {"count": 0}

            def fake_execute(args):
                calls["count"] += 1
                project = pathlib.Path(args.out_dir)
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
            client = FakeTelegramClient()
            bridge.run_provider_generation_job(client, chat_id, session_dir, log_dir, "gpt-test", 30)

            project = ROOT / "generated" / "telegram_provider_projects" / bridge.safe_id(chat_id)
            self.assertEqual(2, calls["count"])
            self.assertEqual("# Existing README\n", (project / "README.md").read_text(encoding="utf-8"))
            self.assertEqual("print('existing')\n", (project / "app.py").read_text(encoding="utf-8"))

    def test_provider_exception_never_delivers_partial_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            chat_id = "chat-partial-no-deliver"
            seed_session(session_dir, chat_id, "做一个本地任务工具")

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
            client = FakeTelegramClient()
            bridge.run_provider_generation_job(client, chat_id, session_dir, log_dir, "gpt-test", 30)

            session = bridge.load_session(session_dir, chat_id)
            self.assertEqual("rework_blocked", session["generation"]["status"])
            self.assertFalse(session["generation"]["delivery_allowed"])
            self.assertEqual("FACT_BLOCKED", session["generation"]["delivery_gate"]["status"])
            self.assertFalse(session["generation"]["delivery_gate"]["delivery_allowed"])
            self.assertIn(
                "provider_not_successful",
                session["generation"]["delivery_gate"]["delivery_fact_check"]["hard_blockers"],
            )
            self.assertEqual([], client.photos)
            self.assertEqual([], client.documents)
            self.assertEqual([], client.videos)


if __name__ == "__main__":
    unittest.main()
