from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import asr_evidence_tier


def test_placeholder_and_contract_fixture_tiers_are_distinct() -> None:
    assert asr_evidence_tier.tier_for_status("placeholder_transcription") == "placeholder"
    assert asr_evidence_tier.tier_for_status("command_fixture_transcription") == "contract_fixture"
    assert asr_evidence_tier.tier_for_status("asr_contract_fixture_verified") == "contract_fixture"
    assert asr_evidence_tier.tier_for_status("real_local_asr_verified") == "single_sample_real"


def test_contract_fixture_detection_does_not_count_as_production() -> None:
    transcript = {
        "engine": "cgkn_contract_fixture_engine",
        "model_name": "contract-fixture-asr-v1",
        "contract_test_fixture": True,
        "evidence": ["contract test fixture"],
    }
    section = asr_evidence_tier.normalize_section(
        {
            "status": "asr_contract_fixture_verified",
            "production_asr": True,
            "commercial_ready": True,
        }
    )

    assert asr_evidence_tier.is_contract_fixture(transcript) is True
    assert section["evidence_tier"] == "contract_fixture"
    assert section["production_asr"] is False
    assert section["commercial_ready"] is False
    assert "contract_fixture_is_not_production_asr" in asr_evidence_tier.production_readiness_blockers(section)


def test_single_sample_real_has_production_blocker() -> None:
    blockers = asr_evidence_tier.production_readiness_blockers(
        {"status": "real_local_asr_verified", "evidence_tier": "single_sample_real"}
    )

    assert "single_sample_real_asr_is_not_production_evidence" in blockers
