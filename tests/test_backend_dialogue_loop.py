from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as dialogue


class BackendDialogueLoopTests(unittest.TestCase):
    def test_local_tick_updates_whiteboard_without_hard_gate(self) -> None:
        session = {
            "messages": [
                {
                    "role": "user",
                    "text": "你帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景和立绘，是真正直接生成图片的",
                }
            ],
            "whiteboard": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result = dialogue.run_backend_dialogue_tick(
                pathlib.Path(temp_dir),
                "chat-vn",
                session,
                model="gpt-test",
                timeout=30,
                reason="new_project_request",
            )

        self.assertIn(result["status"], {"ok", "degraded"})
        self.assertIn("VN", result["project_summary"])
        self.assertIn("时间线", "；".join(result["frontend_plan"]))
        self.assertIn("图片生成", "；".join(result["backend_plan"]))
        self.assertTrue(result["ready_to_generate"])
        self.assertLessEqual(len(result["soft_questions"]), 2)
        self.assertEqual([], session["whiteboard"]["blocking_questions"])
        self.assertTrue(session["whiteboard"]["ready_to_generate"])
        self.assertIn("第一版", result["user_visible_reply"])
        self.assertNotIn("我已记下", result["user_visible_reply"])

    def test_short_request_asks_soft_questions_only(self) -> None:
        session = {"messages": [{"role": "user", "text": "做个系统"}], "whiteboard": {}}
        with tempfile.TemporaryDirectory() as temp_dir:
            result = dialogue.run_backend_dialogue_tick(
                pathlib.Path(temp_dir),
                "chat-short",
                session,
                model="gpt-test",
                timeout=30,
                reason="new_project_request",
            )

        self.assertLessEqual(len(result["soft_questions"]), 2)
        self.assertGreaterEqual(len(result["soft_questions"]), 1)
        self.assertTrue(result["ready_to_generate"])
        self.assertEqual([], session["whiteboard"]["blocking_questions"])
        self.assertIn("不会卡住生成", result["user_visible_reply"])

    def test_provider_failure_degrades_to_local_result(self) -> None:
        session = {
            "messages": [{"role": "user", "text": "请分析一个复杂架构方案，要前端、后端、数据模型都清楚"}],
            "whiteboard": {},
            "backend_dialogue_budget": {},
        }
        original_should = dialogue.should_call_provider
        original_call = dialogue.call_provider
        dialogue.should_call_provider = lambda *args, **kwargs: True
        dialogue.call_provider = lambda *args, **kwargs: (None, "network unavailable")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                result = dialogue.run_backend_dialogue_tick(
                    pathlib.Path(temp_dir),
                    "chat-provider",
                    session,
                    model="gpt-real",
                    timeout=30,
                    reason="project_update",
                )
        finally:
            dialogue.should_call_provider = original_should
            dialogue.call_provider = original_call

        self.assertEqual("degraded", result["status"])
        self.assertIn("network unavailable", result["provider_error"])
        self.assertTrue(result["frontend_plan"])
        self.assertTrue(result["backend_plan"])
        self.assertEqual(1, session["backend_dialogue_budget"]["api_calls"])


if __name__ == "__main__":
    unittest.main()
