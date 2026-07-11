from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import implementation_structure_materializer
import planning_docs_materializer
import requirement_acceptance_check
import requirement_decision_lane


def write_contract_inputs(run_dir: pathlib.Path) -> None:
    requirement_decision_lane.run_requirement_decision("I need a local video material processing workbench", run_dir)
    discovery = run_dir / "discovery"
    discovery.mkdir(parents=True, exist_ok=True)
    (discovery / "complexity_project_contract.json").write_text(
        json.dumps(
            {
                "contract_id": "complexity_project_contract_v1",
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
            }
        ),
        encoding="utf-8",
    )


def test_implementation_structure_materializer_writes_shared_core_and_stage_artifacts(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    write_contract_inputs(run_dir)
    planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)

    result = implementation_structure_materializer.materialize(project_dir=project_dir, run_dir=run_dir)

    assert result["status"] == "PASS"
    assert result["mode"] == "deterministic_degraded_structure"
    for name in ("orchestrator.py", "stages.py", "cli.py", "gui_app.py"):
        assert (project_dir / name).exists()
    for name in result["stage_artifacts"]:
        artifact = json.loads((project_dir / name).read_text(encoding="utf-8"))
        assert {"stage", "status", "count", "input_path", "output_path", "created_at", "upstream_artifacts", "items"}.issubset(artifact)


def test_materialized_implementation_structure_does_not_pass_delivery(tmp_path: pathlib.Path) -> None:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    write_contract_inputs(run_dir)
    planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    implementation_structure_materializer.materialize(project_dir=project_dir, run_dir=run_dir)

    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert layers["requirement_decision_status"] == "PASS"
    assert layers["product_contract_status"] == "PASS"
    assert layers["implementation_status"] == "PASS"
    assert layers["delivery_status"] != "PASS"
    assert "final_project_bundle.zip_missing" in layers["checks"]["delivery_missing"]
    assert not (project_dir / "final_project_bundle.zip").exists()
