from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.telegram_live_bridge as bridge


class ProviderPostBuildFinalizeTests(unittest.TestCase):
    def test_post_build_finalize_runs_tests_images_package_and_gate(self) -> None:
        try:
            import PIL  # noqa: F401
        except Exception:
            self.skipTest("Pillow is required for image evidence fixture")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# VN Assistant\n\nRun `python app.py`.\n", encoding="utf-8")
            (project / "app.py").write_text("print('vn assistant')\n", encoding="utf-8")
            (project / "requirements.txt").write_text("pytest\nPillow\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (project / "models").mkdir()
            (project / "models" / "__init__.py").write_text("", encoding="utf-8")
            (project / "models" / "image_generator.py").write_text(
                "\n".join(
                    [
                        "import pathlib",
                        "from PIL import Image, ImageDraw",
                        "",
                        "class LocalImageGenerator:",
                        "    def __init__(self, assets_dir='assets/generated'):",
                        "        self.assets_dir = pathlib.Path(assets_dir)",
                        "        self.assets_dir.mkdir(parents=True, exist_ok=True)",
                        "    def generate_background(self, scene_name):",
                        "        path = self.assets_dir / f'background_{scene_name}.png'",
                        "        img = Image.new('RGB', (640, 360), (20, 30, 80))",
                        "        draw = ImageDraw.Draw(img)",
                        "        for x in range(0, 640, 20):",
                        "            draw.line((x, 0, 640-x, 360), fill=(40 + x % 180, 120, 200))",
                        "        draw.text((40, 150), 'generated background', fill=(255, 255, 255))",
                        "        img.save(path)",
                        "        return str(path)",
                        "    def generate_character_sprite(self, character_name):",
                        "        path = self.assets_dir / f'sprite_{character_name}.png'",
                        "        img = Image.new('RGBA', (320, 480), (0, 0, 0, 0))",
                        "        draw = ImageDraw.Draw(img)",
                        "        draw.ellipse((90, 30, 230, 170), fill=(250, 220, 180, 255))",
                        "        draw.rectangle((120, 170, 200, 420), fill=(120, 70, 180, 255))",
                        "        draw.text((50, 430), 'generated sprite', fill=(255, 255, 255, 255))",
                        "        img.save(path)",
                        "        return str(path)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            session_dir = root / "sessions"
            session = bridge.default_session("chat-vn-post")
            session["messages"].append(
                {
                    "role": "user",
                    "text": "帮我做一个本地可运行的 VN 项目助手，可以生成背景，立绘，本地模型，桌面界面，文件导出",
                    "created_at": bridge.now(),
                }
            )

            result = bridge.post_build_finalize_provider_project(
                project,
                {"status": "PASS", "example_outputs": {}, "agent_usage": {"events": []}},
                {"copied": {}},
                session,
                session_dir=session_dir,
                chat_id="chat-vn-post",
            )

            self.assertTrue(result["test_result"]["ok"])
            self.assertTrue(result["image_result"]["ok"])
            self.assertTrue(result["gate"]["delivery_allowed"], result["gate"])
            self.assertTrue((project / "TEST_REPORT.md").exists())
            self.assertIn("exit_code: 0", (project / "TEST_REPORT.md").read_text(encoding="utf-8"))
            self.assertTrue((project / "screenshots" / "app_home.png").exists())
            self.assertTrue(list((project / "assets" / "generated").glob("background_*.png")))
            self.assertTrue(list((project / "assets" / "generated").glob("sprite_*.png")))
            self.assertTrue((project / "generated_image_manifest.json").exists())
            self.assertTrue((project / "final_project_bundle.zip").exists())


if __name__ == "__main__":
    unittest.main()
