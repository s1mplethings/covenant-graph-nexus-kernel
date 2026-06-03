from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_intent_router


CSGO2_REQUEST = "我想要一个项目可以通过csgo2的demo基本分析出用户的鼠标键盘动作，还有点击、视角变化、准星移动，生成热力图、操作频率曲线、图片和PDF报告，用来鉴挂"


class LocalIntentRouterTests(unittest.TestCase):
    def test_csgo2_demo_request_routes_to_game_demo_telemetry_analyzer(self) -> None:
        result = local_intent_router.classify_project_type(CSGO2_REQUEST)
        self.assertEqual("game_demo_telemetry_analyzer", result["project_type"])
        self.assertEqual("esports_demo_analysis", result["domain"])

    def test_csgo2_required_features_are_preserved(self) -> None:
        result = local_intent_router.classify_project_type(CSGO2_REQUEST)
        features = result["required_features"]
        self.assertIn("mouse_movement_analysis", features)
        self.assertIn("keyboard_input_analysis", features)
        self.assertIn("heatmap_visualization", features)
        self.assertIn("pdf_report_export", features)

    def test_csgo2_non_goals_include_deep_ml(self) -> None:
        result = local_intent_router.classify_project_type(CSGO2_REQUEST)
        self.assertIn("deep_ml_cheat_detection", result["non_goals"])

    def test_memory_title_does_not_override_raw_csgo2_request(self) -> None:
        memory = "# CGNK Requirement Blueprint Generator\n\n" + CSGO2_REQUEST
        self.assertTrue(local_intent_router.should_ignore_memory_title(memory, CSGO2_REQUEST))
        result = local_intent_router.classify_project_type(memory, {"raw_user_message": CSGO2_REQUEST})
        self.assertEqual("game_demo_telemetry_analyzer", result["project_type"])

    def test_detects_requirement_blueprint_readme_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# CGNK Requirement Blueprint Generator\n", encoding="utf-8")
            conflict = local_intent_router.detect_project_type_conflict(
                {"project_type": "game_demo_telemetry_analyzer"},
                project_dir,
            )
            self.assertTrue(conflict["conflict"])


if __name__ == "__main__":
    unittest.main()
