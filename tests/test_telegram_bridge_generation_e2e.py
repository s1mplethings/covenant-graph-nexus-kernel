from __future__ import annotations

import pathlib
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []

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


class TelegramBridgeGenerationE2ETests(unittest.TestCase):
    def test_api_generation_without_key_fails_fast(self) -> None:
        original = bridge.check_connectivity._resolve_api_credentials
        bridge.check_connectivity._resolve_api_credentials = lambda: {"api_key": ""}
        try:
            with self.assertRaisesRegex(RuntimeError, "api_generation_mode requires"):
                bridge.assert_api_generation_ready("api")
        finally:
            bridge.check_connectivity._resolve_api_credentials = original

    def test_pass_generation_records_delivery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            project_dir = root / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
            screenshot = root / "preview.png"
            screenshot.write_bytes(b"png")
            session = bridge.default_session("chat-pass")
            bridge.save_session(session_dir, session)
            result = {"status": "PASS", "project_dir": str(project_dir), "runtime_dir": str(root / "run"), "generated_files": ["README.md", "app.py"]}

            refs = bridge.emit_delivery_evidence(session_dir, session, result, screenshot, log_dir)
            ledger_text = bridge.truth_ledger_path(session_dir, "chat-pass").read_text(encoding="utf-8")

            self.assertTrue(pathlib.Path(refs["package"]).exists())
            self.assertTrue(pathlib.Path(refs["verify_report"]).exists())
            self.assertIn("package", ledger_text)
            self.assertIn("screenshot", ledger_text)
            self.assertIn("verify_report", ledger_text)
            self.assertIn("verify_passed", ledger_text)

    def test_blocked_generation_retries_then_allows_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            session = bridge.default_session("chat-retry")
            session["active_run"] = {"id": "run-chat-retry-1", "local_retry_count": 0}
            self.assertTrue(bridge.mark_generation_retry(session, reason="timeout", max_retries=2))
            self.assertFalse(session["active_run"]["local_retry_exhausted"])
            self.assertFalse(bridge.mark_generation_retry(session, reason="timeout", max_retries=2))
            self.assertTrue(session["active_run"]["local_retry_exhausted"])
            bridge.append_truth_ledger(session_dir, session, "blocked", "流程阻断", status="BLOCKED", data={"artifact": "blocked"})
            bridge.append_truth_ledger(session_dir, session, "local_retry_exhausted", "重试耗尽", status="pass", data={"artifact": "local_retry_exhausted"})
            bridge.save_session(session_dir, session)
            classification = {"intent": "escalation_request"}
            self.assertTrue(bridge.provider_escalation_allowed(session_dir, "chat-retry", classification))

    def test_generation_confirmation_runs_backend_and_delivers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            project_dir = root / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Local task manager\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
            screenshot = root / "preview.png"
            screenshot.write_bytes(b"png")
            result_path = log_dir / "telegram-live-chat-e2e_generation_result.json"
            result = {
                "status": "PASS",
                "project_dir": str(project_dir),
                "runtime_dir": str(root / "run"),
                "generated_files": ["README.md", "app.py"],
                "effect_report_path": "",
            }
            client = FakeTelegramClient()
            original_run_generation_job = bridge.run_generation_job

            def fake_run_generation_job(fake_client, chat_id, fake_session_dir, fake_log_dir, model, timeout, announce_start=False, control_id="", generation_mode="api"):
                session = bridge.load_session(fake_session_dir, chat_id)
                bridge.update_backend_control_status(session, control_id, "running")
                result_path.parent.mkdir(parents=True, exist_ok=True)
                bridge.write_json(result_path, result)
                session["generation"] = {
                    "status": "pass",
                    "finished_at": bridge.now(),
                    "result_path": str(result_path),
                    "control_id": control_id,
                    "generation_mode": generation_mode,
                }
                bridge.update_backend_control_status(session, control_id, "completed", result_path=str(result_path))
                bridge.emit_delivery_evidence(fake_session_dir, session, result, screenshot, fake_log_dir)
                evidence = bridge.delivery_evidence_state(bridge.read_truth_ledger(fake_session_dir, chat_id))
                bridge.send_delivery_artifacts(fake_client, chat_id, fake_session_dir, session, evidence)
                bridge.save_session(fake_session_dir, session)

            bridge.run_generation_job = fake_run_generation_job
            try:
                bridge.handle_text(client, "chat-e2e", "做一个本地任务管理器", session_dir, log_dir, "gpt-test", 60, "api")
                bridge.handle_text(client, "chat-e2e", "开始生成", session_dir, log_dir, "gpt-test", 60, "api")
                for _ in range(100):
                    current = bridge.load_session(session_dir, "chat-e2e")
                    if str(current.get("generation", {}).get("status", "")).lower() not in {"queued", "running"}:
                        break
                    time.sleep(0.02)
            finally:
                bridge.run_generation_job = original_run_generation_job

            session = bridge.load_session(session_dir, "chat-e2e")
            self.assertIn(str(session["generation"]["status"]).lower(), {"pass", "blocked", "failed"})
            self.assertNotEqual("queued", str(session["generation"]["status"]).lower())
            ledger_text = bridge.truth_ledger_path(session_dir, "chat-e2e").read_text(encoding="utf-8")
            self.assertIn("package", ledger_text)
            self.assertIn("screenshot", ledger_text)
            self.assertIn("verify_report", ledger_text)
            self.assertIn("verify_passed", ledger_text)
            self.assertGreaterEqual(len(client.photos), 1)
            self.assertGreaterEqual(len(client.documents), 2)
            self.assertTrue(result_path.exists() or pathlib.Path(session["generation"]["result_path"]).exists())


if __name__ == "__main__":
    unittest.main()
