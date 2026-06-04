from __future__ import annotations

import ast
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge
import scripts.project_memory_md as project_memory_md


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


class TelegramCustomerBridgeTests(unittest.TestCase):
    def assert_public_reply_style(self, text: str) -> None:
        forbidden = [
            "intake ticket",
            "simulator",
            "provider",
            "API",
            "后台 memo",
            "package",
            "verify report",
            "证据账本",
            "agent/provider",
            "BLOCKED",
        ]
        for term in forbidden:
            self.assertNotIn(term, text)

    def test_single_text_customer_output_transport(self) -> None:
        source = (ROOT / "scripts" / "telegram_live_bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        def enclosing_function(node: ast.AST) -> str:
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(current, ast.FunctionDef):
                    return current.name
            return ""

        send_message_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_message"
        ]
        self.assertTrue(send_message_calls)
        self.assertEqual({"send_customer_reply"}, {enclosing_function(node) for node in send_message_calls})

        listener_source = (ROOT / "scripts" / "telegram_new_listener.py").read_text(encoding="utf-8")
        self.assertNotIn("sendMessage", listener_source)
        self.assertNotIn(".send_message(", listener_source)

    def test_visual_requirements_are_forced_into_backend_fields(self) -> None:
        session = bridge.default_session("test-chat")
        session["messages"].append(
            {
                "role": "user",
                "text": "我要生成照片和短视频，交付时必须直接给图片、截图和 mp4 预览。",
                "created_at": bridge.now(),
            }
        )
        whiteboard = {"project_summary": "照片和短视频生成工具", "delivery_requirements": [], "acceptance_criteria": []}
        updated = bridge.enforce_backend_updates_from_user_text(session, whiteboard)
        joined_delivery = "\n".join(updated["delivery_requirements"])
        joined_acceptance = "\n".join(updated["acceptance_criteria"])
        self.assertIn("图片", joined_delivery)
        self.assertIn("视频", joined_delivery)
        self.assertIn("截图", joined_delivery)
        self.assertIn("图片", joined_acceptance)
        self.assertTrue(any(event["type"] == "backend_delivery_requirements_updated" for event in session["memory_events"]))

    def test_blocking_questions_are_limited_and_rest_become_open_questions(self) -> None:
        whiteboard = {
            "blocking_questions": ["必须回答 A?", "必须回答 B?", "必须回答 C?"],
            "open_questions": ["可选 D?"],
        }
        normalized = bridge.normalize_question_fields(whiteboard)
        self.assertEqual(["必须回答 A?"], normalized["blocking_questions"])
        self.assertEqual(["可选 D?", "必须回答 B?", "必须回答 C?"], normalized["open_questions"])

    def test_off_topic_guard_rejects_generic_unrelated_reply(self) -> None:
        session = bridge.default_session("test-chat")
        session["messages"].append({"role": "user", "text": "我要做游戏视频高光自动剪辑工具", "created_at": bridge.now()})
        whiteboard = {"project_summary": "游戏视频高光自动剪辑工具"}
        self.assertTrue(bridge.reply_looks_off_topic(session, "请提供公司财务报表和发票信息。", whiteboard))
        self.assertFalse(bridge.reply_looks_off_topic(session, "我会按游戏视频高光剪辑方向推进，输出短视频和高光帧截图。", whiteboard))

    def test_merge_whiteboard_preserves_delivery_and_change_requests(self) -> None:
        previous = {
            "project_summary": "旧摘要",
            "delivery_requirements": ["直接发送视频"],
            "change_requests": ["不要只给路径"],
        }
        incoming = {
            "project_summary": "新摘要",
            "delivery_requirements": ["直接发送截图"],
            "change_requests": ["必须保存后台状态"],
        }
        merged = bridge.merge_whiteboard(previous, incoming)
        self.assertEqual("新摘要", merged["project_summary"])
        self.assertEqual(["直接发送视频", "直接发送截图"], merged["delivery_requirements"])
        self.assertEqual(["不要只给路径", "必须保存后台状态"], merged["change_requests"])

    def test_default_policy_identifies_project_delivery_interface(self) -> None:
        self.assertIn("project generation and delivery workflow", bridge.DEFAULT_CUSTOMER_AGENT_POLICY)
        policy = bridge.read_customer_agent_policy()
        self.assertIn("项目生成与交付团队", policy)
        self.assertIn("前台接口", policy)

    def test_uploaded_attachment_is_recorded_as_project_input(self) -> None:
        session = bridge.default_session("test-chat")
        attachment = {
            "type": "image",
            "file_name": "reference.png",
            "mime_type": "image/png",
            "file_size": 120,
            "caption": "参考这个风格生成页面",
            "local_path": str(ROOT / "examples" / "test_results" / "telegram_live_uploads" / "test-chat" / "reference.png"),
            "created_at": bridge.now(),
        }
        bridge.record_attachments_as_project_input(session, [attachment])
        self.assertEqual(1, len(session["attachments"]))
        facts = "\n".join(session["whiteboard"]["known_facts"])
        self.assertIn("用户上传了图片/参考图作为项目输入", facts)
        self.assertTrue(any(event["type"] == "user_attachment_received" for event in session["memory_events"]))

    def test_combined_requirement_includes_uploaded_attachments(self) -> None:
        session = bridge.default_session("test-chat")
        session["whiteboard"]["project_summary"] = "生成一个参考上传资料的作品集网站"
        session["attachments"].append(
            {
                "type": "document",
                "file_name": "requirements.docx",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "file_size": 512,
                "caption": "这里是详细功能",
                "local_path": str(ROOT / "examples" / "test_results" / "telegram_live_uploads" / "test-chat" / "requirements.docx"),
                "created_at": bridge.now(),
            }
        )
        requirement = bridge.combined_requirement(session)
        self.assertIn("用户上传资料和本地输入", requirement)
        self.assertIn("requirements.docx", requirement)
        self.assertIn("这里是详细功能", requirement)

    def test_project_memory_artifact_includes_uploaded_inputs(self) -> None:
        session = bridge.default_session("test-chat")
        session["attachments"].append(
            {
                "type": "document",
                "file_name": "dataset.csv",
                "mime_type": "text/csv",
                "file_size": 64,
                "caption": "训练样例",
                "local_path": str(ROOT / "examples" / "test_results" / "telegram_live_uploads" / "test-chat" / "dataset.csv"),
                "created_at": bridge.now(),
            }
        )
        artifact = project_memory_md.build_project_memory_artifact(session, ROOT / "PROJECT_MEMORY.md")
        self.assertEqual("dataset.csv", artifact["uploaded_inputs"][0]["file_name"])
        md = project_memory_md.build_project_memory_md(session, ROOT / "project_memory.artifact.json")
        self.assertIn("Uploaded Project Inputs", md)
        self.assertIn("dataset.csv", md)

    def test_summarize_message_attachments_accepts_photos_and_documents(self) -> None:
        message = {
            "caption": "用这个做参考",
            "photo": [
                {"file_id": "small", "file_unique_id": "u1", "file_size": 10},
                {"file_id": "large", "file_unique_id": "u2", "file_size": 50},
            ],
            "document": {
                "file_id": "doc",
                "file_unique_id": "du1",
                "file_name": "brief.pdf",
                "mime_type": "application/pdf",
                "file_size": 100,
            },
        }
        specs = bridge.summarize_message_attachments(message)
        self.assertEqual(["image", "document"], [item["type"] for item in specs])
        self.assertEqual("large", specs[0]["file_id"])
        self.assertEqual("用这个做参考", specs[1]["caption"])

    def test_generation_args_include_required_context_prompt_fields(self) -> None:
        args = bridge.build_generation_args("test-chat", "做一个 VN 助手", ROOT / "examples" / "test_results", "gpt-4.1", 420)
        self.assertEqual(12000, args.prompt_max_chars)
        self.assertFalse(args.use_local_model)
        self.assertTrue(args.allow_provider)
        self.assertTrue(args.use_api)
        command = bridge.generation_subprocess_command(args)
        self.assertIn("--prompt-max-chars", command)
        self.assertIn("12000", command)
        self.assertIn("--allow-network", command)
        self.assertIn("--allow-provider", command)
        self.assertIn("--use-api", command)
        self.assertNotIn("--no-api", command)

    def test_generation_command_uses_no_api_flags_in_simulator_mode(self) -> None:
        args = bridge.build_generation_args("test-chat", "做一个 VN 助手", ROOT / "examples" / "test_results", "gpt-4.1", 420, "simulator")
        command = bridge.generation_subprocess_command(args)
        self.assertIn("--no-network", command)
        self.assertIn("--no-provider", command)
        self.assertIn("--no-api", command)
        self.assertNotIn("--use-api", command)

    def test_greeting_does_not_start_generation_or_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_provider_text = bridge.provider_text
            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider should not be called"))
            try:
                bridge.handle_text(client, "chat-1", "你好", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.provider_text = original_provider_text
            session = bridge.load_session(session_dir, "chat-1")
            self.assertEqual("idle", session["generation"]["status"])
            self.assertFalse(session.get("intake_tickets"))
            self.assertIn("你好", client.messages[-1][1])

    def test_status_query_only_reads_status_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_provider_text = bridge.provider_text
            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider should not be called"))
            try:
                bridge.handle_text(client, "chat-2", "现在怎么样了", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.provider_text = original_provider_text
            session = bridge.load_session(session_dir, "chat-2")
            self.assertEqual("idle", session["generation"]["status"])
            self.assertFalse(session.get("intake_tickets"))
            self.assertIn("当前状态", client.messages[-1][1])
            self.assertIn("可运行项目文件", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_new_project_request_creates_intake_ticket_and_human_backend_memo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            bridge.handle_text(client, "chat-3", "做一个本地图片批量重命名 GUI，要截图和测试报告", session_dir, log_dir, "gpt-test", 60)
            session = bridge.load_session(session_dir, "chat-3")
            self.assertEqual(1, len(session["intake_tickets"]))
            self.assertIsInstance(session.get("active_run"), dict)
            self.assertEqual("simulator_running", session["active_run"]["status"])
            self.assertEqual(session["intake_tickets"][0]["id"], session["active_run"]["ticket_id"])
            self.assertTrue(session["backend_memos"])
            memo = session["backend_memos"][-1]["text"]
            self.assertIn("intake ticket", memo)
            self.assertNotIn("{", memo)
            self.assertIn("方向我记下来了", client.messages[-1][1])
            self.assertIn("本地图片批量重命名", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])
            self.assertNotRegex(client.messages[-1][1], r"[A-Za-z]:\\")

    def test_generation_confirmation_starts_backend_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_provider_text = bridge.provider_text
            original_run_generation_job = bridge.run_generation_job
            called = {}

            def fake_run_generation_job(*args, **kwargs):
                called["ran"] = True
                called["control_id"] = kwargs.get("control_id")
                called["generation_mode"] = kwargs.get("generation_mode")

            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider should not be called"))
            bridge.run_generation_job = fake_run_generation_job
            try:
                bridge.handle_text(client, "chat-4", "做一个本地待办事项应用", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-4", "开始生成", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.provider_text = original_provider_text
                bridge.run_generation_job = original_run_generation_job
            session = bridge.load_session(session_dir, "chat-4")
            self.assertTrue(called["ran"])
            self.assertEqual(session["generation"]["control_id"], called["control_id"])
            self.assertEqual("api", called["generation_mode"])
            self.assertEqual("api_provider", session["generation"]["driver"])
            self.assertIn("正式生成", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_generation_confirmation_writes_backend_control_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_run_generation_job = bridge.run_generation_job
            bridge.run_generation_job = lambda *args, **kwargs: None

            try:
                bridge.handle_text(client, "chat-control", "做一个本地 VN 助手，要时间线和图片预览", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-control", "开始生成", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.run_generation_job = original_run_generation_job

            session = bridge.load_session(session_dir, "chat-control")
            controls = session.get("backend_controls", [])
            start_controls = [row for row in controls if row.get("action") == "start_generation"]
            self.assertEqual(1, len(start_controls))
            self.assertEqual("queued", start_controls[0]["status"])
            self.assertIn("本地 VN 助手", start_controls[0]["payload"]["requirement"])
            self.assertTrue(start_controls[0]["payload"]["control_flags"]["api_allowed"])
            self.assertEqual(start_controls[0]["id"], session["generation"]["control_id"])
            self.assertTrue(any(event["type"] == "backend_control_queued" for event in session["memory_events"]))

    def test_running_project_update_writes_revision_control_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_run_generation_job = bridge.run_generation_job
            bridge.run_generation_job = lambda *args, **kwargs: None

            try:
                bridge.handle_text(client, "chat-revise", "做一个本地图片生成工具", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-revise", "开始生成", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-revise", "背景和立绘必须分开两个入口", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.run_generation_job = original_run_generation_job

            session = bridge.load_session(session_dir, "chat-revise")
            controls = session.get("backend_controls", [])
            revision_controls = [row for row in controls if row.get("action") == "revise_generation_scope"]
            self.assertEqual(1, len(revision_controls))
            self.assertIn("背景和立绘", revision_controls[0]["payload"]["latest_user_text"])
            self.assertIn("背景和立绘", "\n".join(revision_controls[0]["payload"]["whiteboard"]["change_requests"]))

    def test_delivery_ready_depends_only_on_truth_ledger_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            artifact_dir = pathlib.Path(temp_dir) / "artifacts"
            artifact_dir.mkdir()
            package = artifact_dir / "delivery.zip"
            screenshot = artifact_dir / "preview.png"
            verify_report = artifact_dir / "verify_report.json"
            package.write_bytes(b"zip")
            screenshot.write_bytes(b"png")
            verify_report.write_text('{"passed": true}\n', encoding="utf-8")
            client = FakeTelegramClient()
            session = bridge.default_session("chat-5")
            bridge.append_truth_ledger(session_dir, session, "package", "package exists", evidence_ref=str(package), data={"artifact": "package"})
            bridge.append_truth_ledger(session_dir, session, "screenshot", "screenshot exists", evidence_ref=str(screenshot), data={"artifact": "screenshot"})
            bridge.save_session(session_dir, session)
            state = bridge.delivery_evidence_state(bridge.read_truth_ledger(session_dir, "chat-5"))
            self.assertFalse(state["delivery_ready"])
            self.assertIn("verify_report", state["missing"])
            bridge.append_truth_ledger(session_dir, session, "verify_report", "verify report exists", evidence_ref=str(verify_report), data={"artifact": "verify_report"})
            state = bridge.delivery_evidence_state(bridge.read_truth_ledger(session_dir, "chat-5"))
            self.assertFalse(state["delivery_ready"])
            self.assertIn("verify_passed", state["missing"])
            bridge.append_truth_ledger(session_dir, session, "verify_passed", "verification passed", evidence_ref=str(verify_report), data={"artifact": "verify_passed", "verify_passed": True})
            bridge.save_session(session_dir, session)
            state = bridge.maybe_auto_deliver_if_ready(client, "chat-5", session_dir)
            self.assertTrue(state["delivery_ready"])
            self.assertTrue(state["sent_record"])
            self.assertEqual(1, len(client.photos))
            self.assertEqual(2, len(client.documents))
            self.assertIn("可交付材料已经齐了", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_pending_decision_asks_one_question_and_pauses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-decision")
            session["whiteboard"]["blocking_questions"] = ["背景和立绘要用同一个模型吗？", "是否需要导出脚本？"]
            session["active_run"] = {"id": "run-chat-decision-1", "status": "simulator_running"}
            bridge.save_session(session_dir, session)
            bridge.handle_text(client, "chat-decision", "开始生成", session_dir, log_dir, "gpt-test", 60)
            session = bridge.load_session(session_dir, "chat-decision")
            self.assertEqual("waiting_decision", session["active_run"]["status"])
            self.assertIn("背景和立绘要用同一个模型吗", client.messages[-1][1])
            self.assertNotIn("是否需要导出脚本", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_provider_escalation_requires_blocked_retry_exhausted_and_explicit_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            session = bridge.default_session("chat-6")
            bridge.save_session(session_dir, session)
            classification = bridge.classify_customer_message("升级给 agent", session)
            self.assertFalse(bridge.provider_escalation_allowed(session_dir, "chat-6", classification))
            bridge.append_truth_ledger(session_dir, session, "blocked", "流程阻断", status="BLOCKED", data={"artifact": "blocked"})
            bridge.save_session(session_dir, session)
            self.assertFalse(bridge.provider_escalation_allowed(session_dir, "chat-6", classification))
            session["active_run"] = {"id": "run-chat-6-1", "local_retry_exhausted": True}
            bridge.save_session(session_dir, session)
            self.assertTrue(bridge.provider_escalation_allowed(session_dir, "chat-6", classification))

    def test_generation_failure_facts_hide_internal_parameter_names(self) -> None:
        facts = bridge.safe_generation_failure_facts("做一个 VN 助手", AttributeError("'Namespace' object has no attribute 'prompt_max_chars'"))
        self.assertEqual("generation_bridge_configuration_error", facts["error_category"])
        self.assertNotIn("prompt_max_chars", facts["user_visible_cause"])
        self.assertTrue(facts["technical_error_logged"])

    def test_generation_failure_facts_classify_context_budget_errors(self) -> None:
        facts = bridge.safe_generation_failure_facts("做一个 VN 助手", RuntimeError("context prompt quality failed: prompt exceeds max_chars: 6966>6000"))
        self.assertEqual("context_prompt_budget_error", facts["error_category"])
        self.assertIn("上下文预算", facts["user_visible_cause"])

    def test_generation_progress_text_does_not_claim_specific_stage(self) -> None:
        text = bridge.generation_progress_text(120)
        self.assertIn("仍在生成", text)
        self.assertIn("尚未验证", text)
        self.assertNotIn("整体进度正常", text)
        self.assertNotIn("已进入图片生成", text)


if __name__ == "__main__":
    unittest.main()
