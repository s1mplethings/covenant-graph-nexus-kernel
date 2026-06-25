from __future__ import annotations

import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import commercial_ready_gate
import delivery_evidence_builder
import implementation_structure_materializer
import production_reliability_gate
import real_asr_adapter_contract


def candidate_capability() -> dict:
    return {
        "commercial_ready": False,
        "capabilities": {
            "asr": {
                "adapter_kind": "real_local_asr",
                "evidence_tier": "production_candidate",
                "production_asr": True,
                "degraded": False,
            },
            "asr_quality": {
                "adapter_kind": "real_local_asr",
                "evidence_tier": "production_candidate",
                "asr_quality_status": "production_candidate",
                "sample_count": 3,
                "failed_samples": 0,
                "timeout_samples": 0,
                "invalid_output_samples": 0,
            },
            "media_decode": {"status": "verified"},
            "user_media_input": {"status": "verified"},
        },
    }


def candidate_promotion() -> dict:
    return {
        "promotion_decision": "COMMERCIAL_CANDIDATE",
        "adapter_kind": "real_local_asr",
        "evidence_tier": "production_candidate",
        "reference_transcript_coverage": 1.0,
        "quality_metrics": {
            "normalized_text_match_rate": 1.0,
            "token_error_rate": 0.0,
            "character_error_rate": 0.0,
        },
        "promotion_blockers": [],
        "report_path": "production_asr_verification_report.json",
    }


def passing_reliability() -> dict:
    return production_reliability_gate.evaluate(
        run_records=[
            {"status": "PASS", "artifact_integrity_status": "PASS", "output_hash": "same", "runtime_seconds": 0.5}
            for _ in range(3)
        ],
        gate_test_only=True,
    )


def approved_review() -> dict:
    return {
        "reviewer": "local gate test reviewer",
        "reviewed_at": "2026-06-24T00:00:00+00:00",
        "sample_count_reviewed": 3,
        "approved": True,
        "notes": "Gate test evidence only; not current production readiness proof.",
        "blocking_findings": [],
        "review_scope": ["transcript accuracy", "failure handling", "artifact traceability"],
    }


def evaluate(tmp_path: pathlib.Path, **overrides) -> dict:
    args = {
        "project_dir": tmp_path,
        "capability_manifest": candidate_capability(),
        "promotion_report": candidate_promotion(),
        "reliability_report": passing_reliability(),
        "human_review_evidence": approved_review(),
        "artifact_integrity_status": "PASS",
        "delivery_status": "PASS",
        "enabled": True,
        "gate_test_only": True,
    }
    args.update(overrides)
    return commercial_ready_gate.evaluate(**args)


def test_fixture_contract_only_is_not_ready(tmp_path: pathlib.Path) -> None:
    capability = candidate_capability()
    capability["capabilities"]["asr"].update({"adapter_kind": "contract_fixture", "evidence_tier": "contract_fixture", "production_asr": False, "degraded": True})
    capability["capabilities"]["asr_quality"].update({"adapter_kind": "fixture", "evidence_tier": "contract_fixture", "asr_quality_status": "contract_only"})
    promotion = candidate_promotion()
    promotion.update({"promotion_decision": "COMMERCIAL_BETA_PLUS", "adapter_kind": "fixture", "evidence_tier": "contract_fixture"})

    report = evaluate(tmp_path, capability_manifest=capability, promotion_report=promotion)

    assert report["ready_decision"] == "NOT_READY"
    assert report["commercial_ready"] is False


def test_candidate_does_not_auto_become_ready(tmp_path: pathlib.Path) -> None:
    reliability = production_reliability_gate.empty_report()

    report = evaluate(tmp_path, reliability_report=reliability)

    assert report["ready_decision"] == "COMMERCIAL_CANDIDATE"
    assert report["commercial_ready"] is False


def test_missing_human_review_requires_review(tmp_path: pathlib.Path) -> None:
    report = evaluate(tmp_path, human_review_evidence=None)

    assert report["ready_decision"] == "REVIEW_REQUIRED"
    assert report["human_review_status"] == "missing"
    assert report["commercial_ready"] is False


@pytest.mark.parametrize(
    ("review_change", "blocker"),
    [
        ({"approved": False}, "human_review_not_approved"),
        ({"blocking_findings": ["bad transcript"]}, "human_review_has_blocking_findings"),
    ],
)
def test_rejected_human_review_cannot_be_ready(tmp_path: pathlib.Path, review_change: dict, blocker: str) -> None:
    review = approved_review()
    review.update(review_change)

    report = evaluate(tmp_path, human_review_evidence=review)

    assert report["commercial_ready"] is False
    assert blocker in report["critical_blockers"]


@pytest.mark.parametrize(
    ("override", "blocker"),
    [
        ({"artifact_integrity_status": "FAIL"}, "ready_artifact_integrity_not_pass"),
        ({"delivery_status": "FAIL"}, "ready_delivery_evidence_not_pass"),
    ],
)
def test_delivery_and_artifact_failures_block_ready(tmp_path: pathlib.Path, override: dict, blocker: str) -> None:
    report = evaluate(tmp_path, **override)

    assert report["commercial_ready"] is False
    assert blocker in report["critical_blockers"]


def test_missing_decode_blocks_ready(tmp_path: pathlib.Path) -> None:
    capability = candidate_capability()
    capability["capabilities"]["media_decode"]["status"] = "not_attempted"

    report = evaluate(tmp_path, capability_manifest=capability)

    assert "ready_production_decode_missing" in report["critical_blockers"]


def test_missing_reference_transcripts_blocks_ready(tmp_path: pathlib.Path) -> None:
    promotion = candidate_promotion()
    promotion["reference_transcript_coverage"] = 0.0

    report = evaluate(tmp_path, promotion_report=promotion)

    assert "ready_reference_transcript_coverage_below_threshold" in report["critical_blockers"]


def test_no_real_asr_command_evidence_is_not_ready(tmp_path: pathlib.Path) -> None:
    capability = candidate_capability()
    capability["capabilities"]["asr"].update({"adapter_kind": "none", "evidence_tier": "none", "production_asr": False, "degraded": True})
    promotion = candidate_promotion()
    promotion.update({"promotion_decision": "COMMERCIAL_BETA", "adapter_kind": "none", "evidence_tier": "none"})

    report = evaluate(tmp_path, capability_manifest=capability, promotion_report=promotion)

    assert report["ready_decision"] == "NOT_READY"
    assert report["commercial_ready"] is False


def test_all_ready_conditions_allow_ready_only_as_gate_test(tmp_path: pathlib.Path) -> None:
    output = tmp_path / "commercial_ready_report.json"

    report = evaluate(tmp_path, output_path=output)

    assert report["ready_decision"] == "COMMERCIAL_READY"
    assert report["commercial_ready"] is True
    assert report["critical_blockers"] == []
    assert report["reason"]
    assert report["evidence_references"]["promotion_report"]
    assert report["gate_test_only"] is True
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_human_review_schema_contains_required_contract(tmp_path: pathlib.Path) -> None:
    path = commercial_ready_gate.write_human_review_schema(tmp_path / "human_review_evidence.schema.json")
    schema = json.loads(path.read_text(encoding="utf-8"))

    assert set(schema["required"]) == commercial_ready_gate.HUMAN_REVIEW_FIELDS
    assert schema["properties"]["approved"]["type"] == "boolean"


def test_delivery_evidence_records_fixture_ready_rejection(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    run_dir = tmp_path / "run"
    implementation_structure_materializer.materialize(project_dir=project, run_dir=run_dir)
    command = f'"{sys.executable}" "{project / "real_asr_adapter_contract.py"}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
    monkeypatch.setenv(real_asr_adapter_contract.ENV_COMMAND, command)
    monkeypatch.setenv("CGKN_REAL_ASR_ADAPTER_KIND", "fixture")
    monkeypatch.setenv("CGKN_REAL_ASR_MULTI_SAMPLE_EVAL", "1")
    monkeypatch.setenv("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT", "3")
    monkeypatch.setenv("CGKN_COMMERCIAL_PROMOTION_GATE", "1")
    monkeypatch.setenv("CGKN_COMMERCIAL_READY_GATE", "1")

    result = delivery_evidence_builder.build(
        project_dir=project,
        run_dir=run_dir,
        smoke_command=[sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."],
        capture_screenshot=True,
    )

    assert result["status"] == "PASS"
    ready = json.loads((project / "commercial_ready_report.json").read_text(encoding="utf-8"))
    reliability = json.loads((project / "production_reliability_report.json").read_text(encoding="utf-8"))
    manifest = json.loads((project / "delivery_manifest.json").read_text(encoding="utf-8"))
    assert ready["ready_decision"] == "NOT_READY"
    assert ready["commercial_ready"] is False
    assert reliability["reliability_status"] == "not_ready"
    assert "commercial_ready_report.json" in manifest["files"]
    assert "production_reliability_report.json" in manifest["files"]
    assert "commercial_ready_decision: NOT_READY" in (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    notes = (project / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    assert "commercial_ready_blockers:" in notes
    assert "Fixture gate tests" in notes
