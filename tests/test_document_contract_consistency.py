from __future__ import annotations

import json
import pathlib
import re

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]


FORMAL_DOCS = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "docs" / "00_kernel_contract.md",
    ROOT / "docs" / "00_product_studio_contract.md",
    ROOT / "docs" / "01_contract_registry.md",
    ROOT / "docs" / "03_execution_flow.md",
    ROOT / "docs" / "04_acceptance_and_evidence.md",
    ROOT / "docs" / "06_agent_led_layered_architecture.md",
]


TELEGRAM_MAINLINE = (
    "customer request",
    "API/provider project generation",
    "provider output validation",
    "post-build finalization",
    "canonical test/runtime/visual evidence",
    "user review",
    "local_packager",
    "public delivery gate",
    "delivery receipt",
    "bind active project",
    "canonical final verdict",
)


def test_readme_and_kernel_contract_share_telegram_mainline() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    kernel = (ROOT / "docs" / "00_kernel_contract.md").read_text(encoding="utf-8")
    registry = (ROOT / "docs" / "01_contract_registry.md").read_text(encoding="utf-8")
    for item in TELEGRAM_MAINLINE:
        assert item in registry
        assert item in readme or item in kernel
    assert "local_packager" in readme
    assert "local_packager" in kernel


def test_formal_docs_use_cgkn_name_not_cgnk_formal_name() -> None:
    for path in FORMAL_DOCS:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"\bCGNK\b", text):
            window = text[max(0, match.start() - 80) : match.end() + 80].lower()
            assert any(token in window for token in ("legacy", "compatibility", "historical", "internal")), (
                f"{path.relative_to(ROOT)} uses CGNK outside a legacy/internal note"
            )


def test_docs_json_examples_validate_when_kind_has_schema() -> None:
    schemas = {
        "CGKNTestExecutionEvidence": ROOT / "schemas" / "test_execution_v1.schema.json",
        "CGKNCustomerRuntimeEvidence": ROOT / "schemas" / "customer_runtime_v1.schema.json",
        "CGKNVisualEvidence": ROOT / "schemas" / "visual_evidence_v1.schema.json",
        "CGKNUserReviewEvidence": ROOT / "schemas" / "user_review_v1.schema.json",
        "CGKNDeliveryManifest": ROOT / "schemas" / "delivery_manifest_v1.schema.json",
        "CGKNDeliveryReceipt": ROOT / "schemas" / "delivery_receipt_v1.schema.json",
        "CGKNFinalVerdict": ROOT / "schemas" / "final_verdict_v1.schema.json",
    }
    resolver = jsonschema.RefResolver.from_schema(
        json.loads((ROOT / "schemas" / "canonical_defs.schema.json").read_text(encoding="utf-8")),
        store={
            "canonical_defs.schema.json": json.loads((ROOT / "schemas" / "canonical_defs.schema.json").read_text(encoding="utf-8"))
        },
    )
    for doc in FORMAL_DOCS:
        text = doc.read_text(encoding="utf-8", errors="replace")
        for block in re.findall(r"```json\s*(.*?)```", text, flags=re.S):
            payload = json.loads(block)
            schema_path = schemas.get(payload.get("kind"))
            if schema_path is None:
                continue
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            jsonschema.validate(payload, schema, resolver=resolver)
