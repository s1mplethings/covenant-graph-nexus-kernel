from __future__ import annotations

import importlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


FORMAL_ARTIFACTS = {
    "production_candidate_provenance": ("CGKNProductionCandidateProvenance", "schemas/production_candidate_provenance_v1.schema.json", "scripts/codex_conversation.py"),
    "provider_causal_trace": ("CGKNProviderCausalTrace", "schemas/provider_causal_trace_v1.schema.json", "scripts/codex_conversation.py"),
    "test_execution": ("CGKNTestExecutionEvidence", "schemas/test_execution_v1.schema.json", "scripts/real_test_execution.py"),
    "customer_runtime": ("CGKNCustomerRuntimeEvidence", "schemas/customer_runtime_v1.schema.json", "scripts/customer_runtime_runner.py"),
    "visual_evidence": ("CGKNVisualEvidence", "schemas/visual_evidence_v1.schema.json", "scripts/browser_visual_evidence.py"),
    "user_review": ("CGKNUserReviewEvidence", "schemas/user_review_v1.schema.json", "scripts/canonical_user_review.py"),
    "delivery_manifest": ("CGKNDeliveryManifest", "schemas/delivery_manifest_v1.schema.json", "scripts/local_packager.py"),
    "delivery_receipt": ("CGKNDeliveryReceipt", "schemas/delivery_receipt_v1.schema.json", "scripts/canonical_delivery_receipt.py"),
    "formal_gate_status": ("CGKNFormalGateStatus", "schemas/formal_gate_status_v1.schema.json", "scripts/formal_mainline_acceptance.py"),
    "final_verdict": ("CGKNFinalVerdict", "schemas/final_verdict_v1.schema.json", "scripts/acceptance_verifier.py"),
}


def load_schema(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_registry_lists_every_formal_artifact_schema_and_producer() -> None:
    registry = (ROOT / "docs" / "01_contract_registry.md").read_text(encoding="utf-8")
    for module_name, (kind, schema_path, producer) in FORMAL_ARTIFACTS.items():
        module = importlib.import_module(f"contracts.{module_name}")
        assert module.KIND == kind
        assert module.SCHEMA_PATH == schema_path
        assert module.PRODUCER == producer
        assert kind in registry
        assert schema_path in registry
        assert producer in registry
        assert (ROOT / schema_path).exists()


def test_formal_schemas_use_single_versioned_kind_and_envelope() -> None:
    for _module_name, (kind, schema_path, _producer) in FORMAL_ARTIFACTS.items():
        schema = load_schema(schema_path)
        assert schema["properties"]["kind"]["const"] == kind
        assert schema["allOf"] == [{"$ref": "canonical_defs.schema.json#/$defs/ArtifactEnvelope"}]
        for field in (
            "kind",
            "schema_version",
            "run_id",
            "candidate_id",
            "candidate_hash",
            "commit_sha",
            "producer",
            "created_at",
            "status",
            "artifact_hash",
        ):
            assert field in schema["required"]


def test_each_formal_artifact_has_one_registered_producer() -> None:
    registry = (ROOT / "docs" / "01_contract_registry.md").read_text(encoding="utf-8")
    for _module_name, (kind, _schema_path, producer) in FORMAL_ARTIFACTS.items():
        rows = [line for line in registry.splitlines() if line.startswith(f"| `{kind}` |")]
        assert len(rows) == 1
        assert producer in rows[0]
