from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge
import scripts.project_memory_md as project_memory_md


class TelegramCustomerBridgeTests(unittest.TestCase):
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
