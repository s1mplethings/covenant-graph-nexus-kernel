from __future__ import annotations

import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import asr_reference_transcript_eval
import commercial_promotion_gate
import delivery_evidence_builder
import implementation_structure_materializer
import local_media_adapter
import real_asr_adapter_contract


def candidate_evidence(tmp_path: pathlib.Path, *, transcript_text: str = "verified local transcript") -> tuple[dict, pathlib.Path]:
    sample_results: list[dict] = []
    references: list[dict] = []
    for index in range(3):
        audio = tmp_path / f"sample_{index + 1}.wav"
        local_media_adapter.create_tiny_wav(audio, duration_seconds=0.2)
        transcript = tmp_path / f"transcript_{index + 1}.json"
        transcript.write_text(json.dumps({"text": transcript_text}), encoding="utf-8")
        sample_results.append(
            {
                "input_path": str(audio),
                "transcript_path": str(transcript),
                "schema_valid": True,
                "status": "real_local_asr_verified",
            }
        )
        references.append(
            {
                "sample_id": f"sample-{index + 1}",
                "audio_path": audio.name,
                "reference_text": "verified local transcript",
                "language": "en",
                "expected_min_duration": 0.1,
                "sha256": asr_reference_transcript_eval.sha256(audio),
            }
        )
    manifest = tmp_path / "reference_transcript_manifest.json"
    manifest.write_text(json.dumps({"samples": references}), encoding="utf-8")
    capability = {
        "commercial_ready": False,
        "capabilities": {
            "asr": {
                "status": "production_asr_candidate",
                "adapter_kind": "real_local_asr",
                "evidence_tier": "production_candidate",
                "degraded": False,
                "commercial_ready": False,
            },
            "asr_quality": {
                "adapter_kind": "real_local_asr",
                "evidence_tier": "production_candidate",
                "asr_quality_status": "production_candidate",
                "production_candidate": True,
                "production_verified": False,
                "sample_count": 3,
                "successful_samples": 3,
                "failed_samples": 0,
                "timeout_samples": 0,
                "invalid_output_samples": 0,
                "success_rate": 1.0,
                "non_empty_text_rate": 1.0,
                "non_empty_segments_rate": 1.0,
                "sample_results": sample_results,
            },
            "media_decode": {"status": "verified"},
            "user_media_input": {"status": "verified"},
        },
    }
    return capability, manifest


def fixture_capability() -> dict:
    return {
        "commercial_ready": False,
        "capabilities": {
            "asr": {"adapter_kind": "contract_fixture", "evidence_tier": "contract_fixture", "degraded": True},
            "asr_quality": {
                "adapter_kind": "fixture",
                "evidence_tier": "contract_fixture",
                "asr_quality_status": "contract_only",
                "production_candidate": False,
                "production_verified": False,
                "sample_count": 3,
                "successful_samples": 3,
                "failed_samples": 0,
                "timeout_samples": 0,
                "invalid_output_samples": 0,
                "success_rate": 1.0,
                "non_empty_text_rate": 1.0,
                "non_empty_segments_rate": 1.0,
                "sample_results": [],
            },
            "media_decode": {"status": "verified"},
            "user_media_input": {"status": "verified"},
        },
    }


def evaluate(tmp_path: pathlib.Path, capability: dict, manifest: pathlib.Path | None = None, **kwargs) -> dict:
    return commercial_promotion_gate.evaluate(
        project_dir=tmp_path,
        capability_manifest=capability,
        delivery_integrity_status=kwargs.pop("delivery_integrity_status", "PASS"),
        reference_manifest_path=manifest,
        **kwargs,
    )


def test_fixture_contract_only_cannot_be_candidate(tmp_path: pathlib.Path) -> None:
    report = evaluate(tmp_path, fixture_capability())

    assert report["promotion_decision"] == "COMMERCIAL_BETA_PLUS"
    assert report["commercial_ready"] is False
    assert "fixture_or_non_real_asr_adapter" in report["promotion_blockers"]


@pytest.mark.parametrize("tier", ["none", "placeholder", "single_sample_real"])
def test_none_placeholder_and_single_sample_cannot_be_candidate(tmp_path: pathlib.Path, tier: str) -> None:
    capability = fixture_capability()
    quality = capability["capabilities"]["asr_quality"]
    quality.update({"adapter_kind": "none" if tier in {"none", "placeholder"} else "real_local_asr", "evidence_tier": tier, "asr_quality_status": "not_ready", "successful_samples": 0})

    report = evaluate(tmp_path, capability)

    assert report["promotion_decision"] == "COMMERCIAL_BETA"
    if tier == "none":
        assert "missing_real_asr_command" in report["promotion_blockers"]


def test_real_multi_sample_without_references_cannot_be_candidate(tmp_path: pathlib.Path) -> None:
    capability, _ = candidate_evidence(tmp_path)

    report = evaluate(tmp_path, capability)

    assert report["promotion_decision"] != "COMMERCIAL_CANDIDATE"
    assert "missing_reference_transcripts" in report["promotion_blockers"]


def test_all_candidate_conditions_pass_but_commercial_ready_stays_false(tmp_path: pathlib.Path) -> None:
    capability, manifest = candidate_evidence(tmp_path)

    report = evaluate(tmp_path, capability, manifest)

    assert report["promotion_decision"] == "COMMERCIAL_CANDIDATE"
    assert report["readiness_level"] == "COMMERCIAL_CANDIDATE"
    assert report["promotion_blockers"] == []
    assert report["reference_transcript_coverage"] == 1.0
    assert report["quality_metrics"]["token_error_rate"] == 0.0
    assert report["commercial_ready"] is False


def test_quality_below_threshold_blocks_candidate(tmp_path: pathlib.Path) -> None:
    capability, manifest = candidate_evidence(tmp_path, transcript_text="unrelated output")

    report = evaluate(tmp_path, capability, manifest)

    assert report["promotion_decision"] != "COMMERCIAL_CANDIDATE"
    assert "token_error_rate_above_threshold" in report["promotion_blockers"]
    assert "character_error_rate_above_threshold" in report["promotion_blockers"]


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("timeout_samples", 1, "timeout_count_above_promotion_threshold"),
        ("invalid_output_samples", 1, "invalid_output_count_above_promotion_threshold"),
    ],
)
def test_timeout_and_invalid_output_block_candidate(tmp_path: pathlib.Path, field: str, value: int, blocker: str) -> None:
    capability, manifest = candidate_evidence(tmp_path)
    capability["capabilities"]["asr_quality"][field] = value

    report = evaluate(tmp_path, capability, manifest)

    assert report["promotion_decision"] != "COMMERCIAL_CANDIDATE"
    assert blocker in report["promotion_blockers"]


def test_delivery_integrity_failure_blocks_candidate(tmp_path: pathlib.Path) -> None:
    capability, manifest = candidate_evidence(tmp_path)

    report = evaluate(tmp_path, capability, manifest, delivery_integrity_status="FAIL")

    assert "delivery_integrity_not_pass" in report["promotion_blockers"]


def test_missing_production_decode_blocks_candidate(tmp_path: pathlib.Path) -> None:
    capability, manifest = candidate_evidence(tmp_path)
    capability["capabilities"]["media_decode"]["status"] = "not_attempted"

    report = evaluate(tmp_path, capability, manifest)

    assert "production_decode_evidence_missing" in report["promotion_blockers"]


def test_delivery_manifest_and_reports_reference_fixture_promotion_report(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    run_dir = tmp_path / "run"
    implementation_structure_materializer.materialize(project_dir=project, run_dir=run_dir)
    command = f'"{sys.executable}" "{project / "real_asr_adapter_contract.py"}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
    monkeypatch.setenv(real_asr_adapter_contract.ENV_COMMAND, command)
    monkeypatch.setenv("CGKN_REAL_ASR_ADAPTER_KIND", "fixture")
    monkeypatch.setenv("CGKN_REAL_ASR_MULTI_SAMPLE_EVAL", "1")
    monkeypatch.setenv("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT", "3")
    monkeypatch.setenv("CGKN_COMMERCIAL_PROMOTION_GATE", "1")

    result = delivery_evidence_builder.build(
        project_dir=project,
        run_dir=run_dir,
        smoke_command=[sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."],
        capture_screenshot=True,
    )

    assert result["status"] == "PASS"
    report = json.loads((project / "production_asr_verification_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((project / "delivery_manifest.json").read_text(encoding="utf-8"))
    assert report["promotion_decision"] == "COMMERCIAL_BETA_PLUS"
    assert report["commercial_ready"] is False
    assert "production_asr_verification_report.json" in manifest["files"]
    assert "commercial_promotion_decision: COMMERCIAL_BETA_PLUS" in (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    notes = (project / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    assert "commercial_promotion_blockers:" in notes
    assert "COMMERCIAL_CANDIDATE is not COMMERCIAL_READY" in notes
