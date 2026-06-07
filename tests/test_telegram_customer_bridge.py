from __future__ import annotations

import ast
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge
import scripts.legacy_provider_pipeline as legacy_provider_pipeline
import scripts.project_memory_md as project_memory_md
import scripts.local_packager as local_packager


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


class InlineThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


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

    def test_local_image_model_requirement_records_critical_question(self) -> None:
        session = bridge.default_session("test-chat")
        session["messages"].append(
            {
                "role": "user",
                "text": "VN 项目的背景和立绘都必须用本地图片模型真实生成",
                "created_at": bridge.now(),
            }
        )
        original_discovery = bridge.local_image_model_discovery.critical_questions_for_text
        bridge.local_image_model_discovery.critical_questions_for_text = lambda text, root=None: (
            ["本地图片生成准备用哪个后端：ComfyUI、AUTOMATIC1111，还是直接给 SD_MODEL_DIR/模型目录？"],
            {"available": False, "checked": [{"kind": "ComfyUI", "status": "missing"}], "backends": []},
        )
        try:
            updated = bridge.enforce_backend_updates_from_user_text(session, {"project_summary": "VN 项目"})
        finally:
            bridge.local_image_model_discovery.critical_questions_for_text = original_discovery

        self.assertEqual([], updated["blocking_questions"])
        self.assertIn("本地图片", "\n".join(updated["critical_questions"]))
        self.assertIn("降级预览不算图片验收通过", "\n".join(updated["acceptance_criteria"]))
        self.assertIn("本地图片模型", "\n".join(updated["known_facts"]))
        self.assertTrue(any(event["type"] == "local_image_model_capability_checked" for event in session["memory_events"]))
        self.assertTrue(any(event["type"] == "capability_strategy_updated" for event in session["memory_events"]))

    def test_capability_strategy_records_generic_advanced_routes_and_obvious_choices(self) -> None:
        session = bridge.default_session("test-chat")
        session["messages"].append(
            {
                "role": "user",
                "text": "做一个本地任务自动化系统，要流程状态、自动生成报告、保存历史，最好有可运行界面",
                "created_at": bridge.now(),
            }
        )

        updated = bridge.enforce_backend_updates_from_user_text(session, {"project_summary": "任务自动化系统"})

        targets = "\n".join(updated["capability_research_targets"])
        self.assertIn("结构化流程/关系建模", targets)
        self.assertIn("内容生成能力", targets)
        self.assertIn("Hosted provider/API backend", targets)
        self.assertIn("SQLite", targets)
        self.assertIn("生成能力优先走本地模型、外部高级 API", "\n".join(updated["critical_questions"]))
        self.assertIn("核心能力", "\n".join(updated["known_facts"]))

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

    def test_pre_send_guard_hides_internal_evidence_keys(self) -> None:
        text = bridge.pre_send_guard("missing package, screenshot, verify_report")

        self.assertNotIn("package", text)
        self.assertNotIn("screenshot", text)
        self.assertNotIn("verify_report", text)
        self.assertIn("可运行项目文件", text)
        self.assertIn("效果预览", text)
        self.assertIn("测试结论", text)

    def test_pre_send_guard_does_not_replace_chinese_slash_phrases(self) -> None:
        text = bridge.pre_send_guard("提取玩家视角/鼠标/键盘动作，用于行为时间线分析。")

        self.assertIn("视角/鼠标/键盘动作", text)
        self.assertNotIn("本地工作区记录", text)

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

    def test_status_reply_can_use_local_model_without_generation_decision(self) -> None:
        session = bridge.default_session("test-chat")
        session["whiteboard"]["project_summary"] = "做一个本地任务管理器"
        original_local_call = bridge.local_model_router.call_text_task
        original_provider_text = bridge.provider_text
        try:
            calls: list[str] = []

            def fake_local(task, system, prompt, timeout):
                calls.append(task)
                return {"ok": True, "provider": "test-local", "text": "当前还在处理，补充会进入同一个项目上下文。"}

            bridge.local_model_router.call_text_task = fake_local
            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be needed"))

            text = bridge.provider_user_message(
                event="status_requested",
                session=session,
                facts={"generation": {"status": "running"}, "evidence_state": {"missing": ["package"]}},
                model="gpt-real",
                timeout=30,
            )
        finally:
            bridge.local_model_router.call_text_task = original_local_call
            bridge.provider_text = original_provider_text

        self.assertEqual(["customer_status"], calls)
        self.assertIn("当前还在处理", text)
        self.assert_public_reply_style(text)

    def test_model_frontdesk_generation_decision_does_not_use_public_reply_local_task(self) -> None:
        session = bridge.default_session("test-chat")
        original_local_call = bridge.local_model_router.call_text_task
        original_provider_text = bridge.provider_text
        try:
            bridge.local_model_router.call_text_task = lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("public reply local model must not decide generation")
            )
            bridge.provider_text = lambda *args, **kwargs: (
                '{"reply":"我按这个方向开始做第一版。","action":"start_generation",'
                '"whiteboard":{"project_summary":"做一个本地任务管理器","ready_to_generate":true,'
                '"known_facts":[],"default_assumptions":[],"first_version_plan":[],"blocking_questions":[],'
                '"open_questions":[],"user_rules":[],"acceptance_criteria":["可运行"],"change_requests":[],'
                '"delivery_requirements":["交付项目包"],"decision_log":[]}}'
            )

            reply, whiteboard, action = bridge.customer_service_reply(session, model="gpt-real", timeout=30)
        finally:
            bridge.local_model_router.call_text_task = original_local_call
            bridge.provider_text = original_provider_text

        self.assertEqual("start_generation", action)
        self.assertIn("本地任务管理器", whiteboard["project_summary"])
        self.assertIn("第一版", reply)

    def test_model_frontdesk_repairs_malformed_json_without_leaking_raw_object(self) -> None:
        session = bridge.default_session("test-chat")
        session["messages"].append({"role": "user", "text": "做一个 CS2 demo 鉴挂工具", "created_at": bridge.now()})
        original_provider_text = bridge.provider_text
        try:
            bridge.provider_text = lambda *args, **kwargs: (
                '{"reply":"我按 CS2 demo 鉴挂工具开始做第一版，会解析 demo、提取视角/鼠标/键盘动作并做可视化。",'
                '"action":"start_generation","whiteboard":{"project_summary":"CS2 demo 鉴挂工具"'
            )

            reply, whiteboard, action = bridge.customer_service_reply(session, model="gpt-real", timeout=30)
        finally:
            bridge.provider_text = original_provider_text

        self.assertEqual("start_generation", action)
        self.assertIn("CS2 demo", reply)
        self.assertIn("视角/鼠标/键盘动作", reply)
        self.assertNotIn('{"reply"', reply)
        self.assertNotIn('"whiteboard"', reply)
        self.assertIn("CS2 demo 鉴挂工具", whiteboard["project_summary"])

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
        command = legacy_provider_pipeline.generation_subprocess_command(args, root=ROOT)
        self.assertIn("--prompt-max-chars", command)
        self.assertIn("12000", command)
        self.assertIn("--allow-network", command)
        self.assertIn("--allow-provider", command)
        self.assertIn("--use-api", command)
        self.assertNotIn("--no-api", command)

    def test_generation_command_does_not_use_no_api_flags_in_simulator_mode(self) -> None:
        args = bridge.build_generation_args("test-chat", "做一个 VN 助手", ROOT / "examples" / "test_results", "gpt-4.1", 420, "simulator")
        command = legacy_provider_pipeline.generation_subprocess_command(args, root=ROOT)
        self.assertIn("--allow-network", command)
        self.assertIn("--allow-provider", command)
        self.assertIn("--use-api", command)
        self.assertNotIn("--no-network", command)
        self.assertNotIn("--no-provider", command)
        self.assertNotIn("--no-api", command)

    def test_greeting_does_not_start_generation_or_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_provider_text = bridge.provider_text
            original_local_call = bridge.local_model_router.call_text_task
            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider should not be called"))
            bridge.local_model_router.call_text_task = lambda task, *args, **kwargs: {
                "ok": True,
                "provider": "test-local",
                "text": "模型问候回复：我在；当前是空会话，直接发项目目标和约束即可。",
            }
            try:
                bridge.handle_text(client, "chat-1", "你好", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.provider_text = original_provider_text
                bridge.local_model_router.call_text_task = original_local_call
            session = bridge.load_session(session_dir, "chat-1")
            self.assertEqual("idle", session["generation"]["status"])
            self.assertFalse(session.get("intake_tickets"))
            self.assertNotIn("你好，我在", client.messages[-1][1])
            self.assertNotIn("我已记下", client.messages[-1][1])
            self.assertNotIn("收到", client.messages[-1][1])
            self.assertIn("模型问候回复", client.messages[-1][1])
            self.assertEqual("provider_user_message", session["messages"][-1]["source"])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_status_query_only_reads_status_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_provider_text = bridge.provider_text
            original_local_call = bridge.local_model_router.call_text_task
            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider should not be called"))
            bridge.local_model_router.call_text_task = lambda task, *args, **kwargs: {
                "ok": True,
                "provider": "test-local",
                "text": "模型状态回复：当前没有正在运行的后台任务；可运行项目文件、效果预览和测试结论还没有交付证据。",
            }
            try:
                bridge.handle_text(client, "chat-2", "现在怎么样了", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.provider_text = original_provider_text
                bridge.local_model_router.call_text_task = original_local_call
            session = bridge.load_session(session_dir, "chat-2")
            self.assertEqual("idle", session["generation"]["status"])
            self.assertFalse(session.get("intake_tickets"))
            self.assertIn("模型状态回复", client.messages[-1][1])
            self.assertIn("可运行项目文件", client.messages[-1][1])
            self.assertEqual("provider_user_message", session["messages"][-1]["source"])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_new_project_request_creates_intake_ticket_and_waits_for_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_start = bridge.start_agent_generation
            called = {}

            def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["reason"] = reason
                called["announce_start"] = announce_start
                session = bridge.load_session(session_dir_arg, chat_id)
                bridge.update_active_run_status(session, "running", driver="agent_conversation_loop")
                session["generation"] = {"status": "running", "driver": "agent_conversation_loop"}
                bridge.save_session(session_dir_arg, session)

            bridge.start_agent_generation = fake_start
            try:
                bridge.handle_text(client, "chat-3", "做一个本地图片批量重命名 GUI，要截图和测试报告", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.start_agent_generation = original_start
            session = bridge.load_session(session_dir, "chat-3")
            self.assertEqual(1, len(session["intake_tickets"]))
            self.assertIsInstance(session.get("active_run"), dict)
            self.assertEqual("intake_open", session["active_run"]["status"])
            self.assertNotEqual("running", session["generation"]["status"])
            self.assertTrue(session["generation_start_waiting"])
            self.assertEqual({}, called)
            self.assertEqual(session["intake_tickets"][0]["id"], session["active_run"]["ticket_id"])
            self.assertTrue(session["backend_memos"])
            memo = "\n".join(item["text"] for item in session["backend_memos"])
            self.assertIn("模型测试回复", memo)
            self.assertNotIn("{", memo)
            self.assertIn("周衡", client.messages[-1][1])
            self.assertIn("团队先不急着开工", client.messages[-1][1])
            self.assertNotIn("我已记下", client.messages[-1][1])
            self.assertNotIn("收到，方向", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])
            self.assertNotRegex(client.messages[-1][1], r"[A-Za-z]:\\")
            agent_events = bridge.agent_session_path(session_dir, "chat-3").read_text(encoding="utf-8")
            self.assertIn("本地图片批量重命名", agent_events)
            self.assertIn("model_frontdesk_turn", agent_events)

    def test_generation_confirmation_starts_backend_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_provider_text = bridge.provider_text
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_thread = bridge.threading.Thread
            called = {}

            def fake_run_agent_loop(*, session_path, project_dir, model, timeout, max_turns):
                called["ran"] = True
                called["session_path"] = str(session_path)
                pathlib.Path(project_dir).mkdir(parents=True, exist_ok=True)
                (pathlib.Path(project_dir) / "README.md").write_text("# Todo\n", encoding="utf-8")
                (pathlib.Path(project_dir) / "app.py").write_text("print('todo')\n", encoding="utf-8")
                (pathlib.Path(project_dir) / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python app.py\n", encoding="utf-8")
                (pathlib.Path(project_dir) / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: PASS\n", encoding="utf-8")
                manifest = local_packager.package_project(pathlib.Path(project_dir), startup_command="python app.py")
                return {"status": manifest["status"], "manifest": manifest, "manifest_path": manifest["manifest_path"]}

            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider should not be called"))
            bridge.agent_conversation_loop.run_agent_loop = fake_run_agent_loop
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-4", "做一个本地待办事项应用", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-4", "开始生成", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.provider_text = original_provider_text
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.threading.Thread = original_thread
            session = bridge.load_session(session_dir, "chat-4")
            self.assertTrue(called["ran"])
            self.assertIn("agent_session.jsonl", called["session_path"])
            self.assertEqual("agent_conversation_loop_fallback", session["generation"]["driver"])
            self.assertTrue(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))
            self.assert_public_reply_style(client.messages[-1][1])

    def test_generation_confirmation_does_not_require_backend_control_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_thread = bridge.threading.Thread

            def fake_run_agent_loop(*, session_path, project_dir, model, timeout, max_turns):
                pathlib.Path(project_dir).mkdir(parents=True, exist_ok=True)
                (pathlib.Path(project_dir) / "README.md").write_text("# VN\n", encoding="utf-8")
                (pathlib.Path(project_dir) / "app.py").write_text("print('vn')\n", encoding="utf-8")
                (pathlib.Path(project_dir) / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python app.py\n", encoding="utf-8")
                (pathlib.Path(project_dir) / "DELIVERY_NOTES.md").write_text("# Delivery\n\ndelivery_status: WARNING\n", encoding="utf-8")
                manifest = local_packager.package_project(pathlib.Path(project_dir), startup_command="")
                return {"status": manifest["status"], "manifest": manifest, "manifest_path": manifest["manifest_path"]}

            bridge.agent_conversation_loop.run_agent_loop = fake_run_agent_loop
            bridge.threading.Thread = InlineThread

            try:
                bridge.handle_text(client, "chat-control", "做一个本地 VN 助手，要时间线和图片预览", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-control", "开始生成", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.threading.Thread = original_thread

            session = bridge.load_session(session_dir, "chat-control")
            controls = session.get("backend_controls", [])
            start_controls = [row for row in controls if row.get("action") == "agent_loop_started"]
            self.assertEqual(0, len(start_controls))
            self.assertEqual("agent_conversation_loop_fallback", session["generation"]["driver"])
            self.assertIn("agent_session.jsonl", session["generation"]["agent_session_path"])
            self.assertFalse(any(path.name == "final_project_bundle.zip" for _, path, _ in client.documents))
            self.assertIn(session["generation"]["status"].upper(), {"BLOCKED", "REWORK"})

    def test_startup_auto_starts_pending_intake(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-startup")
            ticket = bridge.create_intake_ticket(session_dir, session, "做一个本地 VN 助手")
            bridge.create_active_run(session, ticket, "做一个本地 VN 助手")
            bridge.save_session(session_dir, session)
            original_start = bridge.start_agent_generation

            def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                next_session = bridge.load_session(session_dir_arg, chat_id)
                bridge.update_active_run_status(next_session, "running", driver="agent_conversation_loop")
                next_session["generation"] = {"status": "running", "driver": "agent_conversation_loop"}
                bridge.save_session(session_dir_arg, next_session)

            bridge.start_agent_generation = fake_start
            try:
                started = bridge.auto_start_pending_intakes(client, session_dir, log_dir, "gpt-test", 60, allowed_chat="chat-startup", generation_mode="api")
            finally:
                bridge.start_agent_generation = original_start

            session = bridge.load_session(session_dir, "chat-startup")
            self.assertEqual(1, started)
            self.assertEqual("running", session["generation"]["status"])
            controls = [row for row in session.get("backend_controls", []) if row.get("action") == "agent_loop_started"]
            self.assertEqual(0, len(controls))

    def test_running_project_update_writes_revision_control_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_thread = bridge.threading.Thread

            def fake_run_agent_loop(*, session_path, project_dir, model, timeout, max_turns):
                return {"status": "max_turns_reached", "manifest": {}, "manifest_path": ""}

            bridge.agent_conversation_loop.run_agent_loop = fake_run_agent_loop
            bridge.threading.Thread = InlineThread

            try:
                bridge.handle_text(client, "chat-revise", "做一个本地图片生成工具", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-revise", "开始生成", session_dir, log_dir, "gpt-test", 60)
                bridge.handle_text(client, "chat-revise", "背景和立绘必须分开两个入口", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.threading.Thread = original_thread

            events = bridge.agent_session_path(session_dir, "chat-revise").read_text(encoding="utf-8")
            self.assertIn("背景和立绘", events)

    def test_completed_project_update_waits_for_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-restart")
            session["messages"].append({"role": "user", "text": "做一个本地 VN 助手", "created_at": bridge.now()})
            session["whiteboard"]["project_summary"] = "做一个本地 VN 助手"
            session["generation"] = {"status": "ready_with_warnings", "driver": "agent_conversation_loop"}
            bridge.save_session(session_dir, session)
            original_start = bridge.start_agent_generation
            called = {}

            def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["reason"] = reason
                next_session = bridge.load_session(session_dir_arg, chat_id)
                bridge.update_active_run_status(next_session, "running", driver="agent_conversation_loop")
                next_session["generation"] = {"status": "running", "driver": "agent_conversation_loop"}
                bridge.save_session(session_dir_arg, next_session)

            bridge.start_agent_generation = fake_start
            try:
                bridge.handle_text(client, "chat-restart", "增加前端界面和图片预览", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.start_agent_generation = original_start

            session = bridge.load_session(session_dir, "chat-restart")
            self.assertNotEqual("running", session["generation"]["status"])
            self.assertEqual({}, called)
            self.assertTrue(session["generation_start_waiting"])
            self.assertIn("周衡", client.messages[-1][1])
            self.assertIn("团队先不急着开工", client.messages[-1][1])
            self.assertNotIn("我已记下", client.messages[-1][1])
            self.assertNotIn("收到，方向", client.messages[-1][1])
            self.assertIn("增加前端界面", bridge.agent_session_path(session_dir, "chat-restart").read_text(encoding="utf-8"))

    def test_project_attachment_waits_for_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            upload_dir = pathlib.Path(temp_dir) / "uploads"
            client = FakeTelegramClient()
            original_download = bridge.download_message_attachments
            original_start = bridge.start_agent_generation
            called = {}

            def fake_download(client_arg, chat_id, message, upload_dir_arg):
                path = pathlib.Path(upload_dir_arg) / str(chat_id) / "brief.txt"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("VN project brief", encoding="utf-8")
                return (
                    [
                        {
                            "type": "document",
                            "file_name": "brief.txt",
                            "mime_type": "text/plain",
                            "file_size": 16,
                            "caption": "作为项目需求",
                            "local_path": str(path),
                            "created_at": bridge.now(),
                        }
                    ],
                    [],
                )

            def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                called["reason"] = reason
                next_session = bridge.load_session(session_dir_arg, chat_id)
                bridge.update_active_run_status(next_session, "running", driver="agent_conversation_loop")
                next_session["generation"] = {"status": "running", "driver": "agent_conversation_loop"}
                bridge.save_session(session_dir_arg, next_session)

            bridge.download_message_attachments = fake_download
            bridge.start_agent_generation = fake_start
            try:
                bridge.handle_attachment_message(
                    client,
                    "chat-attachment",
                    {"document": {"file_id": "doc", "file_name": "brief.txt"}, "caption": "作为项目需求"},
                    session_dir,
                    log_dir,
                    upload_dir,
                    "gpt-test",
                    60,
                )
            finally:
                bridge.download_message_attachments = original_download
                bridge.start_agent_generation = original_start

            session = bridge.load_session(session_dir, "chat-attachment")
            self.assertNotEqual("running", session["generation"]["status"])
            self.assertEqual(1, len(session["attachments"]))
            self.assertEqual({}, called)
            self.assertTrue(session["generation_start_waiting"])
            self.assertIn("周衡", client.messages[-1][1])
            self.assertIn("许楠", client.messages[-1][1])
            self.assertIn("做成空壳", client.messages[-1][1])

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
            self.assertEqual(1, len(client.documents))
            self.assertIn("乔安完成了交付复核", client.messages[-1][1])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_pending_decision_asks_one_question_and_pauses(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-decision")
            session["whiteboard"]["blocking_questions"] = ["背景和立绘要用同一个模型吗？", "是否需要导出脚本？"]
            session["active_run"] = {"id": "run-chat-decision-1", "status": "intake_open"}
            bridge.save_session(session_dir, session)
            original_loop = bridge.agent_conversation_loop.run_agent_loop
            original_thread = bridge.threading.Thread
            bridge.agent_conversation_loop.run_agent_loop = lambda **kwargs: {"status": "max_turns_reached", "manifest": {}, "manifest_path": ""}
            bridge.threading.Thread = InlineThread
            try:
                bridge.handle_text(client, "chat-decision", "开始生成", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.agent_conversation_loop.run_agent_loop = original_loop
                bridge.threading.Thread = original_thread
            session = bridge.load_session(session_dir, "chat-decision")
            self.assertNotEqual("waiting_decision", session["active_run"]["status"])
            self.assertIn("agent_conversation_loop", session["generation"]["driver"])
            self.assert_public_reply_style(client.messages[-1][1])

    def test_provider_escalation_requires_blocked_retry_exhausted_and_explicit_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            session = bridge.default_session("chat-6")
            bridge.save_session(session_dir, session)
            classification = bridge.classify_customer_message("升级给 agent", session)
            self.assertTrue(bridge.provider_escalation_allowed(session_dir, "chat-6", classification))
            bridge.append_truth_ledger(session_dir, session, "blocked", "流程阻断", status="BLOCKED", data={"artifact": "blocked"})
            bridge.save_session(session_dir, session)
            self.assertTrue(bridge.provider_escalation_allowed(session_dir, "chat-6", classification))
            session["active_run"] = {"id": "run-chat-6-1", "local_retry_exhausted": True}
            bridge.save_session(session_dir, session)
            self.assertTrue(bridge.provider_escalation_allowed(session_dir, "chat-6", classification))

    def test_status_classification_handles_natural_progress_question(self) -> None:
        session = bridge.default_session("chat-status")
        classification = bridge.classify_customer_message("后台那边现在有动静吗", session)

        self.assertEqual("status_query", classification["intent"])
        self.assertEqual("status_question", classification["reason"])

    def test_status_classification_handles_still_working_question(self) -> None:
        session = bridge.default_session("chat-status-working")
        session["generation"] = {"status": "max_turns_reached"}
        session["whiteboard"]["project_summary"] = "做一个 VN 项目助手"

        classification = bridge.classify_customer_message("还在做吗", session)

        self.assertEqual("status_query", classification["intent"])
        self.assertEqual("status_question", classification["reason"])
        self.assertEqual(0, bridge.substantive_user_turn_count({"messages": [{"role": "user", "text": "还在做吗"}]}))

    def test_status_query_does_not_update_project_or_restart_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-status-no-restart")
            session["whiteboard"]["project_summary"] = "做一个 VN 项目助手"
            session["generation"] = {"status": "max_turns_reached", "driver": "agent_generated_pipeline"}
            bridge.save_session(session_dir, session)
            original_start = bridge.start_agent_generation
            original_provider_text = bridge.provider_text
            original_local_call = bridge.local_model_router.call_text_task
            bridge.start_agent_generation = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("status query must not restart generation"))
            bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("status query should use public reply model"))
            bridge.local_model_router.call_text_task = lambda task, *args, **kwargs: {
                "ok": True,
                "provider": "test-local",
                "text": "模型状态回复：后台没有正在运行的任务；这条状态询问不会写成新需求。",
            }
            try:
                bridge.handle_text(client, "chat-status-no-restart", "还在做吗", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.start_agent_generation = original_start
                bridge.provider_text = original_provider_text
                bridge.local_model_router.call_text_task = original_local_call

            saved = bridge.load_session(session_dir, "chat-status-no-restart")
            self.assertEqual("max_turns_reached", saved["generation"]["status"])
            self.assertNotIn("还在做吗", str(saved["whiteboard"].get("known_facts", [])))
            self.assertIn("模型状态回复", client.messages[-1][1])
            self.assertEqual("provider_user_message", saved["messages"][-1]["source"])
            self.assertEqual("status_requested", saved["messages"][-1]["event"])

    def test_status_reply_uses_public_reply_model_for_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-status-package")
            session["active_run"] = {"status": "delivered", "package_path": "final_project_bundle.zip"}
            bridge.save_session(session_dir, session)
            original_local_call = bridge.local_model_router.call_text_task
            original_provider_text = bridge.provider_text
            try:
                called: list[str] = []

                def fake_local(task, *args, **kwargs):
                    called.append(task)
                    return {
                        "ok": True,
                        "provider": "test-local",
                        "text": "模型状态回复：可运行项目文件已经生成；预览和测试结论仍要补齐。",
                    }

                bridge.local_model_router.call_text_task = fake_local
                bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be needed"))
                bridge.handle_text(client, "chat-status-package", "还在做吗", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.local_model_router.call_text_task = original_local_call
                bridge.provider_text = original_provider_text

            saved = bridge.load_session(session_dir, "chat-status-package")
            self.assertEqual(["customer_status"], called)
            self.assertIn("可运行项目文件已经生成", client.messages[-1][1])
            self.assertNotIn("没有可运行结果", client.messages[-1][1])
            self.assertEqual("provider_user_message", saved["messages"][-1]["source"])

    def test_greeting_with_existing_failed_project_is_short_status_not_old_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-greeting-existing")
            session["whiteboard"]["project_summary"] = "本地可运行的 VN 项目助手，具备故事时间线梳理、可视化和 AI 生成背景/立绘图片等能力"
            session["generation"] = {"status": "max_turns_reached", "driver": "agent_generated_pipeline"}
            bridge.save_session(session_dir, session)
            original_local_call = bridge.local_model_router.call_text_task
            original_provider_text = bridge.provider_text
            try:
                bridge.local_model_router.call_text_task = lambda task, *args, **kwargs: {
                    "ok": True,
                    "provider": "test-local",
                    "text": "模型问候回复：我在；当前没有后台任务，继续补充会进入同一个上下文。",
                }
                bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be needed"))

                bridge.handle_text(client, "chat-greeting-existing", "你好", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.local_model_router.call_text_task = original_local_call
                bridge.provider_text = original_provider_text

            saved = bridge.load_session(session_dir, "chat-greeting-existing")
            self.assertEqual("max_turns_reached", saved["generation"]["status"])
            self.assertNotIn("VN 项目助手", client.messages[-1][1])
            self.assertIn("模型问候回复", client.messages[-1][1])
            self.assertEqual("provider_user_message", saved["messages"][-1]["source"])
            self.assertEqual("greeting", saved["messages"][-1]["event"])

    def test_greeting_with_delivered_project_uses_model_not_frontdesk_composer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            session = bridge.default_session("chat-greeting-delivered")
            session["whiteboard"]["project_summary"] = "本地任务工具"
            session["generation"] = {"status": "ready_with_warnings", "package_path": "final_project_bundle.zip"}
            session["active_run"] = {"status": "delivered", "package_path": "final_project_bundle.zip"}
            bridge.save_session(session_dir, session)
            original_local_call = bridge.local_model_router.call_text_task
            original_provider_text = bridge.provider_text
            try:
                called: list[str] = []

                def fake_local(task, *args, **kwargs):
                    called.append(task)
                    return {
                        "ok": True,
                        "provider": "test-local",
                        "text": "模型问候回复：我在；项目包已经生成，现在没有新的后台任务。",
                    }

                bridge.local_model_router.call_text_task = fake_local
                bridge.provider_text = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be needed"))
                bridge.handle_text(client, "chat-greeting-delivered", "你好", session_dir, log_dir, "gpt-test", 60)
            finally:
                bridge.local_model_router.call_text_task = original_local_call
                bridge.provider_text = original_provider_text

            saved = bridge.load_session(session_dir, "chat-greeting-delivered")
            self.assertEqual(["customer_public_reply"], called)
            self.assertIn("项目包已经生成", client.messages[-1][1])
            self.assertIn("没有新的后台任务", client.messages[-1][1])
            self.assertNotIn("当前有项目上下文记录着", client.messages[-1][1])
            self.assertEqual("provider_user_message", saved["messages"][-1]["source"])

    def test_optional_local_classifier_handles_ambiguous_message_without_generation_confirmation(self) -> None:
        session = bridge.default_session("chat-classify")
        session["whiteboard"]["project_summary"] = "做一个 VN 项目助手"
        original_enabled = bridge.local_model_router.task_enabled
        original_call = bridge.local_model_router.call_json_task
        try:
            bridge.local_model_router.task_enabled = lambda task: task == "customer_classification"
            bridge.local_model_router.call_json_task = lambda *args, **kwargs: {
                "ok": True,
                "json": {"intent": "status_query", "confidence": 0.82, "reason": "用户在问后台动向"},
            }

            classification = bridge.classify_customer_message("后台有推进吗", session)
        finally:
            bridge.local_model_router.task_enabled = original_enabled
            bridge.local_model_router.call_json_task = original_call

        self.assertEqual("status_query", classification["intent"])
        self.assertEqual("local_model", classification["source"])

    def test_optional_local_classifier_cannot_invent_generation_confirmation(self) -> None:
        session = bridge.default_session("chat-classify")
        original_enabled = bridge.local_model_router.task_enabled
        original_call = bridge.local_model_router.call_json_task
        try:
            bridge.local_model_router.task_enabled = lambda task: task == "customer_classification"
            bridge.local_model_router.call_json_task = lambda *args, **kwargs: {
                "ok": True,
                "json": {"intent": "generation_confirmation", "confidence": 0.9, "reason": "bad model guess"},
            }

            classification = bridge.classify_customer_message("这个方向听起来还行", session)
        finally:
            bridge.local_model_router.task_enabled = original_enabled
            bridge.local_model_router.call_json_task = original_call

        self.assertNotEqual("generation_confirmation", classification["intent"])

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
