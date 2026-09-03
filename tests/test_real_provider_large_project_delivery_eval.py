import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.provider, pytest.mark.e2e, pytest.mark.slow]


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "generated" / "real_provider_large_project_delivery_eval"


ALLOWED_CLASSIFICATIONS = {
    "large_project_delivered_real_provider",
    "real_provider_generated_but_not_runnable",
    "real_provider_generated_but_missing_real_tests",
    "real_provider_generated_but_missing_visual_evidence",
    "real_provider_generated_but_missing_delivery_package",
    "interface_unavailable",
    "route_or_context_bug",
    "fake_success_detected",
    "internal_leak_detected",
}


def _load_json(name: str):
    path = OUT / name
    if not path.exists():
        pytest.skip(f"real provider delivery eval artifact is not present: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def test_real_provider_large_project_delivery_eval_is_honest() -> None:
    readiness = _load_json("provider_readiness.json")
    result = _load_json("real_provider_generation_result.json")
    transcript = _load_json("codex_e2e_transcript.json")

    classification = result.get("classification")
    assert classification in ALLOWED_CLASSIFICATIONS
    assert result.get("provider_mode") == "real_provider_api"

    if not readiness.get("provider_ready"):
        assert classification == "interface_unavailable"
        assert result.get("codex_sent_document", 0) == 0
        assert result.get("codex_sent_photo", 0) == 0
        return

    assert result.get("provider_ready") is True
    assert result.get("generation_status")
    assert result.get("public_delivery_gate_verdict") in {"PASS", "FAIL"}
    assert not result.get("fake_success_detected")
    assert not result.get("internal_term_leak")
    assert all(not row.get("fake_completion") for row in transcript)
    assert all(not row.get("internal_term_leak") for row in transcript)

    fully_delivered = classification == "large_project_delivered_real_provider"
    if fully_delivered:
        assert result.get("architecture_contract_verdict") == "PASS"
        assert result.get("runnable_contract_verdict") == "PASS"
        assert result.get("real_test_execution_verdict") == "PASS"
        assert result.get("visual_evidence_verdict") == "PASS"
        assert result.get("bundle_integrity_verdict") == "PASS"
        assert result.get("public_delivery_gate_verdict") == "PASS"
        assert result.get("codex_sent_document", 0) > 0
        assert result.get("codex_sent_photo", 0) > 0
    else:
        assert result.get("public_delivery_gate_verdict") != "PASS"
        assert result.get("missing_evidence")
        assert result.get("codex_sent_document", 0) == 0
