from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_intent_router


GENERIC_REQUEST = "做一个本地日志分析工具，上传日志文件后生成统计报告、可视化图表和 PDF 导出。"


class LocalIntentRouterTests(unittest.TestCase):
    def test_memory_title_does_not_override_raw_user_request(self) -> None:
        memory = "# CGNK Requirement Blueprint Generator\n\n## Current Project Summary\n" + GENERIC_REQUEST

        self.assertTrue(local_intent_router.should_ignore_memory_title(memory, GENERIC_REQUEST))
        result = local_intent_router.classify_project_type(memory, {"raw_user_message": GENERIC_REQUEST})

        self.assertNotEqual("requirement_blueprint_generator", result["project_type"])
        self.assertEqual("raw_user_message", result["intent_source"])
        self.assertEqual(GENERIC_REQUEST, result["raw_user_message"])

    def test_explicit_blueprint_generator_request_is_allowed(self) -> None:
        result = local_intent_router.classify_project_type("请做一个 Requirement Blueprint Generator，用来生成项目需求蓝图。")

        self.assertEqual("requirement_blueprint_generator", result["project_type"])
        self.assertEqual("product_planning", result["domain"])

    def test_generic_required_features_are_extracted(self) -> None:
        result = local_intent_router.classify_project_type(GENERIC_REQUEST)
        features = result["required_features"]

        self.assertIn("file_import", features)
        self.assertIn("statistics_report", features)
        self.assertIn("visualization", features)
        self.assertIn("pdf_export", features)

    def test_domain_specific_request_uses_generic_non_blueprint_route(self) -> None:
        request = "做一个工具，通过 CSGO2 demo 文件分析鼠标键盘动作、视角和玩家操作，用于鉴别外挂行为。"

        result = local_intent_router.classify_project_type(request)

        self.assertEqual("data_analysis_tool", result["project_type"])
        self.assertEqual("data_analysis", result["domain"])
        self.assertIn("file_import", result["required_features"])
        self.assertIn("data_analysis", result["required_features"])

    def test_visible_user_goal_has_priority_over_wrapper_title(self) -> None:
        wrapped = "\n".join(
            [
                "# CGNK Requirement Blueprint Generator",
                "",
                "## Visible User Message Log",
                f"1. {GENERIC_REQUEST}",
                "",
                "## System Context",
                "Existing memory title should be treated as background.",
            ]
        )

        goal = local_intent_router.extract_explicit_user_goal(wrapped)

        self.assertEqual(GENERIC_REQUEST, goal["raw_user_message"])
        self.assertEqual("visible_user_message_log", goal["source"])

    def test_detects_requirement_blueprint_readme_conflict_for_non_blueprint_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# CGNK Requirement Blueprint Generator\n", encoding="utf-8")
            conflict = local_intent_router.detect_project_type_conflict(
                {"project_type": "reporting_application"},
                project_dir,
            )

            self.assertTrue(conflict["conflict"])
            self.assertIn("readme_title_is_requirement_blueprint_generator", conflict["reasons"])


if __name__ == "__main__":
    unittest.main()
