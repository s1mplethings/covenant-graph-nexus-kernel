from __future__ import annotations

import pathlib
import tempfile

from scripts import dynamic_pipeline_runner, execution_first_runtime, pipeline_manifest


def test_dynamic_pipeline_writes_execution_first_ledgers_and_canonical_verdict() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        session_path = root / "agent_session.jsonl"
        project_dir = root / "project"
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "execution-first demo"})
        manifest["project_id"] = "execution_first_demo"
        manifest["run_id"] = "run_execution_first_demo"
        manifest["steps"] = [
            {
                "id": "build",
                "type": "agent_turn",
                "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                "role": "foundation",
                "goal": "write runnable minimal project",
                "allowed_actions": ["write_file", "read_file", "list_files"],
            },
            {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
        ]

        def fake_agent(events, model, timeout):
            return {
                "actions": [
                    {"type": "write_file", "path": "README.md", "content": "# Execution-first demo\n"},
                    {"type": "write_file", "path": "app.py", "content": "print('ok')\n"},
                    {"type": "write_file", "path": "requirements.txt", "content": "pytest\n"},
                    {"type": "write_file", "path": "tests/test_app.py", "content": "def test_ok():\n    assert True\n"},
                    {"type": "write_file", "path": "TEST_REPORT.md", "content": "# Tests\n\ncommands_run:\n- python -m pytest\n\nresults:\n- PASS\n"},
                    {"type": "write_file", "path": "DELIVERY_NOTES.md", "content": "# Delivery\n\nready with evidence\n"},
                    {"type": "write_file", "path": "screenshots/ui_screenshot.png", "content": "png"},
                ]
            }

        result = dynamic_pipeline_runner.run_dynamic_pipeline(
            session_path=session_path,
            project_dir=project_dir,
            pipeline_manifest=manifest,
            model="gpt-test",
            timeout=5,
            max_turns=3,
            agent=fake_agent,
            fallback_to_agent_loop=False,
            skip_user_evidence_checkpoint=True,
        )

        execution = result["execution_first"]
        task_ledger = pathlib.Path(execution["task_ledger"])
        evidence_ledger = pathlib.Path(execution["evidence_ledger"])
        canonical_verdict = pathlib.Path(execution["canonical_verdict_path"])

        assert task_ledger.exists()
        assert evidence_ledger.exists()
        assert canonical_verdict.exists()
        assert execution["task_replay"]["completed"] == 2
        assert execution["task_replay"]["illegal_transition_count"] == 0
        assert execution["task_replay"]["completion_without_test_review"] == 0
        assert execution["evidence_refs"]["status"] == "PASS"

        package_events = [
            event
            for event in execution_first_runtime.read_jsonl(evidence_ledger)
            if event.get("event_type") == "package_created"
        ]
        assert package_events
        assert result["execution_first"]["canonical_verdict"]["overall_readiness"] == "NEEDS_REWORK"
        assert result["execution_first"]["canonical_verdict"]["upstream_statuses"]["replan"] == "NOT_EVALUATED"
        assert result["execution_first"]["canonical_verdict"]["upstream_statuses"]["recovery"] == "NOT_EVALUATED"


def test_dynamic_pipeline_can_run_agent_turn_inside_isolated_leaf_workspace() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        session_path = root / "agent_session.jsonl"
        project_dir = root / "project"
        project_dir.mkdir()
        (project_dir / "app.py").write_text("VALUE = 'base'\n", encoding="utf-8")
        manifest = pipeline_manifest.default_minimal_pipeline_manifest({"project_summary": "isolated leaf demo"})
        manifest["project_id"] = "isolated_leaf_demo"
        manifest["run_id"] = "run_isolated_leaf_demo"
        manifest["leaf_isolation"] = True
        manifest["steps"] = [
            {
                "id": "leaf_change",
                "type": "agent_turn",
                "stage": ["product_plan", "technical_plan", "build", "test", "evidence_review", "review"],
                "role": "risk_reviewer",
                "goal": "change app value",
                "allowed_actions": ["write_file", "read_file", "list_files"],
                "allowed_files": ["app.py"],
                "leaf_profile": "micro",
                "nearest_test": "python -c \"from pathlib import Path; assert 'leaf' in Path('app.py').read_text()\"",
            },
            {"id": "package", "type": "package_project", "stage": "package", "goal": "package"},
        ]

        def fake_agent(events, model, timeout):
            assert model == "gpt-test"
            return {"actions": [{"type": "write_file", "path": "app.py", "content": "VALUE = 'leaf'\n"}]}

        result = dynamic_pipeline_runner.run_dynamic_pipeline(
            session_path=session_path,
            project_dir=project_dir,
            pipeline_manifest=manifest,
            model="gpt-test",
            timeout=5,
            max_turns=2,
            agent=fake_agent,
            fallback_to_agent_loop=False,
            skip_user_evidence_checkpoint=True,
        )

        assert result["status"]
        assert (project_dir / "app.py").read_text(encoding="utf-8") == "VALUE = 'leaf'\n"
        leaf_dirs = list((project_dir / ".cgkn_execution" / "leaf_runs").glob("leaf_risk_reviewer_leaf_change"))
        assert leaf_dirs
        manifest_path = leaf_dirs[0] / "result_manifest.json"
        patch_path = leaf_dirs[0] / "patch.diff"
        assert manifest_path.exists()
        assert patch_path.exists()
        assert "VALUE = 'leaf'" in patch_path.read_text(encoding="utf-8")
        assert result["execution_first"]["task_replay"]["completed"] == 2
