from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import planning_docs_materializer
import requirement_acceptance_check
import requirement_decision_lane


PLANNING_DOCS = ("product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md")


def write_contract_inputs(run_dir: pathlib.Path) -> None:
    requirement_decision_lane.run_requirement_decision("I need a local video material processing workbench", run_dir)
    discovery = run_dir / "discovery"
    discovery.mkdir(parents=True, exist_ok=True)
    (discovery / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "contract_id": "complexity_project_contract_v1",
                "selected_project_id": "local_video_workbench",
                "required_planning_docs": list(PLANNING_DOCS),
                "required_pipeline_stages": [
                    "ingest_video",
                    "extract_audio",
                    "chunk_audio",
                    "transcribe_audio",
                    "analyze_segments",
                    "select_segments",
                    "render_clips",
                    "export_results",
                ],
                "required_stage_artifacts": [
                    "stage_plan.json",
                    "media_manifest.json",
                    "audio_chunk_manifest.json",
                    "transcript_merged.json",
                    "segment_analysis.json",
                    "selected_segments.json",
                    "clip_manifest.json",
                    "export_results.json",
                ],
                "required_entrypoints": ["cli", "gui"],
                "required_delivery_evidence": ["README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "final_project_bundle.zip"],
            }
        ),
        encoding="utf-8",
    )


def test_materializer_writes_contract_driven_planning_docs(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    write_contract_inputs(run_dir)

    result = planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)

    assert result["status"] == "PASS"
    assert result["mode"] == "deterministic_contract_planning"
    for name in PLANNING_DOCS:
        path = project_dir / name
        text = path.read_text(encoding="utf-8")
        assert path.exists()
        assert len(text) > 500
        assert "TODO" not in text
        assert "not implementation evidence" in text

    assert "selected_requirement.json" in (project_dir / "product_brief.md").read_text(encoding="utf-8")
    assert "acceptance_contract.json" in (project_dir / "technical_plan.md").read_text(encoding="utf-8")
    assert "complexity_project_contract.json" in (project_dir / "technical_plan.md").read_text(encoding="utf-8")
    assert "mvp_scope.md" in (project_dir / "interaction_design.md").read_text(encoding="utf-8")
    assert "fake PASS" in (project_dir / "acceptance_matrix.md").read_text(encoding="utf-8")


def test_materialized_planning_docs_pass_product_contract_only(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    write_contract_inputs(run_dir)

    planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert layers["requirement_decision_status"] == "PASS"
    assert layers["product_contract_status"] == "PASS"
    assert layers["implementation_status"] != "PASS"
    assert layers["delivery_status"] != "PASS"
    assert "orchestrator.py_missing" in layers["checks"]["implementation_missing"]
    assert "final_project_bundle.zip_missing" in layers["checks"]["delivery_missing"]


def test_planning_gate_rejects_heading_only_docs(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    write_contract_inputs(run_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    for name in PLANNING_DOCS:
        (project_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert layers["product_contract_status"] != "PASS"
    assert "product_brief.md_quality_failed" in layers["checks"]["planning_contract_gate"]["missing"]
