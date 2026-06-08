from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge


class ProjectContextIsolationTests(unittest.TestCase):
    def test_reset_project_scoped_context_for_new_run_clears_project_state(self) -> None:
        session = bridge.default_session("chat-isolation")
        session["pending_start_assumptions"] = ["旧项目按 demo 输入"]
        session["pending_soft_questions"] = ["旧项目是否提供 demo？"]
        session["pending_critical_questions"] = ["旧项目鉴挂依据？"]
        session["pending_required_inputs"] = ["旧项目 demo 文件"]
        session["pending_evidence_checkpoint"] = {"status": "waiting_user_review"}
        session["pending_decision"] = {"status": "pending", "question": "旧问题"}
        session["forced_start_with_missing_inputs"] = True
        session["missing_required_inputs"] = ["旧输入"]
        session["backend_dialogue_analysis"] = {"project_summary": "旧项目"}
        session["delivery_gate"] = {"status": "READY"}
        session["public_delivery_gate"] = {"status": "READY"}
        session["whiteboard"] = {
            "project_summary": "CSGO2 demo 鉴挂工具",
            "known_facts": ["旧项目事实"],
            "first_version_plan": ["旧计划"],
            "critical_questions": ["是否提供实际 demo 文件？"],
            "open_questions": ["风险评分如何做？"],
            "acceptance_criteria": ["旧验收"],
            "delivery_requirements": ["旧交付"],
            "decision_log": ["旧决策"],
            "delivery_gate": {"status": "READY"},
            "user_rules": ["回复要简短"],
            "global_user_preferences": {"language": "zh-CN"},
            "preferred_language": "zh-CN",
            "local_first_preference": True,
            "testing_evidence_preference": "real",
            "no_fake_delivery_preference": True,
            "no_internal_details_preference": True,
        }

        updated = bridge.reset_project_scoped_context_for_new_run(
            session,
            "帮我做一个本地可运行的 VN 项目助手，时间线，背景，立绘，本地模型，文件导出",
            "run-new",
        )

        for key in (
            "pending_start_assumptions",
            "pending_soft_questions",
            "pending_critical_questions",
            "pending_required_inputs",
            "pending_evidence_checkpoint",
            "pending_decision",
            "missing_required_inputs",
            "backend_dialogue_analysis",
            "delivery_gate",
            "public_delivery_gate",
        ):
            self.assertNotIn(key, updated)

        self.assertFalse(updated["forced_start_with_missing_inputs"])
        self.assertFalse(updated["generation_start_waiting"])
        self.assertEqual("run-new", updated["project_scoped_context_run_id"])
        self.assertIn("VN", updated["whiteboard"]["project_summary"])
        self.assertNotIn("CSGO2", str(updated["whiteboard"]))
        self.assertNotIn("demo 文件", str(updated["whiteboard"]))
        self.assertEqual(["回复要简短"], updated["whiteboard"]["user_rules"])
        self.assertEqual({"language": "zh-CN"}, updated["whiteboard"]["global_user_preferences"])
        self.assertTrue(updated["whiteboard"]["local_first_preference"])
        self.assertTrue(updated["whiteboard"]["no_fake_delivery_preference"])
        self.assertTrue(updated["whiteboard"]["no_internal_details_preference"])

    def test_create_intake_ticket_binds_reset_to_ticket_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = pathlib.Path(temp_dir)
            session = bridge.default_session("chat-ticket")
            session["pending_soft_questions"] = ["旧问题"]
            ticket = bridge.create_intake_ticket(session_dir, session, "做一个本地工具")

        self.assertEqual(ticket["id"], session["project_scoped_context_run_id"])
        self.assertNotIn("pending_soft_questions", session)
        self.assertEqual("做一个本地工具", session["whiteboard"]["project_summary"])


if __name__ == "__main__":
    unittest.main()
