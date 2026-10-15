from __future__ import annotations

import json
import pathlib
import re

import pytest

from contracts.status import EVIDENCE_STATUSES, WORKFLOW_STATES

ROOT = pathlib.Path(__file__).resolve().parents[1]


FORBIDDEN_FORMAL_STATUSES = {
    "PARTIAL",
    "READY",
    "REWORK",
    "SKIPPED_WITH_REASON",
    "ready_with_warnings",
    "PASS_FINAL",
    "DELIVER_WITH_WARNINGS",
    "ASK_USER_REVIEW",
    "FACT_BLOCKED",
}


FORMAL_DOCS = [
    "README.md",
    "AGENTS.md",
    "docs/00_kernel_contract.md",
    "docs/00_product_studio_contract.md",
    "docs/01_contract_registry.md",
    "docs/03_execution_flow.md",
    "docs/04_acceptance_and_evidence.md",
    "docs/06_agent_led_layered_architecture.md",
]


def test_status_enum_matches_canonical_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "canonical_defs.schema.json").read_text(encoding="utf-8"))
    assert tuple(schema["$defs"]["EvidenceStatus"]["enum"]) == EVIDENCE_STATUSES
    assert tuple(schema["$defs"]["WorkflowState"]["enum"]) == WORKFLOW_STATES


def test_delivery_manifest_status_is_public_delivery_subset() -> None:
    schema = json.loads((ROOT / "schemas" / "delivery_manifest_v1.schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["status"]["enum"] == ["PASS", "PASS_WITH_LIMITS", "NEEDS_REWORK"]


@pytest.mark.historical_asset
@pytest.mark.skipif(not (ROOT / "docs/00_product_studio_contract.md").is_file(), reason="historical_asset: retired product-studio formal contract is not present")
def test_formal_docs_do_not_use_undeclared_statuses() -> None:
    for rel_path in FORMAL_DOCS:
        text = (ROOT / rel_path).read_text(encoding="utf-8", errors="replace")
        for forbidden in FORBIDDEN_FORMAL_STATUSES:
            assert re.search(rf"(?<!NEEDS_)\b{re.escape(forbidden)}\b", text) is None, (
                f"{rel_path} contains legacy status {forbidden}"
            )


def test_workflow_states_are_not_evidence_statuses() -> None:
    assert set(EVIDENCE_STATUSES).isdisjoint(WORKFLOW_STATES)
