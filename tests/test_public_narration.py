from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as dialogue
import scripts.public_narration as public_narration
import scripts.telegram_live_bridge as bridge


INTERNAL_TERMS = [
    "pipeline_manifest",
    "dynamic_pipeline_runner",
    "delivery_manifest",
    "backend_dialogue_loop",
    "agent_session",
    "user_evidence_checkpoint",
    "waiting_user_review",
    "quality_evidence",
    "local_packager",
    "pipeline",
    "manifest",
    "runner",
]

PERSONA_NAMES = ["林然", "周衡", "许楠", "沈镜", "陈序", "乔安"]


class PublicNarrationTests(unittest.TestCase):
    def assert_no_internal_terms(self, text: str) -> None:
        lowered = text.lower()
        for term in INTERNAL_TERMS:
            self.assertNotIn(term.lower(), lowered)

    def assert_no_persona_names(self, text: str) -> None:
        for name in PERSONA_NAMES:
            self.assertNotIn(name, text)

    def test_redact_internal_terms(self) -> None:
        text = public_narration.redact_internal_terms(
            "pipeline_manifest 已生成，dynamic_pipeline_runner waiting_user_review，delivery_manifest ready"
        )

        self.assert_no_internal_terms(text)
        self.assertIn("项目执行计划", text)
        self.assertIn("后台执行流程", text)
        self.assertIn("交付清单", text)

    def test_no_persona_names_in_public_reply(self) -> None:
        events = [
            "intake_waiting",
            "generation_started",
            "evidence_checkpoint",
            "delivery_ready",
            "generation_warning",
            "review_continue",
            "review_revision",
        ]

        for event in events:
            with self.subTest(event=event):
                text = public_narration.public_event_text(event, {"questions": ["输入格式是什么？"]})
                self.assert_no_persona_names(text)
                self.assert_no_internal_terms(text)

    def test_intake_reply_describes_actions_not_people(self) -> None:
        session = bridge.default_session("public-intake")
        session["messages"].append(
            {
                "role": "user",
                "text": "我想通过 csgo2 demo 分析鼠标键盘动作和视觉信息，用来鉴挂",
                "created_at": bridge.now(),
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = dialogue.run_backend_dialogue_tick(
                pathlib.Path(temp_dir),
                "public-intake",
                session=session,
                model="gpt-test",
                timeout=30,
                reason="new_project_request",
                api_budget="off",
            )

        reply = result["user_visible_reply"]
        for phrase in ("第一版", "测试代码", "测试命令", "预览证据", "判断", "按默认假设开始"):
            self.assertIn(phrase, reply)
        self.assert_no_internal_terms(reply)
        self.assert_no_persona_names(reply)

    def test_evidence_checkpoint_reply_action_based(self) -> None:
        reply = bridge.evidence_checkpoint_summary(
            {
                "test_report_path": "TEST_REPORT.md",
                "test_code_files": ["tests/test_demo.py"],
                "test_commands": ["pytest"],
                "screenshots": ["preview.png"],
                "preview_files": ["data.json"],
                "videos": [],
                "sample_inputs": ["sample.dem"],
                "missing": ["videos"],
            }
        )

        for phrase in ("测试报告", "测试代码", "测试命令", "样例输入", "截图", "视频", "继续/打包", "改哪里"):
            self.assertIn(phrase, reply)
        self.assert_no_internal_terms(reply)
        self.assert_no_persona_names(reply)

    def test_delivery_reply_action_based(self) -> None:
        reply = bridge.build_delivery_summary_text(
            {
                "status": "ready_with_warnings",
                "quality_evidence": {
                    "test_report_found": True,
                    "delivery_notes_found": True,
                    "preview_evidence_found": False,
                    "test_report_has_commands": True,
                    "test_report_has_no_test_executed": False,
                    "sample_input_found": False,
                    "preview_placeholder_found": False,
                },
                "known_limits": ["quality_evidence preview missing from delivery_manifest"],
            }
        )

        for phrase in ("最终交付", "项目包", "测试报告", "测试执行", "预览证据", "真实输入验证", "已知限制"):
            self.assertIn(phrase, reply)
        self.assert_no_internal_terms(reply)
        self.assert_no_persona_names(reply)


if __name__ == "__main__":
    unittest.main()
