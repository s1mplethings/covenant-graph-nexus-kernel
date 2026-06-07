from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.agent_conversation_loop as agent_loop
import scripts.local_agent_actions as local_actions
import scripts.local_packager as local_packager
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_photo(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_video(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(chat_id), pathlib.Path(path), caption))
        return True


class InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_manifest(project_dir: pathlib.Path) -> dict:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (project_dir / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python app.py\n", encoding="utf-8")
    (project_dir / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
    return local_packager.package_project(project_dir, startup_command="python app.py")


class AgentConversationMainlineTests(unittest.TestCase):
    def test_customer_text_appends_to_agent_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            client = FakeTelegramClient()
            original_start = bridge.start_agent_generation
            bridge.start_agent_generation = lambda *args, **kwargs: None
            try:
                bridge.handle_text(client, "chat-a", "做一个本地任务管理器", session_dir, pathlib.Path(temp_dir) / "logs", "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start

            events = read_jsonl(bridge.agent_session_path(session_dir, "chat-a"))
            self.assertTrue(any(event.get("role") == "user" and "本地任务管理器" in event.get("text", "") for event in events))

    def test_generation_confirmation_starts_agent_loop_directly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            called: dict[str, object] = {}
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_thread = bridge.threading.Thread

            def fake_loop(*, session_path, project_dir, model, timeout, max_turns):
                called["session_path"] = str(session_path)
                called["project_dir"] = str(project_dir)
                manifest = make_manifest(pathlib.Path(project_dir))
                return {"status": manifest["status"], "manifest": manifest, "manifest_path": manifest["manifest_path"]}

            bridge.agent_conversation_loop.run_agent_loop = fake_loop
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-b", "做一个本地待办事项应用", session_dir, log_dir, "gpt-test", 30)
                bridge.handle_text(client, "chat-b", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.threading.Thread = original_thread

            self.assertIn("agent_session.jsonl", str(called["session_path"]))
            self.assertNotEqual([], client.documents)
            self.assertTrue(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))

    def test_backend_controls_not_required_for_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_thread = bridge.threading.Thread
            called = {"ran": False}

            def fake_loop(*, session_path, project_dir, model, timeout, max_turns):
                called["ran"] = True
                manifest = make_manifest(pathlib.Path(project_dir))
                return {"status": manifest["status"], "manifest": manifest, "manifest_path": manifest["manifest_path"]}

            bridge.agent_conversation_loop.run_agent_loop = fake_loop
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-c", "做一个本地记账工具", session_dir, log_dir, "gpt-test", 30)
                session = bridge.load_session(session_dir, "chat-c")
                session["backend_controls"] = []
                bridge.save_session(session_dir, session)
                bridge.handle_text(client, "chat-c", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.threading.Thread = original_thread

            self.assertTrue(called["ran"])

    def test_generation_confirmation_uses_start_agent_generation_async(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            called: dict[str, object] = {}
            original_start = bridge.start_agent_generation
            original_loop = bridge.agent_conversation_loop.run_agent_loop

            def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["chat_id"] = str(chat_id)
                called["session_dir"] = str(session_dir_arg)
                called["log_dir"] = str(log_dir_arg)
                called["announce_start"] = announce_start
                called["reason"] = reason

            def forbidden_loop(*args, **kwargs):
                raise AssertionError("generation_confirmation must not synchronously call run_agent_loop")

            bridge.start_agent_generation = fake_start
            bridge.agent_conversation_loop.run_agent_loop = forbidden_loop
            try:
                bridge.handle_text(client, "chat-async", "做一个本地看板应用", session_dir, log_dir, "gpt-test", 30)
                bridge.handle_text(client, "chat-async", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start
                bridge.agent_conversation_loop.run_agent_loop = original_loop

            self.assertEqual("chat-async", called["chat_id"])
            self.assertEqual(str(session_dir), called["session_dir"])
            self.assertEqual(str(log_dir), called["log_dir"])
            self.assertFalse(called["announce_start"])

    def test_old_backend_controls_do_not_block_agent_mainline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            original_start = bridge.start_agent_generation
            called = {"start": False}

            def fake_start(*args, **kwargs):
                called["start"] = True

            bridge.start_agent_generation = fake_start
            try:
                bridge.handle_text(client, "chat-old-control", "做一个本地表格工具", session_dir, log_dir, "gpt-test", 30)
                session = bridge.load_session(session_dir, "chat-old-control")
                session["backend_controls"] = [{"action": "start_generation", "status": "queued"}]
                bridge.save_session(session_dir, session)
                bridge.handle_text(client, "chat-old-control", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start

            self.assertTrue(called["start"])
            self.assertFalse(any("状态" in text or "status" in text.lower() for _, text in client.messages[-1:]))

    def test_backend_control_log_is_log_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            session = bridge.default_session("chat-log")

            control = bridge.append_backend_control(session_dir, session, "start_generation", payload={"x": 1})

            self.assertEqual("BackendControlLog", control["kind"])
            self.assertEqual("logged", control["status"])
            self.assertTrue(control["log_only"])
            ledger = bridge.truth_ledger_path(session_dir, "chat-log").read_text(encoding="utf-8")
            self.assertIn("兼容日志", ledger)
            self.assertNotIn("后台队列", ledger)

    def test_agent_loop_preserves_conversation_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = pathlib.Path(temp_dir) / "agent_session.jsonl"
            project_dir = pathlib.Path(temp_dir) / "project"
            agent_loop.append_event(session_path, {"kind": "user", "role": "user", "text": "先做任务管理"})
            agent_loop.append_event(session_path, {"kind": "user", "role": "user", "text": "再加日历视图"})
            captured: dict[str, object] = {}

            def fake_agent(events, model, timeout):
                captured["texts"] = [event.get("text") for event in events if event.get("role") == "user"]
                return {
                    "actions": [
                        {"type": "write_file", "path": "README.md", "content": "# Task Calendar\n"},
                        {"type": "package_project", "startup_command": ""},
                    ]
                }

            result = agent_loop.run_agent_loop(session_path=session_path, project_dir=project_dir, agent=fake_agent, max_turns=3)

            self.assertIn("先做任务管理", captured["texts"])
            self.assertIn("再加日历视图", captured["texts"])
            self.assertTrue(pathlib.Path(result["package_path"]).exists())

    def test_failed_command_is_returned_to_agent_for_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = pathlib.Path(temp_dir) / "agent_session.jsonl"
            project_dir = pathlib.Path(temp_dir) / "project"
            agent_loop.append_event(session_path, {"kind": "user", "role": "user", "text": "生成并测试"})
            saw_failed_result = {"value": False}

            def fake_agent(events, model, timeout):
                tool_results = [event for event in events if event.get("kind") == "tool_result"]
                if not tool_results:
                    return {"actions": [{"type": "run_command", "command": "python missing_file.py"}]}
                saw_failed_result["value"] = any(
                    event.get("result", {}).get("ok") is False and event.get("result", {}).get("returncode") != 0
                    for event in tool_results
                )
                return {
                    "actions": [
                        {"type": "write_file", "path": "README.md", "content": "# Repaired\n"},
                        {"type": "package_project", "startup_command": ""},
                    ]
                }

            result = agent_loop.run_agent_loop(session_path=session_path, project_dir=project_dir, agent=fake_agent, max_turns=3)

            self.assertTrue(saw_failed_result["value"])
            self.assertTrue(pathlib.Path(result["package_path"]).exists())

    def test_malformed_agent_json_is_returned_as_no_action_parse_error(self) -> None:
        parsed = agent_loop.parse_agent_response('{"message":"bad","actions":[{"type":"write_file","path":"README.md"}')

        self.assertEqual([], parsed["actions"])
        self.assertIn("parse_error", parsed)

    def test_truncated_agent_json_salvages_complete_write_file_actions(self) -> None:
        raw = (
            '{"message":"partial","actions":['
            '{"type":"write_file","path":"backend/app.py","content":"print(\\"ok\\")\\n"},'
            '{"type":"write_file","path":"HANDOFF_BACKEND.md","content":"# truncated'
        )

        parsed = agent_loop.parse_agent_response(raw)

        self.assertEqual([{"type": "write_file", "path": "backend/app.py", "content": 'print("ok")\n'}], parsed["actions"])
        self.assertIn("parse_error", parsed)

    def test_local_packager_creates_zip_without_screenshot_hard_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir) / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")

            manifest = local_packager.package_project(project_dir)

            self.assertEqual("ready_with_warnings", manifest["status"])
            self.assertTrue(pathlib.Path(manifest["package_path"]).exists())
            self.assertTrue(pathlib.Path(manifest["manifest_path"]).exists())

    def test_local_packager_marks_known_limits_as_warning_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir) / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            screenshot = project_dir / "preview.png"
            screenshot.write_bytes(b"preview")

            manifest = local_packager.package_project(project_dir, screenshot_path=screenshot, known_limits=["模型未配置"])

            self.assertEqual("ready_with_warnings", manifest["status"])
            self.assertIn("模型未配置", manifest["known_limits"])

    def test_agent_cannot_write_outside_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir) / "project"
            executor = local_actions.LocalAgentActionExecutor(project_dir)

            result = executor.execute({"type": "write_file", "path": "../escape.txt", "content": "no"})

            self.assertFalse(result["ok"])
            self.assertFalse((pathlib.Path(temp_dir) / "escape.txt").exists())

    def test_executor_rejects_invalid_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir) / "project"
            executor = local_actions.LocalAgentActionExecutor(project_dir)

            result = executor.execute({"type": "write_file", "path": "CFO_CONTEXT_DB.json", "content": '{"bad":,,}'})

            self.assertFalse(result["ok"])
            self.assertIn("JSON content is invalid", result["error"])
            self.assertFalse((project_dir / "CFO_CONTEXT_DB.json").exists())

    def test_agent_loop_can_repair_invalid_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_path = pathlib.Path(temp_dir) / "agent_session.jsonl"
            project_dir = pathlib.Path(temp_dir) / "project"
            saw_json_failure = {"value": False}

            def fake_agent(events, model, timeout):
                tool_results = [event for event in events if event.get("kind") == "tool_result"]
                if not tool_results:
                    return {"actions": [{"type": "write_file", "path": "CFO_CONTEXT_DB.json", "content": '{"bad":,,}'}]}
                saw_json_failure["value"] = any("JSON content is invalid" in str(event) for event in tool_results)
                return {
                    "actions": [
                        {"type": "write_file", "path": "CFO_CONTEXT_DB.json", "content": '{"ok": true}'},
                        {"type": "write_file", "path": "README.md", "content": "# Fixed\n"},
                        {"type": "package_project", "startup_command": ""},
                    ]
                }

            result = agent_loop.run_agent_loop(session_path=session_path, project_dir=project_dir, agent=fake_agent, max_turns=3)

            self.assertTrue(saw_json_failure["value"])
            self.assertTrue(pathlib.Path(result["package_path"]).exists())
            self.assertEqual('{"ok": true}', (project_dir / "CFO_CONTEXT_DB.json").read_text(encoding="utf-8"))

    def test_telegram_delivery_uses_delivery_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project_dir = root / "project"
            manifest = make_manifest(project_dir)
            session = bridge.default_session("chat-d")
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient()

            sent = bridge.send_delivery_from_manifest(client, "chat-d", session_dir, session, manifest)

            self.assertTrue(any(item["kind"] == "package" for item in sent))
            self.assertTrue(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))
            self.assertFalse(any(path.name == "delivery_manifest.json" for _, path, _ in client.documents))
            self.assertFalse(any(path.name == "README.md" for _, path, _ in client.documents))
            self.assertNotIn("screenshot", client.messages[-1][1].lower())
            self.assertNotIn("not provided", client.messages[-1][1].lower())
            ledger = bridge.truth_ledger_path(session_dir, "chat-d").read_text(encoding="utf-8")
            self.assertIn("public_delivery_attachment_sent", ledger)

    def test_non_pass_generation_updates_active_run_out_of_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project_dir = root / "project"
            session = bridge.default_session("chat-non-pass")
            session["active_run"] = {"id": "run-1", "status": "running", "created_at": bridge.now()}
            session["generation"] = {"status": "running"}
            bridge.save_session(session_dir, session)
            client = FakeTelegramClient()

            bridge.finish_agent_loop_delivery(
                client,
                "chat-non-pass",
                session_dir,
                project_dir,
                {"status": "max_turns_reached", "driver": "agent_generated_pipeline"},
            )

            saved = bridge.load_session(session_dir, "chat-non-pass")
            self.assertEqual("max_turns_reached", saved["generation"]["status"])
            self.assertEqual("max_turns_reached", saved["active_run"]["status"])
            self.assertFalse(client.documents)

    def test_run_local_pipeline_no_api_blocked_not_connected_to_telegram_mainline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeTelegramClient()
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_subprocess = bridge.run_generation_subprocess
            original_thread = bridge.threading.Thread
            called = {"loop": False}

            def fake_loop(*, session_path, project_dir, model, timeout, max_turns):
                called["loop"] = True
                manifest = make_manifest(pathlib.Path(project_dir))
                return {"status": manifest["status"], "manifest": manifest, "manifest_path": manifest["manifest_path"]}

            def forbidden_subprocess(*args, **kwargs):
                raise AssertionError("Telegram mainline must not call old no-api subprocess path")

            bridge.agent_conversation_loop.run_agent_loop = fake_loop
            bridge.run_generation_subprocess = forbidden_subprocess
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-no-api", "做一个本地笔记应用", session_dir, log_dir, "gpt-test", 30, "simulator")
                bridge.handle_text(client, "chat-no-api", "开始生成", session_dir, log_dir, "gpt-test", 30, "simulator")
            finally:
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.run_generation_subprocess = original_subprocess
                bridge.threading.Thread = original_thread

            self.assertTrue(called["loop"])
            session = bridge.load_session(session_dir, "chat-no-api")
            self.assertEqual("agent_conversation_loop_fallback", session["generation"]["driver"])
            self.assertTrue(pathlib.Path(session["generation"]["package_path"]).exists())


if __name__ == "__main__":
    unittest.main()
