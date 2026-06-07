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
import scripts.pipeline_planner_agent as pipeline_planner_agent


def stages(manifest: dict) -> set[str]:
    covered: set[str] = set()
    for step in manifest.get("steps", []):
        raw = step.get("stage", [])
        for item in raw if isinstance(raw, list) else [raw]:
            if item:
                covered.add(str(item))
    return covered


class ProductStudioDisciplineTests(unittest.TestCase):
    def test_default_manifest_has_required_stages(self) -> None:
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({})

        self.assertTrue(set(pipeline_manifest.REQUIRED_STAGES).issubset(stages(manifest)))

    def test_validate_required_stages_rejects_missing_test_or_review(self) -> None:
        manifest = {
            "steps": [
                {"id": "build", "type": "agent_turn", "stage": "build"},
                {"id": "package", "type": "package_project", "stage": "package"},
            ]
        }

        ok, missing = pipeline_manifest.validate_required_stages(manifest)

        self.assertFalse(ok)
        self.assertTrue("test" in missing or "review" in missing)

    def test_planner_fallback_when_required_stages_missing(self) -> None:
        original_provider = pipeline_planner_agent._call_provider
        original_local = pipeline_planner_agent.local_model_router.call_json_task
        pipeline_planner_agent.local_model_router.call_json_task = lambda *args, **kwargs: {"ok": False, "error": "skip"}
        pipeline_planner_agent._call_provider = lambda *args, **kwargs: json.dumps(
            {
                "kind": "AgentGeneratedPipelineManifest",
                "version": 1,
                "project_goal": "demo",
                "roles": [{"id": "builder", "name": "Builder", "purpose": "build"}],
                "steps": [
                    {"id": "build", "type": "agent_turn", "stage": "build", "role": "builder", "goal": "build", "allowed_actions": ["write_file"]},
                    {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
                ],
            }
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                manifest = pipeline_planner_agent.plan_pipeline(
                    pathlib.Path(temp_dir) / "agent_session.jsonl",
                    {"project_summary": "demo"},
                    "gpt-real",
                    5,
                )
        finally:
            pipeline_planner_agent._call_provider = original_provider
            pipeline_planner_agent.local_model_router.call_json_task = original_local

        self.assertTrue(set(pipeline_manifest.REQUIRED_STAGES).issubset(stages(manifest)))
        self.assertTrue(manifest.get("planner_fallback_reason") or manifest.get("missing_required_stages") or manifest.get("normalization_fallback_reason"))

    def test_packager_warns_without_test_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")

            manifest = local_packager.package_project(project_dir)

        self.assertEqual("ready_with_warnings", manifest["status"])
        self.assertFalse(manifest["quality_evidence"]["test_report_found"])
        self.assertTrue(any("TEST_REPORT" in item for item in manifest["known_limits"]))

    def test_packager_records_test_report_and_delivery_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = pathlib.Path(temp_dir)
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")
            (project_dir / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (project_dir / "TEST_REPORT.md").write_text("# Tests\n", encoding="utf-8")
            (project_dir / "DELIVERY_NOTES.md").write_text("# Notes\n", encoding="utf-8")

            manifest = local_packager.package_project(project_dir)

        self.assertTrue(manifest["quality_evidence"]["test_report_found"])
        self.assertTrue(manifest["quality_evidence"]["delivery_notes_found"])

    def test_backend_dialogue_short_request_needs_direction_confirmation(self) -> None:
        result = backend_dialogue_loop.summarize_locally({"whiteboard": {}}, "做个系统")

        self.assertTrue(result["needs_direction_confirmation"])
        self.assertTrue(result["soft_questions"])
        self.assertTrue("默认假设" in result["user_visible_reply"] or "开始生成" in result["user_visible_reply"])

    def test_pre_package_audit_records_missing_test_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = pathlib.Path(temp_dir)
            session_file = root / "agent_session.jsonl"
            project_dir = root / "project"
            project_dir.mkdir()
            (project_dir / "README.md").write_text("# Demo\n", encoding="utf-8")

            audit = dynamic_pipeline_runner.pre_package_audit(session_file, project_dir, {})

            events = [json.loads(line) for line in session_file.read_text(encoding="utf-8").splitlines()]

        self.assertIn("test_report", audit["missing"])
        self.assertTrue(any(event.get("kind") == "pre_package_audit" for event in events))


if __name__ == "__main__":
    unittest.main()
