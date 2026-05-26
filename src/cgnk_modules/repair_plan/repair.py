from __future__ import annotations

from copy import deepcopy
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_ARTIFACT_NOT_FOUND,
    CGNK_EDGE_TYPE_MISMATCH,
    CGNK_GRAPH_CYCLE,
    CGNK_INPUT_UNBOUND,
    CGNK_MODULE_NOT_FOUND,
    CGNK_POLICY_CAPABILITY_DENIED,
    CGNK_POLICY_EFFECT_DENIED,
    CGNK_PROPOSAL_INVALID,
    CGNK_REPAIR_AMBIGUOUS,
    CGNK_REPAIR_NO_SAFE_FIX,
    CGNK_REPAIR_UNSUPPORTED_DIAGNOSTIC,
    Diagnostic,
)

REPAIRABLE_CODES = {
    CGNK_EDGE_TYPE_MISMATCH,
    CGNK_INPUT_UNBOUND,
    CGNK_MODULE_NOT_FOUND,
    CGNK_ARTIFACT_NOT_FOUND,
    CGNK_GRAPH_CYCLE,
    CGNK_POLICY_EFFECT_DENIED,
    CGNK_POLICY_CAPABILITY_DENIED,
    CGNK_PROPOSAL_INVALID,
}


def build_repair_plan(
    diagnostics: list[dict[str, Any]],
    proposal: dict[str, Any] | None = None,
    compiled_flow: dict[str, Any] | None = None,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_diagnostics = deepcopy(diagnostics or [])
    suggested_edits: list[dict[str, Any]] = []
    blocked_reasons: list[dict[str, Any]] = []
    for diagnostic in source_diagnostics:
        code = diagnostic.get("code")
        if code not in REPAIRABLE_CODES:
            blocked_reasons.append(_block(CGNK_REPAIR_UNSUPPORTED_DIAGNOSTIC, diagnostic, "Diagnostic is not supported by this repair planner"))
            continue
        hint_edits = _edits_from_hints(diagnostic)
        if len(hint_edits) == 1:
            suggested_edits.append(hint_edits[0])
        elif len(hint_edits) > 1:
            blocked_reasons.append(_block(CGNK_REPAIR_AMBIGUOUS, diagnostic, "Multiple deterministic repair hints are available"))
        else:
            fallback = _fallback_edit(diagnostic, compiled_flow, inventory)
            if fallback is None:
                blocked_reasons.append(_block(CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "No deterministic repair can be generated safely"))
            else:
                suggested_edits.append(fallback)
    confidence = "deterministic" if suggested_edits and not blocked_reasons else ("heuristic" if suggested_edits else "none")
    target_flow = (proposal or {}).get("target_flow") or (compiled_flow or {}).get("flow_ref") or ""
    output_diagnostics = list(blocked_reasons)
    return {
        "kind": "RepairPlan",
        "version": "1",
        "target_proposal": (proposal or {}).get("id", "proposal.unknown") + "@1",
        "target_flow": target_flow or "flow.unknown@1",
        "original_proposal": deepcopy(proposal or {"kind": "GraphEditProposal", "id": "proposal.unknown", "target_flow": target_flow or "flow.unknown@1", "edits": []}),
        "source_diagnostics": source_diagnostics,
        "suggested_edits": suggested_edits,
        "confidence": confidence,
        "requires_recompile": True,
        "blocked_reasons": blocked_reasons,
        "diagnostics": output_diagnostics,
    }


def _edits_from_hints(diagnostic: dict[str, Any]) -> list[dict[str, Any]]:
    edits = []
    for hint in diagnostic.get("repair_hints", []) or []:
        op = hint.get("op")
        if op == "disconnect":
            edits.append({"op": "disconnect", "from": hint.get("from"), "to": hint.get("to")})
        elif op == "replace_node":
            edits.append({"op": "replace_node", "target_node": hint.get("target_node"), "requires_selection": True})
        elif op == "disconnect_cycle_edge":
            edits.append({"op": "review_cycle_disconnect", "cycle_path": hint.get("cycle_path", [])})
    return [edit for edit in edits if all(value is not None for key, value in edit.items() if key in {"from", "to", "target_node"})]


def _fallback_edit(diagnostic: dict[str, Any], compiled_flow: dict[str, Any] | None, inventory: dict[str, Any] | None) -> dict[str, Any] | None:
    code = diagnostic.get("code")
    if code == CGNK_INPUT_UNBOUND and diagnostic.get("target"):
        return {"op": "connect_required_input", "target": diagnostic["target"], "requires_selection": True}
    if code == CGNK_EDGE_TYPE_MISMATCH and diagnostic.get("source") and diagnostic.get("target"):
        return {"op": "disconnect", "from": diagnostic["source"], "to": diagnostic["target"]}
    if code in {CGNK_MODULE_NOT_FOUND, CGNK_ARTIFACT_NOT_FOUND}:
        return {"op": "replace_missing_ref", "missing_ref": diagnostic.get("actual") or diagnostic.get("involved_ref"), "requires_selection": True}
    if code == CGNK_GRAPH_CYCLE:
        return {"op": "review_cycle_disconnect", "cycle_path": diagnostic.get("actual", [])}
    if code in {CGNK_POLICY_EFFECT_DENIED, CGNK_POLICY_CAPABILITY_DENIED}:
        return {"op": "replace_with_policy_allowed_module", "involved_ref": diagnostic.get("involved_ref"), "requires_selection": True}
    if code == CGNK_PROPOSAL_INVALID:
        return {"op": "repair_proposal_shape", "path": diagnostic.get("path"), "requires_schema_validation": True}
    return None


def _block(code: str, diagnostic: dict[str, Any], message: str) -> dict[str, Any]:
    return Diagnostic(code, "warning", diagnostic.get("path", "$.diagnostics"), message, actual=diagnostic.get("code"), involved_ref=diagnostic.get("involved_ref")).as_dict()
