from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.run_local_pipeline as run_local_pipeline


class RunLocalPipelineUsageTests(unittest.TestCase):
    def test_blocked_result_reloads_repair_context_for_same_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = pathlib.Path(temp_dir) / "result.json"
            run_local_pipeline.write_json(
                result_path,
                {
                    "status": "BLOCKED",
                    "reason": "provider_generation_failed",
                    "goal": "build app",
                    "repair_errors": ["provider semantic review failed: missing entrypoint"],
                },
            )

            errors = run_local_pipeline.load_recoverable_repair_errors(result_path, "build app")
            other_goal_errors = run_local_pipeline.load_recoverable_repair_errors(result_path, "other app")

        self.assertEqual(["provider semantic review failed: missing entrypoint"], errors)
        self.assertEqual([], other_goal_errors)

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

    def test_progress_deadline_extends_after_meaningful_work(self) -> None:
        deadline = run_local_pipeline.ProgressDeadline(time.time() - 1, extension_seconds=60)

        deadline.mark_progress("project_generation", "component returned files", ["app.py"])
        value = run_local_pipeline.remaining_timeout(deadline, 120, floor=5, cap=90)

        self.assertGreaterEqual(value, 5)
        self.assertEqual("project_generation", deadline.progress_events[-1]["phase"])

    def test_provider_component_progress_refreshes_deadline_between_components(self) -> None:
        original = run_local_pipeline.provider_generate_project_component
        calls: list[str] = []

        def fake_provider_component(**kwargs):
            component_id = kwargs["component"]["id"]
            calls.append(component_id)
            time.sleep(1.2)
            return {
                "component_id": component_id,
                "summary": f"{component_id} done",
                "files": [{"path": f"{component_id}.py", "content": "print('ok')\n"}],
            }

        run_local_pipeline.provider_generate_project_component = fake_provider_component
        try:
            deadline = run_local_pipeline.ProgressDeadline(time.time() + 6, extension_seconds=60)
            result = run_local_pipeline.provider_generate_project_by_components(
                "build a project",
                {
                    "components": [{"id": "app"}, {"id": "tests"}],
                    "merge_policy": {"required_final_files": ["app.py", "tests.py"]},
                },
                {},
                {},
                {},
                {},
                [],
                "unused",
                30,
                deadline=deadline,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original

        self.assertEqual(["app", "tests"], calls)
        self.assertEqual(2, len(result["files"]))
        self.assertTrue(deadline.progress_events)

    def test_provider_component_checkpoint_resumes_completed_components(self) -> None:
        original = run_local_pipeline.provider_generate_project_component
        original_fast = os.environ.get("CGKN_PROVIDER_RETRY_FAST")
        os.environ["CGKN_PROVIDER_RETRY_FAST"] = "1"
        calls: list[str] = []

        def first_run_component(**kwargs):
            component_id = kwargs["component"]["id"]
            calls.append(component_id)
            if component_id == "backend":
                raise RuntimeError("provider_api_request_failed: HTTP 520: upstream failed [retryable=true]")
            return {
                "component_id": component_id,
                "summary": "foundation done",
                "files": [{"path": "app.py", "content": "print('ok')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass", "checks": ["validated"]},
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_dir = pathlib.Path(temp_dir) / "artifacts" / "provider_components"
            pipeline = {
                "components": [{"id": "foundation"}, {"id": "backend"}],
                "merge_policy": {"required_final_files": ["app.py", "src/backend.py"]},
            }
            run_local_pipeline.provider_generate_project_component = first_run_component
            try:
                with self.assertRaises(RuntimeError):
                    run_local_pipeline.provider_generate_project_by_components(
                        "build a project",
                        pipeline,
                        {},
                        {},
                        {},
                        {},
                        [],
                        "unused",
                        30,
                        checkpoint_dir=checkpoint_dir,
                    )
                self.assertEqual(["foundation", "backend", "backend", "backend"], calls)
                self.assertTrue((checkpoint_dir / "foundation.json").exists())
                calls.clear()

                def second_run_component(**kwargs):
                    component_id = kwargs["component"]["id"]
                    calls.append(component_id)
                    if component_id == "foundation":
                        raise AssertionError("foundation should have been loaded from checkpoint")
                    return {
                        "component_id": component_id,
                        "summary": "backend done",
                        "files": [{"path": "src/backend.py", "content": "def ok():\n    return True\n"}],
                        "quality_gate": {"status": "pass"},
                        "self_test": {"status": "pass", "checks": ["validated"]},
                    }

                run_local_pipeline.provider_generate_project_component = second_run_component
                result = run_local_pipeline.provider_generate_project_by_components(
                    "build a project",
                    pipeline,
                    {},
                    {},
                    {},
                    {},
                    [],
                    "unused",
                    30,
                    checkpoint_dir=checkpoint_dir,
                )
                self.assertTrue((checkpoint_dir / "component_checkpoint_summary.json").exists())
            finally:
                run_local_pipeline.provider_generate_project_component = original
                if original_fast is None:
                    os.environ.pop("CGKN_PROVIDER_RETRY_FAST", None)
                else:
                    os.environ["CGKN_PROVIDER_RETRY_FAST"] = original_fast

        self.assertEqual(["backend"], calls)
        self.assertEqual(["foundation"], result["component_checkpoint_summary"]["skipped_from_checkpoint"])
        self.assertIn("foundation", result["component_checkpoint_summary"]["completed_components"])
        self.assertIn("backend", result["component_checkpoint_summary"]["completed_components"])

    def test_semantic_repair_regenerates_checkpointed_components(self) -> None:
        original = run_local_pipeline.provider_generate_project_component
        calls: list[str] = []

        def fake_provider_component(**kwargs):
            component_id = kwargs["component"]["id"]
            calls.append(component_id)
            return {
                "component_id": component_id,
                "summary": "repaired",
                "files": [{"path": "app.py", "content": "print('repaired')\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass", "checks": ["validated"]},
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_dir = pathlib.Path(temp_dir) / "artifacts" / "provider_components"
            pipeline = {
                "components": [{"id": "foundation"}],
                "merge_policy": {"required_final_files": ["app.py"]},
            }
            spec_hash = run_local_pipeline.provider_component_spec_hash("build a project", pipeline, pipeline["components"][0])
            run_local_pipeline.write_provider_component_checkpoint(
                checkpoint_dir,
                component_id="foundation",
                spec_hash=spec_hash,
                status="pass",
                raw_output="",
                parsed_result={"component_id": "foundation"},
                files=[{"path": "app.py", "content": "print('stale')\n"}],
                semantic_review={"status": "pass"},
            )
            run_local_pipeline.provider_generate_project_component = fake_provider_component
            try:
                result = run_local_pipeline.provider_generate_project_by_components(
                    "build a project",
                    pipeline,
                    {},
                    {},
                    {},
                    {},
                    ["attempt 1: provider semantic review failed: missing runnable behavior"],
                    "unused",
                    30,
                    checkpoint_dir=checkpoint_dir,
                )
            finally:
                run_local_pipeline.provider_generate_project_component = original

        self.assertEqual(["foundation"], calls)
        self.assertEqual([], result["component_checkpoint_summary"]["skipped_from_checkpoint"])
        self.assertEqual("print('repaired')\n", result["files"][0]["content"])

    def test_failed_checkpoint_does_not_overwrite_last_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_dir = pathlib.Path(temp_dir)
            run_local_pipeline.write_provider_component_checkpoint(
                checkpoint_dir,
                component_id="frontend",
                spec_hash="same",
                status="pass",
                raw_output="",
                parsed_result={"component_id": "frontend"},
                files=[{"path": "index.html", "content": "<h1>working</h1>\n"}],
                semantic_review={"status": "pass"},
            )
            run_local_pipeline.write_provider_component_checkpoint(
                checkpoint_dir,
                component_id="frontend",
                spec_hash="same",
                status="failed",
                raw_output="",
                parsed_result={"component_id": "frontend"},
                files=[],
                semantic_review={"status": "fail"},
                error="temporary TLS failure",
                provider_error_type="PROVIDER_TRANSPORT_UNSTABLE",
            )

            cached = run_local_pipeline.load_provider_component_checkpoint(
                checkpoint_dir,
                component_id="frontend",
                spec_hash="same",
            )

        self.assertIsNotNone(cached)
        self.assertEqual("<h1>working</h1>\n", cached[1][0]["content"])

    def test_component_merge_generates_test_plan_from_real_tests(self) -> None:
        original = run_local_pipeline.provider_generate_project_component

        def fake_provider_component(**kwargs):
            component_id = kwargs["component"]["id"]
            if component_id == "docs":
                return {
                    "component_id": component_id,
                    "summary": "docs",
                    "files": [{"path": "README.md", "content": "# App\n"}],
                    "quality_gate": {"status": "pass"},
                    "self_test": {"status": "pass", "checks": ["validated"]},
                }
            return {
                "component_id": component_id,
                "summary": "tests",
                "files": [{"path": "tests/test_app.py", "content": "def test_ok():\n    assert True\n"}],
                "quality_gate": {"status": "pass"},
                "self_test": {"status": "pass", "checks": ["validated"]},
            }

        run_local_pipeline.provider_generate_project_component = fake_provider_component
        try:
            result = run_local_pipeline.provider_generate_project_by_components(
                "build a project",
                {
                    "components": [{"id": "docs"}, {"id": "tests"}],
                    "merge_policy": {"required_final_files": ["README.md", "TEST_PLAN.md"]},
                },
                {},
                {},
                {},
                {},
                [],
                "unused",
                30,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original

        files = {item["path"]: item["content"] for item in result["files"]}
        self.assertIn("TEST_PLAN.md", files)
        self.assertIn("tests/test_app.py", files["TEST_PLAN.md"])

    def test_component_merge_combines_document_conflicts_only(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "foundation", "files": [{"path": "README.md", "content": "# App\n"}]},
                {"component_id": "docs", "files": [{"path": "README.md", "content": "# Usage\n"}]},
            ]
        )
        readme = {item["path"]: item["content"] for item in files}["README.md"]
        self.assertIn("# App", readme)
        self.assertIn("# Usage", readme)

        with self.assertRaises(RuntimeError):
            run_local_pipeline.merge_component_files(
                [
                    {"component_id": "one", "files": [{"path": "src/app.py", "content": "print(1)\n"}]},
                    {"component_id": "two", "files": [{"path": "src/app.py", "content": "print(2)\n"}]},
                ]
            )

    def test_component_merge_allows_frontend_asset_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "foundation", "files": [{"path": "app/index.html", "content": "<h1>base</h1>\n"}]},
                {"component_id": "frontend", "files": [{"path": "app/index.html", "content": "<h1>frontend</h1>\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("<h1>frontend</h1>\n", merged["app/index.html"])

    def test_component_merge_allows_nested_template_asset_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {
                    "component_id": "foundation",
                    "files": [{"path": "src/task_board/templates/index.html", "content": "<h1>base</h1>\n"}],
                },
                {
                    "component_id": "frontend",
                    "files": [{"path": "src/task_board/templates/index.html", "content": "<h1>frontend</h1>\n"}],
                },
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("<h1>frontend</h1>\n", merged["src/task_board/templates/index.html"])

    def test_component_merge_allows_template_asset_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "foundation", "files": [{"path": "templates/index.html", "content": "<h1>base</h1>\n"}]},
                {"component_id": "execution", "files": [{"path": "templates/index.html", "content": "<h1>execution</h1>\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("<h1>execution</h1>\n", merged["templates/index.html"])

    def test_component_merge_allows_top_level_entrypoint_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "generation", "files": [{"path": "app.py", "content": "print('base')\n"}]},
                {"component_id": "execution", "files": [{"path": "app.py", "content": "print('runnable')\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("print('runnable')\n", merged["app.py"])

    def test_component_merge_allows_src_file_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "init", "files": [{"path": "src/task_store.py", "content": "TASKS = []\n"}]},
                {"component_id": "generate_project", "files": [{"path": "src/task_store.py", "content": "TASKS = ['ready']\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("TASKS = ['ready']\n", merged["src/task_store.py"])

    def test_component_merge_allows_test_file_conflicts(self) -> None:
        files = run_local_pipeline.merge_component_files(
            [
                {"component_id": "init", "files": [{"path": "tests/test_app.py", "content": "def test_placeholder(): pass\n"}]},
                {"component_id": "generate_project", "files": [{"path": "tests/test_app.py", "content": "def test_home(): pass\n"}]},
            ]
        )

        merged = {item["path"]: item["content"] for item in files}
        self.assertEqual("def test_home(): pass\n", merged["tests/test_app.py"])

    def test_component_merge_accepts_test_report_as_qa_evidence(self) -> None:
        original = run_local_pipeline.provider_generate_project_component

        def fake_component(**kwargs):
            component_id = kwargs["component"]["id"]
            if component_id == "docs":
                return {"component_id": "docs", "files": [{"path": "README.md", "content": "# Demo\n"}]}
            return {
                "component_id": "execution",
                "files": [
                    {"path": "app.py", "content": "print('ok')\n"},
                    {"path": "TEST_REPORT.md", "content": "commands_run: pytest\nexit_code: 0\n"},
                ],
            }

        run_local_pipeline.provider_generate_project_component = fake_component
        try:
            result = run_local_pipeline.provider_generate_project_by_components(
                goal="做一个小工具",
                component_pipeline={
                    "components": [
                        {"id": "docs", "goal": "Write docs", "acceptance": []},
                        {"id": "execution", "goal": "Write runnable app and test report", "acceptance": []},
                    ],
                    "merge_policy": {"required_final_files": ["README.md", "TEST_PLAN.md"]},
                },
                plan_doc={},
                blueprint={},
                online_inputs={},
                market_research={},
                repair_errors=[],
                model="gpt-test",
                timeout=5,
            )
        finally:
            run_local_pipeline.provider_generate_project_component = original

        files = {item["path"]: item["content"] for item in result["files"]}
        assert "README.md" in files
        assert "TEST_REPORT.md" in files


if __name__ == "__main__":
    unittest.main()
