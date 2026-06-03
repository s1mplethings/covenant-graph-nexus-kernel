from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_local_pipeline as run_local_pipeline


class RunLocalPipelineUsageTests(unittest.TestCase):
    def test_usage_plan_placeholders_expand_project_file_url(self) -> None:
        project_dir = ROOT / "generated" / "demo_project"
        run_dir = ROOT / "examples" / "runtime_runs" / "demo_project"
        plan = {
            "wait_url": "file://{project_dir}/index.html",
            "browser_steps": [
                {"action": "goto", "url": "file://{project_dir}/index.html"},
                {"action": "fill", "selector": "textarea", "text": "{project_dir}"},
            ],
            "pre_commands": [["python", "{project_dir}\\scripts\\demo.py"]],
        }
        normalized = run_local_pipeline.normalize_usage_plan_placeholders(plan, project_dir, run_dir)
        self.assertEqual(project_dir.resolve().as_uri() + "/index.html", normalized["wait_url"])
        self.assertEqual(project_dir.resolve().as_uri() + "/index.html", normalized["browser_steps"][0]["url"])
        self.assertIn(str(project_dir.resolve()), normalized["browser_steps"][1]["text"])
        self.assertIn(str(project_dir.resolve()), normalized["pre_commands"][0][1])

    def test_pip_install_pre_command_is_skipped_without_failure(self) -> None:
        result = run_local_pipeline.run_allowed_command(["python", "-m", "pip", "install", "-r", "requirements.txt"], ROOT)
        self.assertEqual("pass", result["status"])
        self.assertTrue(result["skipped"])
        self.assertIn("shared runtime", result["reason"])


if __name__ == "__main__":
    unittest.main()
