from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import requirement_acceptance_check
import planning_docs_materializer
import requirement_decision_lane


PLANNING_DOCS = ("product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md")


def write_requirement_and_contract(run_dir: pathlib.Path, required_stage_artifacts: list[str] | None = None) -> None:
    requirement_decision_lane.run_requirement_decision("I need a local video workbench", run_dir)
    discovery = run_dir / "discovery"
    discovery.mkdir(parents=True, exist_ok=True)
    (discovery / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "contract_id": "complexity_project_contract_v1",
                "required_stage_artifacts": required_stage_artifacts or [],
            }
        ),
        encoding="utf-8",
    )


def write_core_and_delivery(project: pathlib.Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    (project / "orchestrator.py").write_text("import stages\n\ndef run():\n    return stages.ingest_video()\n", encoding="utf-8")
    (project / "stages.py").write_text("def ingest_video():\n    return {'status': 'degraded'}\n", encoding="utf-8")
    (project / "cli.py").write_text("import argparse\nimport orchestrator\n\nif __name__ == '__main__': orchestrator.run()\n", encoding="utf-8")
    (project / "gui_app.py").write_text("import tkinter\nimport orchestrator\norchestrator.run()\n", encoding="utf-8")
    (project / "README.md").write_text("# Project\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- python -m pytest\nexit_code: 0\n", encoding="utf-8")
    (project / "DELIVERY_NOTES.md").write_text("# Delivery\n", encoding="utf-8")
    (project / "screenshots").mkdir(exist_ok=True)
    (project / "screenshots" / "app_screenshot.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    )
    (project / "final_project_bundle.zip").write_bytes(b"zip")


def test_missing_requirement_artifacts_block_requirement_layer(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=tmp_path / "run")
    assert result["requirement_decision_status"] == "FAIL"
    assert result["implementation_status"] != "PASS"


def test_missing_planning_docs_do_not_pass_product_contract(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    write_requirement_and_contract(run_dir)
    project = tmp_path / "project"
    project.mkdir()
    result = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=run_dir)
    assert result["requirement_decision_status"] == "PASS"
    assert result["product_contract_status"] != "PASS"
    assert result["implementation_status"] != "PASS"
    assert result["delivery_status"] == "NEEDS_REWORK"
    assert result["checks"]["planning_contract_gate"]["missing"]


def test_each_missing_planning_doc_blocks_product_contract(tmp_path: pathlib.Path) -> None:
    for missing_doc in PLANNING_DOCS:
        case_dir = tmp_path / missing_doc.replace(".", "_")
        run_dir = case_dir / "run"
        project = case_dir / "project"
        write_requirement_and_contract(run_dir)
        write_core_and_delivery(project)
        for name in PLANNING_DOCS:
            if name != missing_doc:
                (project / name).write_text(f"# {name}\n", encoding="utf-8")

        result = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=run_dir)

        assert result["requirement_decision_status"] == "PASS"
        assert result["product_contract_status"] != "PASS"
        assert result["implementation_status"] != "PASS"
        assert result["delivery_status"] != "PASS"
        assert result["overall_status"] != "PASS"
        assert f"{missing_doc}_missing" in result["checks"]["planning_contract_gate"]["missing"]
        assert "planning_contract_incomplete" in result["checks"]["implementation_missing"]
        assert "planning_contract_incomplete" in result["checks"]["delivery_missing"]


def test_complete_planning_docs_are_required_before_implementation_can_pass(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project = tmp_path / "project"
    write_requirement_and_contract(run_dir)
    write_core_and_delivery(project)
    planning_docs_materializer.materialize(project_dir=project, run_dir=run_dir)

    result = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=run_dir)

    assert result["product_contract_status"] == "PASS"
    assert "planning_contract_incomplete" not in result["checks"]["implementation_missing"]


def test_stage_artifact_schema_failure_keeps_implementation_from_pass(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    write_requirement_and_contract(run_dir, ["media_manifest.json"])
    project = tmp_path / "project"
    project.mkdir()
    planning_docs_materializer.materialize(project_dir=project, run_dir=run_dir)
    (project / "orchestrator.py").write_text("import stages\n", encoding="utf-8")
    (project / "stages.py").write_text("def ingest_video(): pass\n", encoding="utf-8")
    (project / "cli.py").write_text("import argparse\nimport orchestrator\n", encoding="utf-8")
    (project / "gui_app.py").write_text("import tkinter\nimport orchestrator\n", encoding="utf-8")
    (project / "media_manifest.json").write_text(json.dumps({"stage": "ingest_video"}), encoding="utf-8")
    result = requirement_acceptance_check.evaluate_layers(project_dir=project, run_dir=run_dir)
    assert result["implementation_status"] != "PASS"
    assert "stage_artifact_schema_invalid:media_manifest.json" in result["checks"]["implementation_missing"]
