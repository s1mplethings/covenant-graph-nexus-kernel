from __future__ import annotations

import json
import pathlib
import sys
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import delivery_evidence_builder
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


def materialized_project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    write_contract_inputs(run_dir)
    planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    implementation_structure_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    return project_dir, run_dir


def test_builder_generates_real_delivery_docs_manifest_zip_and_screenshot(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialized_project(tmp_path)

    result = delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)

    assert result["status"] == "PASS"
    for name in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
        assert (project_dir / name).exists()
        assert (project_dir / name).stat().st_size > 200
    assert "python" in (project_dir / "TEST_REPORT.md").read_text(encoding="utf-8")
    assert "degraded" in (project_dir / "DELIVERY_NOTES.md").read_text(encoding="utf-8").lower()

    bundle = project_dir / "final_project_bundle.zip"
    manifest_path = project_dir / "delivery_manifest.json"
    screenshot = project_dir / "screenshots" / "delivery_smoke_screenshot.png"
    assert bundle.exists() and bundle.stat().st_size > 1000
    assert screenshot.exists() and screenshot.stat().st_size > 100
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["evidence_status"]["smoke_command"]["status"] == "PASS"
    assert manifest["evidence_status"]["screenshot"]["status"] == "PASS"
    assert manifest["evidence_status"]["capability_manifest"]["status"] == "PASS"
    assert manifest["capability_manifest_path"].endswith("capability_manifest.json")
    assert manifest["capability_manifest"]["commercial_ready"] is False
    assert manifest["capability_manifest"]["capabilities"]["media_fixture"]["type"] == "wav"
    assert manifest["capability_manifest"]["capabilities"]["transcription"]["commercial_ready"] is False
    assert manifest["files"]["final_project_bundle.zip"]["sha256"]
    assert manifest["files"]["final_project_bundle.zip"]["size"] == bundle.stat().st_size
    assert manifest["files"]["capability_manifest.json"]["sha256"]
    assert manifest["files"]["transcription_adapter_result.json"]["sha256"]
    assert "transcription_status" in (project_dir / "TEST_REPORT.md").read_text(encoding="utf-8")
    assert "Transcription may be placeholder_transcription" in (project_dir / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    with zipfile.ZipFile(bundle) as zf:
        names = set(zf.namelist())
    assert "README.md" in names
    assert "TEST_REPORT.md" in names
    assert "DELIVERY_NOTES.md" in names
    assert "product_brief.md" in names
    assert "orchestrator.py" in names
    assert any(name.endswith("delivery_smoke_command.json") for name in names)


def test_builder_delivery_pass_does_not_change_upstream_statuses(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialized_project(tmp_path)

    delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)
    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert layers["requirement_decision_status"] == "PASS"
    assert layers["product_contract_status"] == "PASS"
    assert layers["implementation_status"] == "PASS"
    assert layers["delivery_status"] == "PASS"


def test_screenshot_blocked_does_not_count_as_screenshot(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialized_project(tmp_path)
    delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir, capture_screenshot=False)

    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert (project_dir / "screenshot_blocked.json").exists()
    assert layers["delivery_status"] != "PASS"
    assert "screenshot_missing" in layers["checks"]["delivery_missing"]


def test_smoke_command_failure_blocks_delivery_pass(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialized_project(tmp_path)

    delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir, smoke_command=[sys.executable, "missing_entry.py"])
    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert layers["delivery_status"] != "PASS"
    assert "smoke_command_failed" in layers["checks"]["delivery_missing"]


def test_zip_or_required_reports_missing_blocks_delivery_pass(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialized_project(tmp_path)
    delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)

    (project_dir / "final_project_bundle.zip").unlink()
    (project_dir / "README.md").unlink()
    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert layers["delivery_status"] != "PASS"
    assert "final_project_bundle.zip_missing" in layers["checks"]["delivery_missing"]
    assert "README.md_missing" in layers["checks"]["delivery_missing"]
