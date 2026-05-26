from __future__ import annotations

from copy import deepcopy
from typing import Any

from .diagnostics import (
    CGNK_ARTIFACT_NOT_FOUND,
    CGNK_EDGE_TYPE_MISMATCH,
    CGNK_GRAPH_CYCLE,
    CGNK_INPUT_UNBOUND,
    CGNK_MODULE_NOT_FOUND,
    CGNK_POLICY_CAPABILITY_DENIED,
    CGNK_POLICY_EFFECT_DENIED,
    CGNK_REPAIR_AMBIGUOUS,
    CGNK_REPAIR_NO_SAFE_FIX,
    CGNK_REPAIR_PLAN_INVALID,
    CGNK_REPAIR_UNSUPPORTED_DIAGNOSTIC,
    Diagnostic,
)
from .graph_edit import apply_graph_edit_proposal
from .registry import ContractRegistry


def build_repair_plan(proposal: dict[str, Any], flow_ref: str, registry: ContractRegistry) -> dict[str, Any]:
    preview = apply_graph_edit_proposal(proposal, registry, dry_run=True)
    source_diagnostics = deepcopy(preview.get("diagnostics", []))
    base_flow = registry.resolve_flow(flow_ref or proposal.get("target_flow", ""))
    flow = _flow_with_proposed_nodes(base_flow, proposal)
    suggested_edits: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for diagnostic in source_diagnostics:
        code = diagnostic.get("code")
        if code == CGNK_EDGE_TYPE_MISMATCH:
            _repair_edge_type_mismatch(diagnostic, proposal, flow, registry, suggested_edits, blocked)
        elif code == CGNK_INPUT_UNBOUND:
            _repair_unbound_input(diagnostic, flow, registry, suggested_edits, blocked)
        elif code == CGNK_GRAPH_CYCLE:
            hints = [h for h in diagnostic.get("repair_hints", []) if h.get("op") in {"disconnect", "disconnect_cycle_edge"}]
            if hints:
                suggested_edits.append({"op": "review_cycle_disconnect", "hint": hints[0]})
            else:
                _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Cycle diagnostic did not include a deterministic disconnect hint")
        elif code in {CGNK_POLICY_EFFECT_DENIED, CGNK_POLICY_CAPABILITY_DENIED}:
            _repair_policy_denial(diagnostic, proposal, flow, registry, suggested_edits, blocked)
        elif code in {CGNK_MODULE_NOT_FOUND, CGNK_ARTIFACT_NOT_FOUND}:
            _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Missing contract refs require an explicit replacement ref")
        else:
            _block(blocked, CGNK_REPAIR_UNSUPPORTED_DIAGNOSTIC, diagnostic, "Diagnostic is not supported by deterministic repair")

    confidence = "deterministic" if suggested_edits and not blocked else ("none" if not suggested_edits else "heuristic")
    plan = {
        "kind": "RepairPlan",
        "version": "1",
        "target_proposal": proposal.get("id", "proposal.unknown") + "@1",
        "target_flow": flow_ref or proposal.get("target_flow", ""),
        "original_proposal": deepcopy(proposal),
        "source_diagnostics": source_diagnostics,
        "suggested_edits": suggested_edits,
        "confidence": confidence,
        "requires_recompile": True,
        "blocked_reasons": blocked,
        "diagnostics": list(blocked),
    }
    schema_diags = registry.schema_loader.validate(plan, "repair_plan.schema.json", "$.repair_plan")
    if schema_diags:
        plan["blocked_reasons"].extend(
            Diagnostic(CGNK_REPAIR_PLAN_INVALID, "error", d.path, d.message).as_dict() for d in schema_diags
        )
        plan["confidence"] = "none"
    return plan


def _repair_edge_type_mismatch(
    diagnostic: dict[str, Any],
    proposal: dict[str, Any],
    flow: dict[str, Any] | None,
    registry: ContractRegistry,
    suggested_edits: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
) -> None:
    if flow is None:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Target flow is unavailable")
        return
    source = diagnostic.get("source") or {}
    target = diagnostic.get("target") or {}
    target_type = _endpoint_type(flow, target, "input", registry)
    source_type = _endpoint_type(flow, source, "output", registry)
    source_alternatives = [
        ep for ep in _all_source_endpoints(flow, registry)
        if ep != source and _artifact_compatible(_endpoint_type(flow, ep, "output", registry), target_type, registry)
    ]
    target_alternatives = [
        ep for ep in _all_target_endpoints(flow, registry)
        if ep != target and _artifact_compatible(source_type, _endpoint_type(flow, ep, "input", registry), registry)
    ]
    candidates: list[dict[str, Any]] = []
    if len(source_alternatives) == 1:
        candidates.append({"op": "replace_connect_source", "from": source_alternatives[0], "to": target})
    if len(target_alternatives) == 1:
        candidates.append({"op": "replace_connect_target", "from": source, "to": target_alternatives[0]})
    if len(candidates) == 1:
        suggested_edits.append(candidates[0])
    elif len(candidates) > 1:
        _block(blocked, CGNK_REPAIR_AMBIGUOUS, diagnostic, "Multiple compatible edge repairs exist")
    else:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "No single compatible source or target alternative exists")


def _repair_unbound_input(
    diagnostic: dict[str, Any],
    flow: dict[str, Any] | None,
    registry: ContractRegistry,
    suggested_edits: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
) -> None:
    if flow is None:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Target flow is unavailable")
        return
    target = diagnostic.get("target") or _target_from_path(diagnostic.get("path", ""))
    target_type = _endpoint_type(flow, target, "input", registry)
    alternatives = [
        ep for ep in _all_source_endpoints(flow, registry)
        if _artifact_compatible(_endpoint_type(flow, ep, "output", registry), target_type, registry)
    ]
    if len(alternatives) == 1:
        suggested_edits.append({"op": "connect", "from": alternatives[0], "to": target})
    elif len(alternatives) > 1:
        _block(blocked, CGNK_REPAIR_AMBIGUOUS, diagnostic, "Multiple compatible producers exist for required input")
    else:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "No compatible producer exists for required input")


def _repair_policy_denial(
    diagnostic: dict[str, Any],
    proposal: dict[str, Any],
    flow: dict[str, Any] | None,
    registry: ContractRegistry,
    suggested_edits: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
) -> None:
    if flow is None:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Target flow is unavailable")
        return
    policy = registry.resolve_policy(flow.get("policy_ref", ""))
    if policy is None:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Policy is unavailable")
        return
    denied_ref = _denied_module_ref(diagnostic, proposal)
    denied_module = registry.resolve_module(denied_ref) if denied_ref else None
    if denied_module is None:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "Denied module could not be identified")
        return
    compatible = [
        ref for ref, module in registry.modules.items()
        if ref != denied_ref and _module_surface_compatible(denied_module, module) and _module_allowed(module, policy)
    ]
    if len(compatible) == 1:
        suggested_edits.append({"op": "replace_module_ref", "from": denied_ref, "to": compatible[0]})
    elif len(compatible) > 1:
        _block(blocked, CGNK_REPAIR_AMBIGUOUS, diagnostic, "Multiple lower-risk compatible modules exist")
    else:
        _block(blocked, CGNK_REPAIR_NO_SAFE_FIX, diagnostic, "No lower-risk compatible module exists")


def _denied_module_ref(diagnostic: dict[str, Any], proposal: dict[str, Any]) -> str | None:
    involved = diagnostic.get("involved_ref")
    if isinstance(involved, str) and involved.startswith("module."):
        return involved
    for edit in proposal.get("edits", []):
        replacement = edit.get("replacement") or edit.get("node") or {}
        module_ref = replacement.get("uses") or edit.get("module_ref")
        if isinstance(module_ref, str) and module_ref.startswith("module."):
            return module_ref
    return None


def _flow_with_proposed_nodes(flow: dict[str, Any] | None, proposal: dict[str, Any]) -> dict[str, Any] | None:
    if flow is None:
        return None
    preview = deepcopy(flow)
    for edit in proposal.get("edits", []):
        if edit.get("op") == "add_node":
            node = edit.get("node")
            if node and not any(row.get("id") == node.get("id") for row in preview.get("nodes", [])):
                preview.setdefault("nodes", []).append(deepcopy(node))
        elif edit.get("op") == "replace_node":
            for row in preview.get("nodes", []):
                if row.get("id") == edit.get("target_node"):
                    row.update(deepcopy(edit.get("replacement", {})))
    return preview


def _target_from_path(path: str) -> dict[str, str]:
    parts = path.split(".")
    if len(parts) >= 5 and parts[-3:] and "ports" in parts:
        try:
            node_index = parts.index("nodes")
            return {"node": parts[node_index + 1], "port": parts[-1]}
        except (ValueError, IndexError):
            pass
    return {}


def _all_source_endpoints(flow: dict[str, Any], registry: ContractRegistry) -> list[dict[str, str]]:
    endpoints = [{"flow_input": name} for name in flow.get("inputs", {})]
    for node in flow.get("nodes", []):
        module = registry.resolve_module(node.get("uses", ""))
        for port in (module or {}).get("ports", {}).get("output", {}):
            endpoints.append({"node": node["id"], "port": port})
    return endpoints


def _all_target_endpoints(flow: dict[str, Any], registry: ContractRegistry) -> list[dict[str, str]]:
    endpoints = [{"flow_output": name} for name in flow.get("outputs", {})]
    for node in flow.get("nodes", []):
        module = registry.resolve_module(node.get("uses", ""))
        for port in (module or {}).get("ports", {}).get("input", {}):
            endpoints.append({"node": node["id"], "port": port})
    return endpoints


def _endpoint_type(flow: dict[str, Any], endpoint: dict[str, Any], side: str, registry: ContractRegistry) -> str | None:
    if side == "output" and "flow_input" in endpoint:
        return flow.get("inputs", {}).get(endpoint["flow_input"])
    if side == "input" and "flow_output" in endpoint:
        return flow.get("outputs", {}).get(endpoint["flow_output"])
    node_id = endpoint.get("node")
    port = endpoint.get("port")
    node = next((row for row in flow.get("nodes", []) if row.get("id") == node_id), None)
    module = registry.resolve_module(node.get("uses", "")) if node else None
    return (module or {}).get("ports", {}).get(side, {}).get(port, {}).get("artifact_type")


def _artifact_compatible(src: str | None, tgt: str | None, registry: ContractRegistry) -> bool:
    if src is None or tgt is None:
        return False
    if src == tgt:
        return True
    artifact = registry.resolve_artifact(src) or {}
    return tgt in artifact.get("compatibility", {}).get("backward_compatible_with", [])


def _module_surface_compatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left.get("ports", {}) == right.get("ports", {})


def _module_allowed(module: dict[str, Any], policy: dict[str, Any]) -> bool:
    effects = module.get("effects", {})
    if effects.get("provider_call") and not policy.get("provider", {}).get("allowed", False):
        return False
    if effects.get("network") and not policy.get("network", {}).get("allowed", False):
        return False
    if int(effects.get("risk", 0)) > int(policy.get("risk", {}).get("max_risk", 0)):
        return False
    return True


def _block(blocked: list[dict[str, Any]], code: str, diagnostic: dict[str, Any], message: str) -> None:
    blocked.append(
        Diagnostic(
            code,
            "warning",
            diagnostic.get("path", "$.diagnostics"),
            message,
            actual=diagnostic.get("code"),
            involved_ref=diagnostic.get("involved_ref"),
        ).as_dict()
    )
