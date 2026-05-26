from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import (
    CGNK_RUNTIME_ADAPTER_INVALID,
    CGNK_RUNTIME_EXECUTION_FORBIDDEN,
    CGNK_RUNTIME_PATCH_APPLY_FORBIDDEN,
    CGNK_RUNTIME_PROVIDER_FORBIDDEN,
    CGNK_RUNTIME_WORKSPACE_WRITE_FORBIDDEN,
    Diagnostic,
)
from cgnk_core.schema_loader import SchemaLoader


def validate_runtime_adapter_contract(contract: dict[str, Any], schema_loader: SchemaLoader) -> list[Diagnostic]:
    diagnostics = [
        Diagnostic(CGNK_RUNTIME_ADAPTER_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual)
        for d in schema_loader.validate(contract, "runtime_adapter_contract.schema.json", "$.runtime_adapter")
    ]
    if contract.get("can_execute") is True:
        diagnostics.append(Diagnostic(CGNK_RUNTIME_EXECUTION_FORBIDDEN, "error", "$.can_execute", "Runtime execution is forbidden in CGNK core", expected=False, actual=True, involved_ref=contract.get("id")))
    if contract.get("can_call_provider") is True:
        diagnostics.append(Diagnostic(CGNK_RUNTIME_PROVIDER_FORBIDDEN, "error", "$.can_call_provider", "Provider calls are forbidden in CGNK core", expected=False, actual=True, involved_ref=contract.get("id")))
    if contract.get("can_write_workspace") is True:
        diagnostics.append(Diagnostic(CGNK_RUNTIME_WORKSPACE_WRITE_FORBIDDEN, "error", "$.can_write_workspace", "Workspace writes are forbidden in CGNK runtime adapter contracts", expected=False, actual=True, involved_ref=contract.get("id")))
    if contract.get("can_apply_patch") is True:
        diagnostics.append(Diagnostic(CGNK_RUNTIME_PATCH_APPLY_FORBIDDEN, "error", "$.can_apply_patch", "Patch application is forbidden in CGNK core", expected=False, actual=True, involved_ref=contract.get("id")))
    return diagnostics
