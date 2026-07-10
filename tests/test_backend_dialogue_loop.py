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
        original_discovery = dialogue.local_image_model_discovery.critical_questions_for_text
        dialogue.local_image_model_discovery.critical_questions_for_text = lambda text, root=None: (
            ["本地图片生成准备用哪个后端：ComfyUI、AUTOMATIC1111，还是直接给 SD_MODEL_DIR/模型目录？"],
            {"available": False, "checked": [{"kind": "ComfyUI", "status": "missing"}], "backends": []},
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                result = dialogue.run_backend_dialogue_tick(
                    pathlib.Path(temp_dir),
                    "chat-vn",
                    session,
                    model="gpt-test",
                    timeout=30,
                    reason="new_project_request",
                )
        finally:
            dialogue.local_image_model_discovery.critical_questions_for_text = original_discovery

        self.assertIn(result["status"], {"ok", "degraded"})
        self.assertIn("VN", result["project_summary"])
        self.assertIn("时间线", "；".join(result["frontend_plan"]))
        self.assertIn("图片生成", "；".join(result["backend_plan"]))
        self.assertIn("本地图片模型能力探测", "；".join(result["backend_plan"]))
        self.assertIn("核心能力识别", "；".join(result["backend_plan"]))
        self.assertTrue(result["ready_to_generate"])
        self.assertLessEqual(len(result["soft_questions"]), 3)
        self.assertGreaterEqual(len(result["critical_questions"]), 1)
        self.assertIn("本地图片", "；".join(session["whiteboard"]["critical_questions"]))
        self.assertEqual([], session["whiteboard"]["blocking_questions"])
        self.assertTrue(session["whiteboard"]["ready_to_generate"])
        self.assertIn("第一版", result["user_visible_reply"])
        self.assertIn("会影响第一版质量的选择", result["user_visible_reply"])
        self.assertNotIn("我已记下", result["user_visible_reply"])
        strategy = session["whiteboard"]["capability_strategy"]
        labels = "；".join(item["label"] for item in strategy["capabilities"])
        self.assertIn("内容生成能力", labels)
        self.assertIn("结构化流程/关系建模", labels)
        self.assertTrue(strategy["research_targets"])
        self.assertTrue(result["question_decisions"])
        self.assertEqual(result["question_decisions"], session["whiteboard"]["question_decisions"])

    def test_local_image_backend_found_does_not_ask_missing_backend_question(self) -> None:
        session = {
            "messages": [{"role": "user", "text": "本地 VN 工具，背景和立绘都要用本地图片模型直接生成"}],
            "whiteboard": {},
        }
        original_discovery = dialogue.local_image_model_discovery.critical_questions_for_text
        dialogue.local_image_model_discovery.critical_questions_for_text = lambda text, root=None: (
            [],
            {"available": True, "checked": [{"kind": "ComfyUI", "status": "available"}], "backends": [{"kind": "ComfyUI", "target": "local"}]},
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                result = dialogue.run_backend_dialogue_tick(
                    pathlib.Path(temp_dir),
                    "chat-vn-local",
                    session,
                    model="gpt-test",
                    timeout=30,
                    reason="new_project_request",
                )
        finally:
            dialogue.local_image_model_discovery.critical_questions_for_text = original_discovery

        self.assertEqual([], result["critical_questions"])
        self.assertEqual([], session["whiteboard"]["critical_questions"])
        self.assertTrue(session["whiteboard"]["local_image_model_discovery"]["available"])

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

        self.assertLessEqual(len(result["soft_questions"]), 3)
        self.assertGreaterEqual(len(result["soft_questions"]), 1)
        self.assertTrue(result["ready_to_generate"])
        self.assertEqual([], session["whiteboard"]["blocking_questions"])
        self.assertIn("现在缺少几个会影响质量的点", result["user_visible_reply"])
        self.assertIn("按默认假设开始", result["user_visible_reply"])
        self.assertTrue(result["needs_direction_confirmation"])
        self.assertIn("开始生成", result["user_visible_reply"])

    def test_capability_questions_include_reason_and_default(self) -> None:
        result = dialogue.summarize_locally(
            {"whiteboard": {}},
            "做一个本地任务自动化系统，要流程状态、自动生成报告、保存历史，最好有可运行界面",
        )

        self.assertTrue(result["critical_questions"])
        self.assertTrue(result["question_decisions"])
        first = result["question_decisions"][0]
        self.assertIn("question", first)
        self.assertIn("reason", first)
        self.assertIn("default_assumption", first)
        card_questions = {item["question"] for item in result["question_decisions"]}
        self.assertTrue(set(result["critical_questions"]).issubset(card_questions))
        self.assertIn("会影响第一版质量的选择", result["user_visible_reply"])
        self.assertIn("如果你暂时不选", result["user_visible_reply"])
        self.assertNotIn("生成能力优先走本地模型、外部高级 API", "\n".join(result["critical_questions"]))

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

    def test_local_model_can_supply_backend_dialogue_before_api(self) -> None:
        original_task_enabled = dialogue.local_model_router.task_enabled
        original_local_call = dialogue.local_model_router.call_json_task
        original_creds = dialogue.check_connectivity._resolve_api_credentials
        try:
            dialogue.local_model_router.task_enabled = lambda task: task == "backend_dialogue"
            dialogue.local_model_router.call_json_task = lambda *args, **kwargs: {
                "ok": True,
                "provider": "test-local",
                "model": "local-small",
                "json": {
                    "project_summary": "本地模型拆解 demo",
                    "frontend_plan": ["ui"],
                    "backend_plan": ["api"],
                    "data_model": ["item"],
                    "first_version_scope": ["v1"],
                    "assumptions": [],
                    "soft_questions": [],
                    "user_visible_reply": "第一版先做 demo。",
                },
            }
            dialogue.check_connectivity._resolve_api_credentials = lambda: (_ for _ in ()).throw(AssertionError("api should not be needed"))

            result, error = dialogue.call_provider(
                {"messages": []},
                "请分析 demo",
                {"project_summary": "demo"},
                model="gpt-real",
                timeout=30,
            )
        finally:
            dialogue.local_model_router.task_enabled = original_task_enabled
            dialogue.local_model_router.call_json_task = original_local_call
            dialogue.check_connectivity._resolve_api_credentials = original_creds

        self.assertEqual("", error)
        self.assertIsNotNone(result)
        self.assertEqual("local_model", result["_provider_source"])
        self.assertEqual("本地模型拆解 demo", result["project_summary"])

    def test_provider_endpoint_does_not_duplicate_v1(self) -> None:
        captured: dict[str, object] = {}
        original_creds = dialogue.check_connectivity._resolve_api_credentials
        original_post = dialogue.check_connectivity._post_json
        original_extract = dialogue.check_connectivity._extract_text

        def fake_post(endpoint, payload, token, timeout):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"project_summary":"demo","frontend_plan":["ui"],'
                                '"backend_plan":["api"],"data_model":["item"],'
                                '"first_version_scope":["v1"],"assumptions":[],"soft_questions":[],'
                                '"user_visible_reply":"第一版会先做 demo。"}'
                            )
                        }
                    }
                ]
            }, ""

        dialogue.check_connectivity._resolve_api_credentials = lambda: {"api_key": "test-key", "base_url": "https://gptsapi.net/v1"}
        dialogue.check_connectivity._post_json = fake_post
        dialogue.check_connectivity._extract_text = lambda doc: doc["choices"][0]["message"]["content"]
        try:
            result, error = dialogue.call_provider(
                {"messages": []},
                "请分析一个 demo",
                {"project_summary": "demo"},
                model="gpt-test",
                timeout=30,
            )
        finally:
            dialogue.check_connectivity._resolve_api_credentials = original_creds
            dialogue.check_connectivity._post_json = original_post
            dialogue.check_connectivity._extract_text = original_extract

        self.assertEqual("", error)
        self.assertIsNotNone(result)
        self.assertEqual("https://gptsapi.net/v1/chat/completions", captured["endpoint"])
        self.assertNotIn("/v1/v1/", str(captured["endpoint"]))


if __name__ == "__main__":
    unittest.main()
