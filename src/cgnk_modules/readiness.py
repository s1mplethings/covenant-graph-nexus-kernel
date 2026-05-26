from __future__ import annotations

import pathlib
from typing import Any

from cgnk_core.diagnostics import CGNK_MODULE_CHAIN_NOT_READY, Diagnostic

from .registry import ALL_MODULES, P0_MODULES, check_all_modules, check_p0_modules


def build_module_chain_readiness(chain: str = "p0", root: pathlib.Path | None = None) -> dict[str, Any]:
    if chain not in {"p0", "all"}:
        diagnostic = Diagnostic(CGNK_MODULE_CHAIN_NOT_READY, "error", "$.chain", "Unsupported module readiness chain", expected="p0 or all", actual=chain).as_dict()
        return {
            "kind": "ModuleChainReadiness",
            "schema_version": "1",
            "ok": False,
            "chain_id": chain,
            "modules": [],
            "missing_modules": [],
            "contract_failures": [],
            "deterministic_failures": [],
            "forbidden_dependency_failures": [],
            "diagnostics": [diagnostic],
            "readiness_status": "blocked",
        }

    registry_report = check_p0_modules(root) if chain == "p0" else check_all_modules(root)
    modules = [row["module_ref"] for row in registry_report["modules"]]
    diagnostics = list(registry_report["diagnostics"])
    missing_modules = [row["module_ref"] for row in registry_report["modules"] if not row.get("imports")]
    contract_failures = [row["module_ref"] for row in registry_report["modules"] if not row.get("contract_conformant")]
    deterministic_failures = [row["module_ref"] for row in registry_report["modules"] if not row.get("deterministic_output") or not row.get("plain_dict_output") or not row.get("json_serializable_output")]
    forbidden_dependency_failures = sorted({row.get("involved_ref", "") for row in diagnostics if row.get("code") in {"CGNK_MODULE_FORBIDDEN_IMPORT", "CGNK_MODULE_FORBIDDEN_EFFECT"} and row.get("involved_ref")})
    if missing_modules or contract_failures or deterministic_failures or forbidden_dependency_failures:
        diagnostics.append(
            Diagnostic(
                CGNK_MODULE_CHAIN_NOT_READY,
                "error",
                "$.modules",
                "P0 module chain is not ready for CTCP slice refactor",
                expected="all P0 modules import, conform, produce deterministic plain dicts, and avoid forbidden dependencies/effects",
                actual={
                    "missing_modules": missing_modules,
                    "contract_failures": contract_failures,
                    "deterministic_failures": deterministic_failures,
                    "forbidden_dependency_failures": forbidden_dependency_failures,
                },
            ).as_dict()
        )
    ok = not any(row["severity"] == "error" for row in diagnostics)
    return {
        "kind": "ModuleChainReadiness",
        "schema_version": "1",
        "ok": ok,
        "chain_id": chain,
        "modules": modules or [row["module_ref"] for row in (P0_MODULES if chain == "p0" else ALL_MODULES)],
        "missing_modules": missing_modules,
        "contract_failures": contract_failures,
        "deterministic_failures": deterministic_failures,
        "forbidden_dependency_failures": forbidden_dependency_failures,
        "diagnostics": diagnostics,
        "readiness_status": "ready_for_refactor" if ok else "blocked",
    }
