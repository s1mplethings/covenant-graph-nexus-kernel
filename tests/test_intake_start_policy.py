from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as backend_dialogue_loop
import scripts.local_packager as local_packager
import scripts.telegram_live_bridge as bridge


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.documents: list[tuple[str, pathlib.Path, str]] = []
        self.actions: list[tuple[str, str]] = []

    def send_message(self, chat_id: int | str, text: str) -> bool:
        self.messages.append((str(chat_id), text))
        return True

    def send_document(self, chat_id: int | str, path: pathlib.Path, caption: str = "") -> bool:
        self.documents.append((str(chat_id), pathlib.Path(path), caption))
        return True

    def send_chat_action(self, chat_id: int | str, action: str) -> None:
        self.actions.append((str(chat_id), action))


class IntakeStartPolicyTests(unittest.TestCase):
    def test_game_analysis_request_with_questions_can_auto_start_scaffold(self) -> None:
        text = "我想要一个项目可以通过csgo2的demo分析鼠标键盘动作和视觉信息，用来鉴挂"
        analysis = backend_dialogue_loop.summarize_locally({"whiteboard": {}}, text, reason="new_project_request")

        self.assertTrue(analysis["missing_required_inputs"])
        self.assertEqual((True, "actionable_project_request"), bridge.should_auto_start_generation({}, analysis, text))

        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_start = bridge.start_agent_generation
            called = {"started": False}

            def fake_start(*args, **kwargs):
                called["started"] = True

            bridge.start_agent_generation = fake_start
            try:
                bridge.handle_text(client, "chat-cs2", text, session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start

            session = bridge.load_session(session_dir, "chat-cs2")

        self.assertTrue(called["started"])
        self.assertFalse(session.get("generation_start_waiting", False))
        reply = client.messages[-1][1]
        self.assertNotIn("不会马上开工", reply)

    def test_direct_image_generation_requirement_is_not_start_command(self) -> None:
        text = "帮我做一个本地可运行的 VN 项目助手，是正经直接生成图片的"
        analysis = {
            "needs_direction_confirmation": True,
            "soft_questions": ["本地模型地址是什么？"],
            "critical_questions": ["桌面界面形态是什么？"],
            "missing_required_inputs": [],
            "confidence": 0.9,
        }

        self.assertFalse(bridge.explicit_start_requested(text))
        self.assertEqual((True, "actionable_project_request"), bridge.should_auto_start_generation({}, analysis, text))

    def test_explicit_start_allows_generation_with_assumptions(self) -> None:
        text = "我想要一个项目可以通过csgo2的demo分析鼠标键盘动作和视觉信息，用来鉴挂"
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir) / "sessions"
            log_dir = pathlib.Path(temp_dir) / "logs"
            client = FakeTelegramClient()
            original_start = bridge.start_agent_generation
            captured: dict[str, object] = {}

            def fake_start(client_arg, chat_id, session_dir_arg, log_dir_arg, model, timeout, *, announce_start, reason="frontdesk_generation_confirmation"):
                captured["called"] = True
                session = bridge.load_session(session_dir_arg, chat_id)
                captured["snapshot"] = bridge.build_generation_context_snapshot(session, bridge.combined_requirement(session))

            bridge.start_agent_generation = fake_start
            try:
                bridge.handle_text(client, "chat-force", text, session_dir, log_dir, "gpt-test", 30)
                bridge.handle_text(client, "chat-force", "按默认假设开始生成", session_dir, log_dir, "gpt-test", 30)
            finally:
                bridge.start_agent_generation = original_start

        snapshot = captured["snapshot"]
        self.assertTrue(captured["called"])
        self.assertIsInstance(snapshot, dict)

    def test_no_placeholder_screenshot_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (project_dir / "TEST_REPORT.md").write_text("commands_run:\n- python app.py\nresults:\n- ok\n", encoding="utf-8")
            (project_dir / "DELIVERY_NOTES.md").write_text("delivery_status: WARNING\n", encoding="utf-8")
            (project_dir / "placeholder_preview.png").write_bytes(b"\x89PNG\r\n\x1a\nplaceholder")

            manifest = local_packager.package_project(project_dir, visual_required=True)

        self.assertFalse(manifest["quality_evidence"]["preview_evidence_found"])
        self.assertTrue(manifest["quality_evidence"]["preview_placeholder_found"])
        self.assertTrue(any("占位" in item or "不算真实运行证据" in item for item in manifest["known_limits"]))

    def test_test_report_no_test_executed_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (project_dir / "TEST_REPORT.md").write_text("NO TEST EXECUTED\ncommands_run:\n- none\n", encoding="utf-8")
            (project_dir / "DELIVERY_NOTES.md").write_text("delivery_status: WARNING\n", encoding="utf-8")

            manifest = local_packager.package_project(project_dir)

        self.assertEqual("NEEDS_REWORK", manifest["status"])
        self.assertTrue(manifest["quality_evidence"]["test_report_has_no_test_executed"])
        self.assertTrue(any("未执行真实测试" in item for item in manifest["known_limits"]))

    def test_demo_project_without_sample_input_warns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# CS2 Demo Analyzer\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (project_dir / "TEST_REPORT.md").write_text("commands_run:\n- python app.py\nresults:\n- ok\n", encoding="utf-8")
            (project_dir / "DELIVERY_NOTES.md").write_text("delivery_status: WARNING\n", encoding="utf-8")

            manifest = local_packager.package_project(project_dir, known_limits=["demo/data analysis project"])

        self.assertEqual("NEEDS_REWORK", manifest["status"])
        self.assertTrue(any("缺少真实 demo 或样例输入" in item for item in manifest["known_limits"]))


if __name__ == "__main__":
    unittest.main()
