from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as dialogue
import scripts.team_narration as team_narration
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


class TeamNarrationPublicReplyTests(unittest.TestCase):
    def assert_no_internal_terms(self, text: str) -> None:
        lowered = text.lower()
        for term in INTERNAL_TERMS:
            self.assertNotIn(term.lower(), lowered)

    def test_redact_internal_terms(self) -> None:
        text = team_narration.redact_internal_terms(
            "pipeline_manifest 已生成，dynamic_pipeline_runner waiting_user_review，delivery_manifest ready"
        )

        self.assertNotIn("pipeline_manifest", text)
        self.assertNotIn("dynamic_pipeline_runner", text)
        self.assertNotIn("delivery_manifest", text)
        self.assertNotIn("runner", text)
        self.assertNotIn("manifest", text)
        self.assertIn("项目执行计划", text)
        self.assertIn("后台执行流程", text)
        self.assertIn("交付清单", text)

    def test_intake_reply_uses_team_names(self) -> None:
        session = bridge.default_session("team-intake")
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
                "team-intake",
                session=session,
                model="gpt-test",
                timeout=30,
                reason="new_project_request",
                api_budget="off",
            )

        reply = result["user_visible_reply"]
        self.assertTrue("林然" in reply or "周衡" in reply)
        self.assertTrue("陈序" in reply or "沈镜" in reply)
        self.assert_no_internal_terms(reply)

    def test_evidence_checkpoint_reply_uses_team_names(self) -> None:
        reply = bridge.evidence_checkpoint_summary(
            {
                "test_report_path": "TEST_REPORT.md",
                "test_code_files": ["tests/test_demo.py"],
                "test_commands": ["pytest"],
                "screenshots": ["preview.png"],
                "preview_files": [],
                "videos": [],
                "sample_inputs": [],
                "missing": ["preview_files"],
            }
        )

        self.assertIn("陈序", reply)
        self.assertIn("沈镜", reply)
        self.assertIn("乔安", reply)
        self.assert_no_internal_terms(reply)

    def test_delivery_reply_uses_team_names(self) -> None:
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

        self.assertIn("乔安", reply)
        self.assertIn("陈序", reply)
        self.assertIn("沈镜", reply)
        self.assert_no_internal_terms(reply)


if __name__ == "__main__":
    unittest.main()
