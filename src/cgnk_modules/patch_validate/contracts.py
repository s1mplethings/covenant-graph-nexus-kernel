from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import CGNK_MODULE_IMPL_CONTRACT_MISMATCH, Diagnostic

MODULE_REF = "module.patch.validate@1"
INPUT_ARTIFACT_REF = "artifact.patch_manifest@1"
SNAPSHOT_ARTIFACT_REF = "artifact.project_snapshot@1"
OUTPUT_ARTIFACT_REF = "artifact.validation_report@1"
PASSTHROUGH_ARTIFACT_REF = "artifact.patch_manifest@1"


def check_contract_conformance(contract: dict[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    actual_ref = f"{contract.get('id')}@{contract.get('version')}"
    if actual_ref != MODULE_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.id", "Unexpected module contract ref", expected=MODULE_REF, actual=actual_ref, involved_ref=actual_ref))
    inputs = contract.get("ports", {}).get("input", {})
    outputs = contract.get("ports", {}).get("output", {})
    if inputs.get("patch_manifest", {}).get("artifact_type") != INPUT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.ports.input.patch_manifest.artifact_type", "Unexpected patch_manifest input artifact", expected=INPUT_ARTIFACT_REF, actual=inputs.get("patch_manifest", {}).get("artifact_type"), involved_ref=MODULE_REF))
    if inputs.get("snapshot", {}).get("artifact_type") != SNAPSHOT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.ports.input.snapshot.artifact_type", "Unexpected snapshot input artifact", expected=SNAPSHOT_ARTIFACT_REF, actual=inputs.get("snapshot", {}).get("artifact_type"), involved_ref=MODULE_REF))
    if outputs.get("validation_report", {}).get("artifact_type") != OUTPUT_ARTIFACT_REF:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.ports.output.validation_report.artifact_type", "Unexpected validation_report output artifact", expected=OUTPUT_ARTIFACT_REF, actual=outputs.get("validation_report", {}).get("artifact_type"), involved_ref=MODULE_REF))
    effects = contract.get("effects", {})
    if effects.get("network") is not False:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects.network", "Patch validation must be offline", expected=False, actual=effects.get("network"), involved_ref=MODULE_REF))
    if effects.get("provider_call") is not False:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects.provider_call", "Patch validation must not call providers", expected=False, actual=effects.get("provider_call"), involved_ref=MODULE_REF))
    if effects.get("fs_write") != []:
        diagnostics.append(Diagnostic(CGNK_MODULE_IMPL_CONTRACT_MISMATCH, "error", "$.effects.fs_write", "Patch validation must not write workspace files", expected=[], actual=effects.get("fs_write"), involved_ref=MODULE_REF))
    return diagnostics
