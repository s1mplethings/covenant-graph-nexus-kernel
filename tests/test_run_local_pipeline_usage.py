from __future__ import annotations

import pathlib
import sys
import tempfile
import time
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

    def test_frozen_user_intent_prefers_original_requirement_over_compressed_goal(self) -> None:
        original = "做一个工具，通过 CSGO2 demo 文件分析鼠标键盘动作和视角，用于鉴别外挂行为。"
        compressed = "# CGNK Requirement Blueprint Generator\n\n## Current Project Summary\n" + original

        intent = run_local_pipeline.frozen_user_intent(
            {
                "original_requirement": original,
                "pipeline_plan": {"payload": {"requirement": compressed}},
            },
            compressed,
        )

        self.assertEqual("data_analysis_tool", intent["project_type"])
        self.assertEqual(original, intent["raw_user_message"])

    def test_usage_planning_writes_diagnostics_and_phase_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = pathlib.Path(temp_dir)
            project_dir = base / "project"
            run_dir = base / "run"
            project_dir.mkdir()
            (project_dir / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
            phase_log = run_dir / "artifacts" / "generation_phase_log.jsonl"

            result = run_local_pipeline.run_project_usage_agent(
                "本地静态页面",
                project_dir,
                run_dir,
                ["index.html"],
                {"project_type": "local_application"},
                {},
                "unused",
                30,
                phase_log_path=phase_log,
            )

            self.assertIn(result["status"], {"partial", "pass", "failed"})
            diagnostics = run_dir / "agent_usage" / "usage_planning_diagnostics.json"
            self.assertTrue(diagnostics.exists())
            log_text = phase_log.read_text(encoding="utf-8")
            self.assertIn("usage_planning_local", log_text)
            self.assertIn("usage_plan.json written", log_text)

    def test_provider_plan_doc_strips_internal_context_prompt(self) -> None:
        plan = {
            "goal": "做一个真实项目",
            "internal_context_prompt": "CGNK_CONTEXT_PROMPT requirement_blueprint",
            "pipeline_plan": {"payload": {"requirement": "做一个真实项目"}},
        }

        sanitized = run_local_pipeline.provider_plan_doc(plan)

        self.assertNotIn("internal_context_prompt", sanitized)
        self.assertEqual("做一个真实项目", sanitized["goal"])

    def test_provider_blueprint_context_is_marked_as_supporting_only(self) -> None:
        context = run_local_pipeline.provider_blueprint_context({"raw_requirement": "做一个真实项目"})

        self.assertEqual("supporting_requirement_analysis_only", context["role"])
        self.assertIn("not a blueprint generator", context["warning"])
        self.assertEqual("做一个真实项目", context["doc"]["raw_requirement"])

    def test_remaining_timeout_is_capped_by_deadline(self) -> None:
        deadline = time.time() + 6

        value = run_local_pipeline.remaining_timeout(deadline, 120, floor=1, cap=90)

        self.assertLessEqual(value, 6)
        self.assertGreaterEqual(value, 1)


if __name__ == "__main__":
    unittest.main()
