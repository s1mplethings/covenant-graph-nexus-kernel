from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_MODULE_IMPL_CONTRACT_MISMATCH, Diagnostic

MODULE_REF = "module.project.build_graph@1"
INPUT_ARTIFACT_REF = "artifact.project_snapshot@1"
OUTPUT_ARTIFACT_REF = "artifact.project_graph@1"
INPUT_PORT = "snapshot"
OUTPUT_PORT = "graph"


def check_contract_conformance(contract: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    actual_ref = f"{contract.get('id')}@{contract.get('version')}"
    if actual_ref != MODULE_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.id", "Unexpected module contract ref", expected=MODULE_REF, actual=actual_ref, involved_ref=actual_ref))
    input_port = contract.get("ports", {}).get("input", {}).get(INPUT_PORT, {})
    if input_port.get("artifact_type") != INPUT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", f"$.ports.input.{INPUT_PORT}.artifact_type", "Unexpected input artifact ref", expected=INPUT_ARTIFACT_REF, actual=input_port.get("artifact_type"), involved_ref=MODULE_REF))
    output_port = contract.get("ports", {}).get("output", {}).get(OUTPUT_PORT, {})
    if output_port.get("artifact_type") != OUTPUT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", f"$.ports.output.{OUTPUT_PORT}.artifact_type", "Unexpected output artifact ref", expected=OUTPUT_ARTIFACT_REF, actual=output_port.get("artifact_type"), involved_ref=MODULE_REF))
    effects = contract.get("effects", {})
    if effects.get("network") is not False:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects.network", "Project graph builder must be offline", expected=False, actual=effects.get("network"), involved_ref=MODULE_REF))
    if effects.get("provider_call") is not False:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects.provider_call", "Project graph builder must not call providers", expected=False, actual=effects.get("provider_call"), involved_ref=MODULE_REF))
    if effects.get("fs_write") != []:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects.fs_write", "Project graph builder must not write workspace files", expected=[], actual=effects.get("fs_write"), involved_ref=MODULE_REF))
    return diagnostics
