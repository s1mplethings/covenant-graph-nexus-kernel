from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_MODULE_IMPL_CONTRACT_MISMATCH, Diagnostic

MODULE_REF = "module.trace.summary@1"
OUTPUT_ARTIFACT_REF = "artifact.trace_summary@1"
OUTPUT_PORT = "summary"


def check_contract_conformance(contract: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    actual_ref = f"{contract.get('id')}@{contract.get('version')}"
    if actual_ref != MODULE_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.id", "Unexpected module contract ref", expected=MODULE_REF, actual=actual_ref, involved_ref=actual_ref))
    output = contract.get("ports", {}).get("output", {}).get(OUTPUT_PORT, {})
    if output.get("artifact_type") != OUTPUT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", f"$.ports.output.{OUTPUT_PORT}.artifact_type", "Unexpected output artifact ref", expected=OUTPUT_ARTIFACT_REF, actual=output.get("artifact_type"), involved_ref=MODULE_REF))
    effects = contract.get("effects", {})
    if effects.get("network") is not False or effects.get("provider_call") is not False or effects.get("fs_write") != []:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects", "Trace summary must be offline and workspace-write-free", expected={"network": False, "provider_call": False, "fs_write": []}, actual=effects, involved_ref=MODULE_REF))
    return diagnostics
