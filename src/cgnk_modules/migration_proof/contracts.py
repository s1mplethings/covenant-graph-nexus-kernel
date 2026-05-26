from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_MODULE_IMPL_CONTRACT_MISMATCH, Diagnostic

MODULE_REF = "module.migration.proof@1"
OUTPUT_ARTIFACT_REF = "artifact.migration_proof@1"


def check_contract_conformance(contract: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    actual_ref = f"{contract.get('id')}@{contract.get('version')}"
    if actual_ref != MODULE_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.id", "Unexpected module contract ref", expected=MODULE_REF, actual=actual_ref, involved_ref=actual_ref))
    output = contract.get("ports", {}).get("output", {}).get("migration_proof", {})
    if output.get("artifact_type") != OUTPUT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.ports.output.migration_proof.artifact_type", "Unexpected migration proof output artifact", expected=OUTPUT_ARTIFACT_REF, actual=output.get("artifact_type"), involved_ref=MODULE_REF))
    effects = contract.get("effects", {})
    if effects.get("network") is not False or effects.get("provider_call") is not False or effects.get("fs_write") != []:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects", "Migration proof module must be offline and read-only", expected={"network": False, "provider_call": False, "fs_write": []}, actual=effects, involved_ref=MODULE_REF))
    return {"ok": not diagnostics, "diagnostics": [d.as_dict() for d in diagnostics]}
