from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.backend_dialogue_loop as backend_dialogue_loop
import scripts.dynamic_pipeline_runner as dynamic_pipeline_runner
import scripts.local_packager as local_packager
import scripts.pipeline_manifest as pipeline_manifest


def resume_test_manifest() -> dict:
    return {
        "kind": "AgentGeneratedPipelineManifest",
        "version": 1,
        "project_goal": "plain cli",
        "roles": [
            {"id": "cfo", "name": "CFO", "purpose": "plan and review"},
            {"id": "builder", "name": "Builder", "purpose": "build"},
            {"id": "qa", "name": "QA", "purpose": "test"},
        ],
        "steps": [
            {"id": "product_plan", "type": "agent_turn", "stage": "product_plan", "role": "cfo", "goal": "run product_plan", "allowed_actions": ["write_file"]},
            {"id": "technical_plan", "type": "agent_turn", "stage": "technical_plan", "role": "cfo", "goal": "run technical_plan", "allowed_actions": ["write_file"]},
            {"id": "build", "type": "agent_turn", "stage": "build", "role": "builder", "goal": "run build", "allowed_actions": ["write_file"]},
            {"id": "test", "type": "agent_turn", "stage": "test", "role": "qa", "goal": "run test", "allowed_actions": ["write_file"]},
            {"id": "evidence_review", "type": "agent_turn", "stage": "evidence_review", "role": "qa", "goal": "run evidence_review", "allowed_actions": ["write_file"]},
            {"id": "review", "type": "agent_turn", "stage": "review", "role": "cfo", "goal": "run review", "allowed_actions": ["write_file"]},
            {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
        ],
        "limits": {"max_agent_turns_per_step": 1, "max_total_steps": 7},
    }


def current_goal(events: list[dict]) -> str:
    prompt = str(events[0].get("content", ""))
    return prompt.split("Current step goal:", 1)[-1].split("\n", 1)[0].strip().rstrip(".")


def stage_index(manifest: dict, stage: str) -> int:
    for index, step in enumerate(manifest.get("steps", [])):
        raw = step.get("stage", [])
        values = raw if isinstance(raw, list) else [raw]
        if stage in [str(item) for item in values]:
            return index
    return -1


class EvidenceReviewCheckpointTests(unittest.TestCase):
    def test_default_manifest_has_evidence_review_between_test_and_review(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})

        self.assertIn("evidence_review", pipeline_manifest.REQUIRED_STAGES)
        self.assertGreater(stage_index(manifest, "evidence_review"), stage_index(manifest, "test"))
        self.assertGreater(stage_index(manifest, "review"), stage_index(manifest, "evidence_review"))
        self.assertGreater(stage_index(manifest, "package"), stage_index(manifest, "review"))

    def test_validate_required_stages_rejects_package_before_evidence_review(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "demo"})
        package_step = next(step for step in manifest["steps"] if step["id"] == "package")
        evidence_step = next(step for step in manifest["steps"] if step["id"] == "evidence_review")
        manifest["steps"].remove(package_step)
        evidence_index = manifest["steps"].index(evidence_step)
        manifest["steps"].insert(evidence_index, package_step)

        ok, errors = pipeline_manifest.validate_required_stages(manifest)

        self.assertFalse(ok)
        self.assertIn("package_before_evidence_review", errors)

    def test_collect_user_review_evidence_finds_tests_inputs_and_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            (project / "tests").mkdir()
            (project / "samples").mkdir()
            (project / "screenshots").mkdir()
            (project / "demo").mkdir()
            (project / "preview").mkdir()
            (project / "TEST_REPORT.md").write_text("# Tests\n\ncommands_run:\n- python -m pytest\n", encoding="utf-8")
            (project / "EVIDENCE_REVIEW.md").write_text("# Evidence\n", encoding="utf-8")
            (project / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
            (project / "samples" / "input.json").write_text('{"demo": true}\n', encoding="utf-8")
            (project / "screenshots" / "result.png").write_bytes(b"png")
            (project / "demo" / "clip.mp4").write_bytes(b"mp4")
            (project / "preview" / "index.html").write_text("<h1>ok</h1>\n", encoding="utf-8")

            evidence = dynamic_pipeline_runner.collect_user_review_evidence(project)

        self.assertEqual("TEST_REPORT.md", evidence["test_report_path"])
        self.assertEqual("EVIDENCE_REVIEW.md", evidence["evidence_review_path"])
        self.assertIn("tests/test_app.py", evidence["test_code_files"])
        self.assertIn("python -m pytest", evidence["test_commands"])
        self.assertIn("samples/input.json", evidence["sample_inputs"])
        self.assertIn("screenshots/result.png", evidence["screenshots"])
        self.assertIn("demo/clip.mp4", evidence["videos"])
        self.assertIn("preview/index.html", evidence["preview_files"])

    def test_visual_demo_requires_user_evidence_judgement(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "csgo2 鉴挂 demo，需要截图和视频"})

        self.assertTrue(dynamic_pipeline_runner.requires_user_evidence_judgement(manifest, {}))
        self.assertTrue(dynamic_pipeline_runner.requires_user_evidence_judgement({"steps": []}, {"requires_user_evidence_review": True}))

    def test_backend_dialogue_marks_csgo_visual_request_for_review(self) -> None:
        result = backend_dialogue_loop.summarize_locally({"whiteboard": {}}, "做一个 csgo2 鉴挂 demo，要截图和视频预览")

        self.assertTrue(result["requires_user_evidence_review"])
        self.assertIn("测试代码", result["user_visible_reply"])
        self.assertIn("判断", result["user_visible_reply"])

    def test_packager_records_user_review_evidence_and_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = pathlib.Path(temp_dir)
            (project / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project / "TEST_REPORT.md").write_text("# Tests\ncommands_run:\n- python app.py\n", encoding="utf-8")
            (project / "EVIDENCE_REVIEW.md").write_text("# Evidence\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
            (project / "screenshots").mkdir()
            (project / "screenshots" / "result.png").write_bytes(b"png")

            manifest = local_packager.package_project(project, user_review_required=True, user_review_completed=False)

        evidence = manifest["user_review_evidence"]
        self.assertTrue(evidence["user_review_required"])
        self.assertFalse(evidence["user_review_completed"])
        self.assertTrue(evidence["evidence_review_found"])
        self.assertIn("tests/test_app.py", evidence["test_code_files"])
        self.assertIn("screenshots/result.png", evidence["screenshots"])
        self.assertTrue(any("用户尚未确认" in item for item in manifest["known_limits"]))

    def test_dynamic_runner_waits_after_evidence_review_before_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "视觉 demo，需要用户看证据"})

            def fake_agent(events, model, timeout):
                prompt = str(events[0].get("content", ""))
                current_goal = prompt.split("Current step goal:", 1)[-1].split("\n", 1)[0]
                if "EVIDENCE_REVIEW.md" in current_goal:
                    return {"actions": [{"type": "write_file", "path": "EVIDENCE_REVIEW.md", "content": "# Evidence\n"}]}
                if "TEST_REPORT.md" in current_goal or "test" in current_goal.lower():
                    return {"actions": [{"type": "write_file", "path": "TEST_REPORT.md", "content": "# Tests\ncommands_run:\n- python app.py\n"}]}
                if "DELIVERY_NOTES.md" in current_goal:
                    return {"actions": [{"type": "write_file", "path": "DELIVERY_NOTES.md", "content": "# Notes\n"}]}
                return {"actions": [{"type": "write_file", "path": "DELIVERY_NOTES.md", "content": "# Notes\n"}]}

            result = dynamic_pipeline_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=manifest,
                model="gpt-test",
                timeout=5,
                max_turns=20,
                agent=fake_agent,
                fallback_to_agent_loop=False,
                whiteboard={"requires_user_evidence_review": True},
            )
            events = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertEqual("waiting_user_review", result["status"])
        self.assertEqual("TEST_REPORT.md", result["evidence"]["test_report_path"])
        self.assertTrue(any(event.get("kind") == "user_evidence_checkpoint" for event in events))
        self.assertFalse((project_dir / "final_project_bundle.zip").exists())

    def test_resume_after_evidence_review_starts_at_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Built\n", encoding="utf-8")
            (project_dir / "TEST_REPORT.md").write_text("# Tests\ncommands_run:\n- python app.py\n", encoding="utf-8")
            (project_dir / "EVIDENCE_REVIEW.md").write_text("# Evidence\n", encoding="utf-8")
            executed: list[str] = []

            def fake_agent(events, model, timeout):
                goal = current_goal(events)
                executed.append(goal.removeprefix("run "))
                return {"actions": [{"type": "write_file", "path": "DELIVERY_NOTES.md", "content": "# Notes\n"}]}

            result = dynamic_pipeline_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=resume_test_manifest(),
                model="gpt-test",
                timeout=5,
                max_turns=7,
                agent=fake_agent,
                fallback_to_agent_loop=False,
                skip_user_evidence_checkpoint=True,
                start_stage="review",
            )
            events = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            package_exists = pathlib.Path(result["package_path"]).exists()

        self.assertEqual(["review"], executed)
        self.assertTrue(package_exists)
        skipped = [event for event in events if event.get("kind") == "pipeline_step_skipped"]
        self.assertEqual(["product_plan", "technical_plan", "build", "test", "evidence_review"], [event.get("step_id") for event in skipped])
        self.assertTrue(all(event.get("reason") == "resume_start_stage" for event in skipped))
        self.assertTrue(all(event.get("start_stage") == "review" for event in skipped))
        self.assertTrue(any(event.get("kind") == "pipeline_step_result" and event.get("step_id") == "review" for event in events))
        self.assertTrue(any(event.get("kind") == "pipeline_step_result" and event.get("step_id") == "package" for event in events))

    def test_normal_pipeline_still_starts_from_product_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_path = root / "agent_session.jsonl"
            project_dir = root / "project"
            executed: list[str] = []

            def fake_agent(events, model, timeout):
                step = current_goal(events).removeprefix("run ")
                executed.append(step)
                actions = {
                    "product_plan": [{"type": "write_file", "path": "PRODUCT_PLAN.md", "content": "# Product\n"}],
                    "technical_plan": [{"type": "write_file", "path": "TECHNICAL_PLAN.md", "content": "# Tech\n"}],
                    "build": [{"type": "write_file", "path": "README.md", "content": "# Built\n"}],
                    "test": [{"type": "write_file", "path": "TEST_REPORT.md", "content": "# Tests\ncommands_run:\n- python app.py\n"}],
                    "evidence_review": [{"type": "write_file", "path": "EVIDENCE_REVIEW.md", "content": "# Evidence\n"}],
                    "review": [{"type": "write_file", "path": "DELIVERY_NOTES.md", "content": "# Notes\n"}],
                }
                return {"actions": actions[step]}

            result = dynamic_pipeline_runner.run_dynamic_pipeline(
                session_path=session_path,
                project_dir=project_dir,
                pipeline_manifest=resume_test_manifest(),
                model="gpt-test",
                timeout=5,
                max_turns=7,
                agent=fake_agent,
                fallback_to_agent_loop=False,
                start_stage="",
            )
            events = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            package_exists = pathlib.Path(result["package_path"]).exists()

        self.assertEqual(["product_plan", "technical_plan", "build", "test", "evidence_review", "review"], executed)
        self.assertTrue(package_exists)
        self.assertFalse(any(event.get("kind") == "pipeline_step_skipped" for event in events))


if __name__ == "__main__":
    unittest.main()
