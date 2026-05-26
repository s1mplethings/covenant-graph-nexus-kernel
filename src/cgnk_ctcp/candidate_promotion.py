from __future__ import annotations

from typing import Any

from cgnk_core.diagnostics import (
    CGNK_CTCP_CANDIDATE_NOT_REUSABLE,
    CGNK_CTCP_CANDIDATE_PROMOTION_INVALID,
    CGNK_CTCP_CONTRACT_SOURCE_TRACE_MISSING,
    CGNK_CTCP_PROMOTED_MODULE_INVALID,
    Diagnostic,
)
from cgnk_core.registry import ContractRegistry

FORBIDDEN_TRACE_SNIPPETS = (
    "\n",
    "def ",
    "class ",
    "import ",
    "return ",
    "lambda ",
    "final_output",
    "project_output",
    ".sqlite",
    ".db",
    ".zip",
)


def validate_candidate_promotion(inventory: dict[str, Any], transfer_plan: dict[str, Any], registry: ContractRegistry) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(
        Diagnostic(CGNK_CTCP_CANDIDATE_PROMOTION_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual)
        for d in registry.schema_loader.validate(inventory, "ctcp_module_inventory.schema.json", "$.inventory")
    )
    diagnostics.extend(
        Diagnostic(CGNK_CTCP_CANDIDATE_PROMOTION_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual)
        for d in registry.schema_loader.validate(transfer_plan, "ctcp_transfer_plan.schema.json", "$.transfer_plan")
    )

    candidates = {row["id"]: row for row in inventory.get("candidates", [])}
    promoted: list[str] = []
    for index, row in enumerate(transfer_plan.get("modules", [])):
        candidate_id = row.get("candidate", "")
        module_ref = row.get("target_module", "")
        candidate = candidates.get(candidate_id)
        path = f"$.modules[{index}]"
        if row.get("copy_old_code") is not False:
            diagnostics.append(Diagnostic(CGNK_CTCP_CANDIDATE_PROMOTION_INVALID, "error", f"{path}.copy_old_code", "Promotion must not copy old CTCP code", expected=False, actual=row.get("copy_old_code"), involved_ref=candidate_id))
        if candidate is None:
            diagnostics.append(Diagnostic(CGNK_CTCP_CANDIDATE_PROMOTION_INVALID, "error", f"{path}.candidate", "Promoted candidate is missing from curated inventory", expected="candidate in inventory", actual=candidate_id, involved_ref=candidate_id))
            continue
        classification = candidate.get("classification", {})
        if classification.get("role") != "reusable_middle_capability" or classification.get("migration_value") not in {"high", "medium"} or not candidate.get("transfer", {}).get("recommended", False):
            diagnostics.append(Diagnostic(CGNK_CTCP_CANDIDATE_NOT_REUSABLE, "error", f"{path}.candidate", "Promoted candidate is not an eligible reusable middle capability", expected="reusable high/medium recommended candidate", actual=classification, involved_ref=candidate_id))
        module = registry.resolve_module(module_ref)
        if module is None:
            diagnostics.append(Diagnostic(CGNK_CTCP_PROMOTED_MODULE_INVALID, "error", f"{path}.target_module", "Target ModuleContract is missing", expected="known module ref", actual=module_ref, involved_ref=module_ref))
            continue
        trace = module.get("source_trace")
        if not trace:
            diagnostics.append(Diagnostic(CGNK_CTCP_CONTRACT_SOURCE_TRACE_MISSING, "error", f"{module_ref}.source_trace", "Promoted ModuleContract must include source_trace", expected="source_trace object", actual=None, involved_ref=module_ref))
            continue
        if trace.get("candidate") != candidate_id:
            diagnostics.append(Diagnostic(CGNK_CTCP_CONTRACT_SOURCE_TRACE_MISSING, "error", f"{module_ref}.source_trace.candidate", "Module source_trace does not point at promoted candidate", expected=candidate_id, actual=trace.get("candidate"), involved_ref=module_ref))
        copied = _copied_code_evidence(trace)
        if copied:
            diagnostics.append(Diagnostic(CGNK_CTCP_PROMOTED_MODULE_INVALID, "error", f"{module_ref}.source_trace", "source_trace appears to embed implementation code or forbidden output paths", expected="paths/symbols/evidence only", actual=copied, involved_ref=module_ref))
        promoted.append(module_ref)

    return {
        "kind": "CTCPCandidatePromotionReport",
        "ok": not any(d.severity == "error" for d in diagnostics),
        "promoted_modules": sorted(set(promoted)),
        "diagnostics": [d.as_dict() for d in diagnostics],
    }


def _copied_code_evidence(trace: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for value in [trace.get("candidate"), *trace.get("legacy_files", []), *trace.get("legacy_symbols", []), *trace.get("evidence_keywords", [])]:
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        if any(snippet in lowered for snippet in FORBIDDEN_TRACE_SNIPPETS):
            findings.append(value)
    return findings
