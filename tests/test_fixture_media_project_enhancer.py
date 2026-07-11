from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import delivery_evidence_builder
import discovery_selection_lane
import implementation_structure_materializer
import planning_docs_materializer
import requirement_acceptance_check
import requirement_decision_lane


GOAL = "I need a local-first media review workbench with GUI, CLI, pipeline artifacts, and degraded mode."


def materialize_fixture_project(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    requirement_decision_lane.run_requirement_decision(GOAL, run_dir)
    discovery_selection_lane.run_discovery_selection(GOAL, run_dir / "discovery", candidate_count=4)
    planning_docs_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    implementation_structure_materializer.materialize(project_dir=project_dir, run_dir=run_dir)
    return project_dir, run_dir


def test_generated_media_project_runs_real_local_fixture_processing(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialize_fixture_project(tmp_path)

    result = delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)

    assert result["status"] == "PASS"
    assert "fixtures/media_fixture.json" in " ".join(result["smoke_command"]["argv"])
    segment_analysis = json.loads((project_dir / "segment_analysis.json").read_text(encoding="utf-8"))
    selected = json.loads((project_dir / "selected_segments.json").read_text(encoding="utf-8"))
    export = json.loads((project_dir / "export_results.json").read_text(encoding="utf-8"))
    assert segment_analysis["mode"] == "local_fixture_processing"
    assert segment_analysis["status"] == "degraded"
    assert segment_analysis["count"] >= 2
    assert any(item["candidate"] for item in segment_analysis["items"])
    assert selected["count"] >= 1
    assert export["count"] == 1
    assert export["items"][0]["clip_count"] >= 1
    assert export["not_real_ai_model"] is True


def test_delivery_manifest_records_fixture_artifact_hashes_and_sizes(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialize_fixture_project(tmp_path)

    delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)
    manifest = json.loads((project_dir / "delivery_manifest.json").read_text(encoding="utf-8"))

    for rel in ("fixtures/media_fixture.json", "fixtures/sample_audio.wav", "capability_manifest.json", "media_manifest.json", "segment_analysis.json", "export_results.json"):
        assert rel in manifest["files"]
        assert manifest["files"][rel]["sha256"]
        assert manifest["files"][rel]["size"] > 0
    assert manifest["capability_manifest_path"].endswith("capability_manifest.json")
    assert manifest["capability_manifest"]["commercial_ready"] is False
    assert manifest["capability_manifest"]["capabilities"]["media_fixture"]["type"] == "wav"
    assert manifest["capability_manifest"]["capabilities"]["media_metadata"]["status"] in {"python_wave_verified", "ffprobe_verified"}
    transcription = manifest["capability_manifest"]["capabilities"]["transcription"]
    assert transcription["status"] in {"placeholder_transcription", "local_model_unavailable", "local_model_verified", "failed"}
    assert transcription["commercial_ready"] is False
    assert "transcription_adapter_result.json" in manifest["files"]
    test_report = (project_dir / "TEST_REPORT.md").read_text(encoding="utf-8")
    delivery_notes = (project_dir / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    assert "adapter_status" in test_report
    assert "transcription_status" in test_report
    assert "Adapter Status" in delivery_notes
    assert "Transcription may be placeholder_transcription" in delivery_notes


def test_corrupt_fixture_hash_blocks_smoke_and_delivery_pass(tmp_path: pathlib.Path) -> None:
    project_dir, run_dir = materialize_fixture_project(tmp_path)
    fixture_path = project_dir / "fixtures" / "media_fixture.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    fixture["files"][0]["sha256"] = "0" * 64
    fixture_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = delivery_evidence_builder.build(project_dir=project_dir, run_dir=run_dir)
    manifest = json.loads((project_dir / "delivery_manifest.json").read_text(encoding="utf-8"))
    layers = requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=run_dir)

    assert result["status"] == "PARTIAL"
    assert result["smoke_command"]["status"] == "FAIL"
    assert "fixture_validation_failed" in result["smoke_command"]["stderr"]
    assert "sha256_mismatch" in result["smoke_command"]["stderr"]
    assert manifest["evidence_status"]["smoke_command"]["status"] == "FAIL"
    assert layers["delivery_status"] != "PASS"
    assert "smoke_command_failed" in layers["checks"]["delivery_missing"]
