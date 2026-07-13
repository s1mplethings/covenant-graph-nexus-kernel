from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RunProductStudioTests(unittest.TestCase):
    def run_creator(self, out_dir: pathlib.Path) -> pathlib.Path:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_product_studio.py"),
                "--goal",
                "做一个本地 GUI 图片批量重命名工具",
                "--input",
                "图片文件夹，prefix + index 规则",
                "--output",
                "重命名图片、操作报告、README、测试数据、测试报告、截图证据、交付包",
                "--constraint",
                "本地运行",
                "--out",
                str(out_dir),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return out_dir / "product_studio_run.json"

    def test_cli_generates_product_studio_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = self.run_creator(pathlib.Path(temp_dir))
            self.assertTrue(run_path.exists())

    def test_generated_json_contains_nine_top_level_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = self.run_creator(pathlib.Path(temp_dir))
            data = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(
                {
                    "customer_intent",
                    "output_contract",
                    "virtual_team_roster",
                    "product_story",
                    "mvp_scope",
                    "technical_plan",
                    "build_plan",
                    "test_evidence",
                    "delivery_bundle",
                },
                set(data),
            )

    def test_gui_image_need_creates_ux_and_media_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = self.run_creator(pathlib.Path(temp_dir))
            data = json.loads(run_path.read_text(encoding="utf-8"))
            roles = data["virtual_team_roster"]["specialist_agents"]
            self.assertIn("UX Designer", roles)
            self.assertIn("Media Pipeline Engineer", roles)

    def test_generated_run_passes_checker_run_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = self.run_creator(pathlib.Path(temp_dir))
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_product_studio_contract.py"),
                    "--run-file",
                    str(run_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

    def test_run_summary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = pathlib.Path(temp_dir)
            self.run_creator(out_dir)
            summary_path = out_dir / "run_summary.md"
            self.assertTrue(summary_path.exists())
            text = summary_path.read_text(encoding="utf-8")
            self.assertIn("当前状态: PASS_WITH_LIMITS", text)
            self.assertIn("Agent Build / Runner / QA Evidence", text)

    def test_creator_has_no_provider_or_network_arguments(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_product_studio.py"), "--help"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        help_text = proc.stdout.lower()
        self.assertNotIn("provider", help_text)
        self.assertNotIn("api-key", help_text)
        self.assertNotIn("network", help_text)


if __name__ == "__main__":
    unittest.main()
