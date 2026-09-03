from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.slow


class ProductStudioFinalAcceptanceTests(unittest.TestCase):
    def test_final_acceptance_delivery_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = pathlib.Path(temp_dir) / "final_acceptance_gui_rename"
            run_cmd = [
                sys.executable,
                str(ROOT / "scripts" / "run_product_studio.py"),
                "--goal",
                "做一个本地 GUI 图片批量重命名工具",
                "--input",
                "图片文件夹，prefix + index 规则",
                "--output",
                "重命名图片、操作报告、README、测试数据、测试报告、截图证据、交付包",
                "--constraint",
                "本地运行，不调用 provider，不联网",
                "--out",
                str(run_dir),
            ]
            subprocess.run(run_cmd, cwd=ROOT, check=True, capture_output=True, text=True)

            run_file = run_dir / "product_studio_run.json"
            self.assertTrue(run_file.exists())

            deliver_cmd = [
                sys.executable,
                str(ROOT / "scripts" / "deliver_product_studio.py"),
                "--run-file",
                str(run_file),
                "--out",
                str(run_dir),
            ]
            subprocess.run(deliver_cmd, cwd=ROOT, check=True, capture_output=True, text=True)

            checker_cmd = [
                sys.executable,
                str(ROOT / "scripts" / "check_product_studio_contract.py"),
                "--run-file",
                str(run_file),
                "--json",
            ]
            checker_proc = subprocess.run(checker_cmd, cwd=ROOT, check=True, capture_output=True, text=True)
            checker_result = json.loads(checker_proc.stdout)
            self.assertTrue(checker_result["ok"], checker_result["issues"])
            self.assertTrue(checker_result["delivery_detected"])

            zip_path = run_dir / "delivery_bundle.zip"
            self.assertTrue(zip_path.exists())
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
            self.assertIn("generated_project/index.html", names)
            self.assertIn("generated_project/app.js", names)
            self.assertIn("generated_project/styles.css", names)
            self.assertIn("generated_project/README.md", names)
            self.assertIn("test_report.json", names)
            self.assertIn("runtime_check.json", names)
            self.assertIn("visual_evidence/visual_evidence.json", names)
            self.assertIn("visual_evidence/app_home_screenshot.svg", names)
            self.assertIn("verify_report.json", names)
            self.assertIn("sent_record.json", names)
            self.assertIn("delivery_bundle.json", names)
            self.assertIn("known_limits.md", names)
            self.assertIn("revision_entry.json", names)

            bundle = json.loads((run_dir / "delivery_bundle.json").read_text(encoding="utf-8"))
            self.assertEqual("PASS_WITH_LIMITS", bundle["status"])
            self.assertTrue(bundle["no_network"])
            self.assertFalse(bundle["provider_used"])
            self.assertIn("project_package", bundle)
            self.assertIn("screenshot", bundle)
            self.assertIn("verify_report", bundle)
            self.assertIn("sent_record", bundle)

            visual = json.loads((run_dir / "visual_evidence" / "visual_evidence.json").read_text(encoding="utf-8"))
            self.assertEqual("static_svg_preview", visual["evidence_type"])
            self.assertEqual("PASS_WITH_LIMITS", visual["status"])

            allow_proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "cgnk_boundary_guard.py"),
                    "--intent",
                    str(ROOT / "examples" / "boundary" / "sample_intents.json"),
                    "--case",
                    "allow_product_story",
                    "--json",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            block_proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "cgnk_boundary_guard.py"),
                    "--intent",
                    str(ROOT / "examples" / "boundary" / "sample_intents.json"),
                    "--case",
                    "block_product_agent_generated_path",
                    "--json",
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual("allow", json.loads(allow_proc.stdout)["status"])
            self.assertEqual("block", json.loads(block_proc.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
