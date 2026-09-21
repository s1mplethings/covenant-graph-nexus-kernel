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
import scripts.pipeline_planner_agent as planner_agent
import scripts.codex_conversation as bridge


class FakeCodexConversation:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.actions: list[tuple[str, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.photos: list[tuple[str, pathlib.Path, str]] = []
        self.videos: list[tuple[str, pathlib.Path, str]] = []

    def send_message(self, conversation_id: int | str, text: str) -> bool:
        self.messages.append((str(conversation_id), text))
        return True

    def send_chat_action(self, conversation_id: int | str, action: str) -> None:
        self.actions.append((str(conversation_id), action))

    def send_document(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(conversation_id), pathlib.Path(path), caption))
        return True

    def send_photo(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.photos.append((str(conversation_id), pathlib.Path(path), caption))
        return True

    def send_video(self, conversation_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.videos.append((str(conversation_id), pathlib.Path(path), caption))
        return True


class InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return False


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_manifest(project_dir: pathlib.Path) -> dict:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
    (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (project_dir / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python app.py\n", encoding="utf-8")
    (project_dir / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
    return local_packager.package_project(project_dir, startup_command="python app.py")


def make_provider_result(project_dir: pathlib.Path) -> dict:
    make_manifest(project_dir)
    (project_dir / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (project_dir / "tests").mkdir(exist_ok=True)
    (project_dir / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return {
        "status": "PASS",
        "generated_files": ["README.md", "app.py", "requirements.txt", "TEST_REPORT.md", "DELIVERY_NOTES.md"],
        "provider_semantic_review": {"status": "pass"},
        "artifact_refs": {},
        "agent_usage": {"status": "pass", "events": [{"command": "python app.py"}]},
        "example_outputs": {},
    }


class AgentConversationMainlineTests(unittest.TestCase):
    def test_customer_text_appends_to_agent_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            client = FakeCodexConversation()
            original_start = bridge.start_agent_generation
            bridge.start_agent_generation = lambda *args, **kwargs: None
            try:
                bridge.handle_text(client, "chat-a", "做一个本地任务管理器", session_dir, pathlib.Path(temp_dir) / "logs", "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start

            events = read_jsonl(bridge.agent_session_path(session_dir, "chat-a"))
            self.assertTrue(any(event.get("role") == "user" and "本地任务管理器" in event.get("text", "") for event in events))

    def test_generation_confirmation_runs_provider_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeCodexConversation()
            called: dict[str, object] = {}
            original_execute = bridge.provider_project_pipeline.execute
            original_thread = bridge.threading.Thread

            def fake_execute(args):
                called["project_dir"] = str(args.out_dir)
                return make_provider_result(pathlib.Path(args.out_dir))

            bridge.provider_project_pipeline.execute = fake_execute
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-b", "做一个本地待办事项应用", session_dir, log_dir, "gpt-test", 30)
                bridge.handle_text(client, "chat-b", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.provider_project_pipeline.execute = original_execute
                bridge.threading.Thread = original_thread

            saved = bridge.load_session(session_dir, "chat-b")
            provider_staging = pathlib.Path(str(called["project_dir"])).resolve()
            final_candidate = pathlib.Path(
                saved["generation"]["project_dir"]
            ).resolve()
            self.assertEqual("provider_response_staging", provider_staging.parent.name)
            self.assertEqual(saved["generation"]["run_id"], provider_staging.name)
            self.assertNotEqual(final_candidate, provider_staging)
            self.assertEqual([], client.documents)
            self.assertNotIn(saved.get("generation", {}).get("status"), {"delivered", "delivered_with_warnings"})
            self.assertFalse(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))

    def test_backend_controls_not_required_for_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeCodexConversation()
            original_execute = bridge.provider_project_pipeline.execute
            original_thread = bridge.threading.Thread
            called = {"ran": False}

            def fake_execute(args):
                called["ran"] = True
                return make_provider_result(pathlib.Path(args.out_dir))

            bridge.provider_project_pipeline.execute = fake_execute
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-c", "做一个本地记账工具", session_dir, log_dir, "gpt-test", 30)
                session = bridge.load_session(session_dir, "chat-c")
                session["backend_controls"] = []
                bridge.save_session(session_dir, session)
                bridge.handle_text(client, "chat-c", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.provider_project_pipeline.execute = original_execute
                bridge.threading.Thread = original_thread

            self.assertTrue(called["ran"])

    def test_generation_confirmation_uses_start_agent_generation_async(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeCodexConversation()
            called: dict[str, object] = {}
            original_start = bridge.start_agent_generation
            original_loop = agent_loop.run_agent_loop

            def fake_start(client_arg, conversation_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["conversation_id"] = str(conversation_id)
                called["session_dir"] = str(session_dir_arg)
                called["log_dir"] = str(log_dir_arg)
                called["announce_start"] = announce_start
                called["reason"] = reason

            def forbidden_loop(*args, **kwargs):
                raise AssertionError("generation_confirmation must not synchronously call run_agent_loop")

            bridge.start_agent_generation = fake_start
            agent_loop.run_agent_loop = forbidden_loop
            try:
                bridge.handle_text(client, "chat-async", "做一个本地文本转换工具", session_dir, log_dir, "gpt-test", 30)
                bridge.handle_text(client, "chat-async", "开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start
                agent_loop.run_agent_loop = original_loop

            self.assertEqual("chat-async", called["conversation_id"])
            self.assertEqual(str(session_dir), called["session_dir"])
            self.assertEqual(str(log_dir), called["log_dir"])
            self.assertFalse(called["announce_start"])

    def test_old_backend_controls_do_not_block_agent_mainline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeCodexConversation()
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
            self.assertFalse(pathlib.Path(result.get("package_path", "")).is_file())
            self.assertNotEqual("PASS", result.get("status"))

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
            self.assertFalse(pathlib.Path(result.get("package_path", "")).is_file())
            self.assertNotEqual("PASS", result.get("status"))

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

            self.assertEqual("NEEDS_REWORK", manifest["status"])
            self.assertFalse(pathlib.Path(manifest["package_path"]).exists())
            self.assertTrue(pathlib.Path(manifest["manifest_path"]).exists())

    def test_local_packager_marks_known_limits_as_warning_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir) / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            screenshot = project_dir / "preview.png"
            screenshot.write_bytes(b"preview")

            manifest = local_packager.package_project(project_dir, screenshot_path=screenshot, known_limits=["模型未配置"])

            self.assertEqual("NEEDS_REWORK", manifest["status"])
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
            self.assertFalse(pathlib.Path(result.get("package_path", "")).is_file())
            self.assertNotEqual("PASS", result.get("status"))
            self.assertEqual('{"ok": true}', (project_dir / "CFO_CONTEXT_DB.json").read_text(encoding="utf-8"))

    def test_conversation_delivery_uses_delivery_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project_dir = root / "project"
            manifest = make_manifest(project_dir)
            session = bridge.default_session("chat-d")
            bridge.save_session(session_dir, session)
            client = FakeCodexConversation()

            sent = bridge.send_delivery_from_manifest(client, "chat-d", session_dir, session, manifest)

            self.assertEqual([], sent)
            self.assertEqual([], client.documents)
            self.assertFalse(any(path.name == "delivery_manifest.json" for _, path, _ in client.documents))
            self.assertFalse(any(path.name == "README.md" for _, path, _ in client.documents))
            self.assertNotIn("screenshot", client.messages[-1][1].lower())
            self.assertNotIn("not provided", client.messages[-1][1].lower())
            ledger = bridge.truth_ledger_path(session_dir, "chat-d").read_text(encoding="utf-8")
            self.assertIn("public_delivery_gate", ledger)
            self.assertNotIn("public_delivery_attachment_sent", ledger)

    def test_non_pass_generation_without_package_becomes_rework(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project_dir = root / "project"
            session = bridge.default_session("chat-non-pass")
            session["active_run"] = {"id": "run-1", "status": "running", "created_at": bridge.now()}
            session["generation"] = {"status": "running"}
            bridge.save_session(session_dir, session)
            client = FakeCodexConversation()

            bridge.finish_agent_loop_delivery(
                client,
                "chat-non-pass",
                session_dir,
                project_dir,
                {"status": "max_turns_reached", "driver": "agent_generated_pipeline"},
            )

            saved = bridge.load_session(session_dir, "chat-non-pass")
            self.assertEqual("rework_blocked", saved["generation"]["status"])
            self.assertEqual("rework_blocked", saved["active_run"]["status"])
            self.assertFalse(saved["generation"]["delivery_allowed"])
            self.assertFalse(client.documents)
            joined = "\n".join(text for _, text in client.messages)
            self.assertIn("需要继续修复", joined)
            self.assertNotIn("事实级问题", joined)

    def test_finish_delivery_forwards_validated_provider_result_to_final_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            project_dir = root / "project"
            project_dir.mkdir()
            session = bridge.default_session("chat-provider-result")
            bridge.save_session(session_dir, session)
            client = FakeCodexConversation()
            result = {
                "status": "PASS",
                "driver": "api_provider_project_generation",
                "manifest": {
                    "status": "PASS",
                    "project_dir": str(project_dir),
                    "package_path": str(project_dir / "final_project_bundle.zip"),
                    "manifest_path": str(project_dir / "delivery_manifest.json"),
                },
            }
            captured: dict[str, object] = {}
            original_send = bridge.send_delivery_from_manifest

            def fake_send(_client, _conversation_id, _session_dir, _session, _manifest, provider_result=None):
                captured["provider_result"] = provider_result
                return []

            bridge.send_delivery_from_manifest = fake_send
            try:
                bridge.finish_agent_loop_delivery(client, "chat-provider-result", session_dir, project_dir, result)
            finally:
                bridge.send_delivery_from_manifest = original_send

            self.assertIs(result, captured.get("provider_result"))

    def test_agent_pipeline_failure_becomes_rework_without_internal_public_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeCodexConversation()
            session = bridge.default_session("chat-fail-rework")
            session["active_run"] = {"id": "run-fail", "goal": "做一个本地工具", "status": "running", "created_at": bridge.now()}
            session["whiteboard"]["project_summary"] = "做一个本地工具"
            bridge.save_session(session_dir, session)
            original_plan = planner_agent.plan_pipeline
            original_loop = agent_loop.run_agent_loop

            planner_agent.plan_pipeline = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("planner transport failed"))
            agent_loop.run_agent_loop = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider TLS failed"))
            try:
                bridge.run_agent_generation_job(client, "chat-fail-rework", session_dir, log_dir, "gpt-test", 5)
            finally:
                planner_agent.plan_pipeline = original_plan
                agent_loop.run_agent_loop = original_loop

            saved = bridge.load_session(session_dir, "chat-fail-rework")
            self.assertEqual("rework_blocked", saved["generation"]["status"])
            self.assertEqual("rework_blocked", saved["active_run"]["status"])
            self.assertFalse(saved["generation"]["delivery_allowed"])
            self.assertEqual([], client.documents)
            joined = "\n".join(text for _, text in client.messages)
            self.assertIn("需要继续修复", joined)
            self.assertNotIn("事实级问题", joined)
            for forbidden in ("TLS", "provider", "backend", "后台", "pipeline", "manifest"):
                self.assertNotIn(forbidden, joined)

    def test_simulator_mode_is_preflight_only_and_does_not_deliver(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_dir = root / "sessions"
            log_dir = root / "logs"
            client = FakeCodexConversation()
            original_execute = bridge.provider_project_pipeline.execute
            original_subprocess = bridge.run_generation_subprocess
            original_thread = bridge.threading.Thread
            called = {"provider": False}

            def fake_execute(args):
                called["provider"] = True
                return make_provider_result(pathlib.Path(args.out_dir))

            def forbidden_subprocess(*args, **kwargs):
                raise AssertionError("Codex conversation mainline must not call old no-api subprocess path")

            bridge.provider_project_pipeline.execute = fake_execute
            bridge.run_generation_subprocess = forbidden_subprocess
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-no-api", "做一个本地笔记应用", session_dir, log_dir, "gpt-test", 30, "simulator")
                bridge.handle_text(client, "chat-no-api", "开始生成", session_dir, log_dir, "gpt-test", 30, "simulator")
            finally:
                bridge.provider_project_pipeline.execute = original_execute
                bridge.run_generation_subprocess = original_subprocess
                bridge.threading.Thread = original_thread

            self.assertTrue(called["provider"])
            session = bridge.load_session(session_dir, "chat-no-api")
            self.assertEqual("simulator_preflight", session["generation"]["driver"])
            self.assertEqual("rework_blocked", session["generation"]["status"])
            self.assertFalse(session["generation"]["delivery_allowed"])
            self.assertFalse((ROOT / "generated" / "simulator_preflight" / "chat-no-api" / "final_project_bundle.zip").exists())


if __name__ == "__main__":
    unittest.main()
