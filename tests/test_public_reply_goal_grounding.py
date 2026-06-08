from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge


class PublicReplyGoalGroundingTests(unittest.TestCase):
    def test_vn_goal_does_not_get_csgo_questions(self) -> None:
        session = bridge.default_session("chat-vn")
        session["whiteboard"] = {
            "project_summary": "CSGO2 demo 鉴挂工具",
            "critical_questions": ["是否可以提供实际 demo 文件？", "鉴挂判别主要看视角异常还是命中事件？"],
        }
        session["active_run"] = {
            "goal": "帮我做一个本地可运行的 VN 项目助手，可以梳理故事逻辑的时间线，可以生成背景，立绘，本地模型，桌面界面，文件导出"
        }

        reply = bridge.grounded_current_goal_reply(session)

        for text in ("VN", "时间线", "背景", "立绘", "本地模型", "导出"):
            self.assertIn(text, reply)
        for text in ("CSGO", "demo 鉴挂", "视角异常", "命中事件", "风险评分"):
            self.assertNotIn(text, reply)

    def test_new_run_resets_project_scoped_context(self) -> None:
        session = bridge.default_session("chat-reset")
        session["pending_soft_questions"] = ["是否可以提供实际 demo 文件？"]
        session["pending_critical_questions"] = ["鉴挂判别主要看视角异常还是命中事件？"]
        session["missing_required_inputs"] = ["实际 demo 文件"]
        session["backend_dialogue_analysis"] = {"project_summary": "CSGO2 鉴挂", "critical_questions": ["demo 文件？"]}
        session["whiteboard"] = {
            "project_summary": "CSGO2 demo 鉴挂工具",
            "known_facts": ["旧项目是 CSGO2"],
            "critical_questions": ["是否可以提供实际 demo 文件？"],
            "open_questions": ["风险评分怎么做？"],
            "user_rules": ["回复要简短"],
        }

        updated = bridge.reset_project_scoped_context_for_new_run(
            session,
            "帮我做一个本地可运行的 VN 项目助手，时间线，背景，立绘，本地模型，文件导出",
            "run-vn",
        )

        self.assertIn("VN", updated["whiteboard"]["project_summary"])
        self.assertEqual([], updated.get("pending_soft_questions", []))
        self.assertNotIn("backend_dialogue_analysis", updated)
        self.assertFalse(updated.get("forced_start_with_missing_inputs"))
        self.assertNotIn("CSGO", str(updated["whiteboard"]))
        self.assertNotIn("demo 文件", str(updated["whiteboard"]))
        self.assertIn("回复要简短", updated["whiteboard"]["user_rules"])

    def test_public_reply_rejects_domain_mismatch(self) -> None:
        current_goal = "本地可运行的 VN 项目助手，故事时间线，背景，立绘，本地模型，桌面界面，文件导出"
        reply = "是否可以提供 CSGO2 demo？鉴挂判别主要看视角异常、命中事件，还是风险评分？"

        self.assertFalse(bridge.reply_matches_current_goal(reply, current_goal))

    def test_failure_reply_no_backend_word(self) -> None:
        reply = bridge.public_delivery_gate_failed_reply()

        for forbidden in ("后台", "internal", "provider", "TLS", "SSLError", "json", "report", "pipeline", "manifest"):
            self.assertNotIn(forbidden, reply)
        for required in ("生成没有通过交付检查", "不会把内部记录当成果", "补齐可运行项目", "真实测试", "截图、图片或视频证据"):
            self.assertIn(required, reply)


if __name__ == "__main__":
    unittest.main()
