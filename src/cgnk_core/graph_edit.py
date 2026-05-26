from __future__ import annotations

from copy import deepcopy
from typing import Any

from .compiler import compile_flow
from .diagnostics import (
    CGNK_MODULE_NOT_FOUND,
    CGNK_POLICY_EFFECT_DENIED,
    CGNK_PROPOSAL_INVALID,
    Diagnostic,
)
from .registry import ContractRegistry


def apply_graph_edit_proposal(proposal: dict[str, Any], registry: ContractRegistry, dry_run: bool = True) -> dict[str, Any]:
    diagnostics = registry.schema_loader.validate(proposal, path="$.proposal")
    if diagnostics:
        return _preview(False, proposal, None, diagnostics)
    flow = registry.resolve_flow(proposal["target_flow"])
    if flow is None:
        return _preview(False, proposal, None, [Diagnostic(CGNK_PROPOSAL_INVALID, "error", "$.target_flow", "Target flow not found", actual=proposal["target_flow"])])
    preview = deepcopy(flow)
    diagnostics = []
    for index, edit in enumerate(proposal.get("edits", [])):
        diagnostics.extend(_apply_edit(preview, edit, registry, f"$.edits[{index}]"))
    if diagnostics:
        return _preview(False, proposal, preview, diagnostics)
    result = compile_flow(proposal["target_flow"], registry, flow_doc=preview)
    diagnostics = [_diagnostic_from_dict(d) for d in result["diagnostics"]]
    accepted = result["ok"]
    return {
        "kind": "ProposalPreviewResult",
        "ok": accepted,
        "accepted": accepted,
        "dry_run": dry_run,
        "proposal_ref": f"{proposal['id']}@1",
        "target_flow": proposal["target_flow"],
        "diagnostics": [d.as_dict() for d in diagnostics],
        "preview_flow": preview if accepted else None,
        "compile_result": result,
    }


def _preview(ok: bool, proposal: dict[str, Any], preview: dict[str, Any] | None, diagnostics: list[Diagnostic]) -> dict[str, Any]:
    return {
        "kind": "ProposalPreviewResult",
        "ok": ok,
        "accepted": ok,
        "dry_run": True,
        "proposal_ref": proposal.get("id", "proposal.invalid") + "@1",
        "target_flow": proposal.get("target_flow"),
        "diagnostics": [d.as_dict() for d in diagnostics],
        "preview_flow": preview if ok else None,
        "compile_result": None,
    }


def _apply_edit(flow: dict[str, Any], edit: dict[str, Any], registry: ContractRegistry, path: str) -> list[Diagnostic]:
    op = edit.get("op")
    if op == "add_node":
        module_ref = edit["node"]["uses"]
        if registry.resolve_module(module_ref) is None:
            return [Diagnostic(CGNK_MODULE_NOT_FOUND, "error", f"{path}.node.uses", "Module ref not found", actual=module_ref)]
        if any(n["id"] == edit["node"]["id"] for n in flow.get("nodes", [])):
            return [Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.node.id", "Node id already exists", actual=edit["node"]["id"])]
        flow.setdefault("nodes", []).append(deepcopy(edit["node"]))
        return []
    if op == "remove_node":
        flow["nodes"] = [n for n in flow.get("nodes", []) if n["id"] != edit["target_node"]]
        flow["edges"] = [e for e in flow.get("edges", []) if e.get("from", {}).get("node") != edit["target_node"] and e.get("to", {}).get("node") != edit["target_node"]]
        return []
    if op == "replace_node":
        return _replace_node(flow, edit, registry, path)
    if op == "connect":
        edge = {"from": deepcopy(edit["from"]), "to": deepcopy(edit["to"])}
        if edge not in flow.setdefault("edges", []):
            flow["edges"].append(edge)
        return []
    if op == "disconnect":
        edge = {"from": edit["from"], "to": edit["to"]}
        if edge not in flow.get("edges", []):
            return [Diagnostic(CGNK_PROPOSAL_INVALID, "error", path, "Edge to disconnect does not exist")]
        flow["edges"] = [e for e in flow.get("edges", []) if e != edge]
        return []
    if op == "split_edge":
        return _split_edge(flow, edit, registry, path)
    if op == "add_gate":
        flow.setdefault("gates", []).append(deepcopy(edit["gate"]))
        return []
    if op == "remove_gate":
        flow["gates"] = [g for g in flow.get("gates", []) if g.get("id") != edit["gate_id"]]
        return []
    if op == "change_policy_ref":
        flow["policy_ref"] = edit["policy_ref"]
        return []
    if op == "upgrade_module_version":
        replacement = {"id": edit["target_node"], "uses": edit["module_ref"]}
        return _replace_node(flow, {"target_node": edit["target_node"], "replacement": replacement}, registry, path)
    return [Diagnostic(CGNK_PROPOSAL_INVALID, "error", path, "Unsupported graph edit op", actual=op)]


def _split_edge(flow: dict[str, Any], edit: dict[str, Any], registry: ContractRegistry, path: str) -> list[Diagnostic]:
    edge = edit["edge"]
    inserted = edit["inserted_node"]
    diagnostics: list[Diagnostic] = []
    if edge not in flow.get("edges", []):
        return [Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.edge", "Edge to split does not exist", expected="existing edge", actual=edge)]
    module = registry.resolve_module(inserted["uses"])
    if module is None:
        return [Diagnostic(CGNK_MODULE_NOT_FOUND, "error", f"{path}.inserted_node.uses", "Inserted module not found", actual=inserted["uses"], involved_ref=inserted["uses"])]
    if any(n["id"] == inserted["id"] for n in flow.get("nodes", [])):
        return [Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.inserted_node.id", "Inserted node id already exists", actual=inserted["id"])]

    src_type = _endpoint_type(flow, edge["from"], "output", registry)
    tgt_type = _endpoint_type(flow, edge["to"], "input", registry)
    input_port = _first_compatible_port(module, "input", src_type, registry)
    output_port = _first_compatible_port(module, "output", tgt_type, registry)
    if src_type is None or input_port is None:
        diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.inserted_node", "Inserted module has no compatible input for split edge", expected=src_type, actual=inserted["uses"], involved_ref=inserted["uses"]))
    if tgt_type is None or output_port is None:
        diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.inserted_node", "Inserted module has no compatible output for split edge", expected=tgt_type, actual=inserted["uses"], involved_ref=inserted["uses"]))
    diagnostics.extend(_check_module_allowed_by_policy(flow, module, registry, path))
    if diagnostics:
        return diagnostics
    flow["edges"] = [e for e in flow.get("edges", []) if e != edge]
    flow.setdefault("nodes", []).append(deepcopy(inserted))
    flow["edges"].append({"from": deepcopy(edge["from"]), "to": {"node": inserted["id"], "port": input_port}})
    flow["edges"].append({"from": {"node": inserted["id"], "port": output_port}, "to": deepcopy(edge["to"])})
    return []


def _replace_node(flow: dict[str, Any], edit: dict[str, Any], registry: ContractRegistry, path: str) -> list[Diagnostic]:
    old_node = next((n for n in flow.get("nodes", []) if n["id"] == edit["target_node"]), None)
    if old_node is None:
        return [Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.target_node", "Target node not found", actual=edit["target_node"])]
    old_module = registry.resolve_module(old_node["uses"])
    new_module = registry.resolve_module(edit["replacement"]["uses"])
    if new_module is None:
        return [Diagnostic(CGNK_MODULE_NOT_FOUND, "error", f"{path}.replacement.uses", "Replacement module not found", actual=edit["replacement"]["uses"])]
    diagnostics: list[Diagnostic] = []
    if old_module:
        old_inputs = old_module.get("ports", {}).get("input", {})
        new_inputs = new_module.get("ports", {}).get("input", {})
        incoming_edges = [e for e in flow.get("edges", []) if e.get("to", {}).get("node") == old_node["id"]]
        bound_inputs = {e["to"]["port"] for e in incoming_edges}
        for port, spec in new_inputs.items():
            if spec.get("required", False) and port not in old_inputs and port not in bound_inputs:
                diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.replacement.ports.input.{port}", "Replacement adds unbound required input", expected="bound input", actual=port, involved_ref=edit["replacement"]["uses"]))
        for edge in incoming_edges:
            port = edge["to"]["port"]
            if port in old_inputs and port in new_inputs and not _artifact_compatible(_endpoint_type(flow, edge["from"], "output", registry), new_inputs[port].get("artifact_type"), registry):
                diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.replacement.ports.input.{port}", "Replacement input artifact type is incompatible", expected=old_inputs[port].get("artifact_type"), actual=new_inputs[port].get("artifact_type"), source=edge["from"], target=edge["to"], involved_ref=edit["replacement"]["uses"]))
        new_outputs = new_module.get("ports", {}).get("output", {})
        outgoing_edges = [e for e in flow.get("edges", []) if e.get("from", {}).get("node") == old_node["id"]]
        downstream_outputs = {e["from"]["port"] for e in outgoing_edges}
        for port in downstream_outputs:
            if port not in new_outputs:
                diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.replacement.ports.output.{port}", "Replacement removes downstream-used output", expected="output port preserved", actual=port, involved_ref=edit["replacement"]["uses"]))
        for edge in outgoing_edges:
            port = edge["from"]["port"]
            if port in new_outputs and not _artifact_compatible(new_outputs[port].get("artifact_type"), _endpoint_type(flow, edge["to"], "input", registry), registry):
                diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.replacement.ports.output.{port}", "Replacement output artifact type is incompatible", expected=_endpoint_type(flow, edge["to"], "input", registry), actual=new_outputs[port].get("artifact_type"), source=edge["from"], target=edge["to"], involved_ref=edit["replacement"]["uses"]))
        old_eff = old_module.get("effects", {})
        new_eff = new_module.get("effects", {})
        if (not old_eff.get("provider_call") and new_eff.get("provider_call")) or (not old_eff.get("network") and new_eff.get("network")):
            diagnostics.append(Diagnostic(CGNK_POLICY_EFFECT_DENIED, "error", f"{path}.replacement.effects", "Replacement expands provider/network effects", expected=old_eff, actual=new_eff, involved_ref=edit["replacement"]["uses"]))
        if int(new_eff.get("risk", 0)) > int(old_eff.get("risk", 0)):
            diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.replacement.effects.risk", "Replacement increases risk", expected=old_eff.get("risk", 0), actual=new_eff.get("risk", 0), involved_ref=edit["replacement"]["uses"]))
        diagnostics.extend(_check_module_allowed_by_policy(flow, new_module, registry, path))
        replacement_id = edit["replacement"].get("id", old_node["id"])
        if replacement_id != old_node["id"] and _gate_references_node(flow, old_node["id"]):
            diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.replacement.id", "Replacement changes node id referenced by gates", expected=old_node["id"], actual=replacement_id, involved_ref=old_node["id"]))
    if diagnostics:
        return diagnostics
    for node in flow.get("nodes", []):
        if node["id"] == old_node["id"]:
            node["uses"] = edit["replacement"]["uses"]
            node["id"] = edit["replacement"].get("id", old_node["id"])
            break
    return []


def _diagnostic_from_dict(row: dict[str, Any]) -> Diagnostic:
    return Diagnostic(
        row["code"],
        row["severity"],
        row["path"],
        row["message"],
        row.get("expected"),
        row.get("actual"),
        row.get("involved_ref"),
        row.get("source"),
        row.get("target"),
        row.get("repair_hints"),
    )


def _check_module_allowed_by_policy(flow: dict[str, Any], module: dict[str, Any], registry: ContractRegistry, path: str) -> list[Diagnostic]:
    policy = registry.resolve_policy(flow.get("policy_ref", ""))
    if policy is None:
        return []
    diagnostics: list[Diagnostic] = []
    effects = module.get("effects", {})
    policy_ref = f"{policy['id']}@{policy['version']}"
    module_ref = f"{module['id']}@{module['version']}"
    if effects.get("network") and not policy.get("network", {}).get("allowed", False):
        diagnostics.append(Diagnostic(CGNK_POLICY_EFFECT_DENIED, "error", f"{path}.effects.network", "Module network effect violates policy", expected=False, actual=True, involved_ref=policy_ref))
    if effects.get("provider_call") and not policy.get("provider", {}).get("allowed", False):
        diagnostics.append(Diagnostic(CGNK_POLICY_EFFECT_DENIED, "error", f"{path}.effects.provider_call", "Module provider effect violates policy", expected=False, actual=True, involved_ref=policy_ref))
    if int(effects.get("risk", 0)) > int(policy.get("risk", {}).get("max_risk", 0)):
        diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.effects.risk", "Module risk violates policy", expected=policy.get("risk", {}).get("max_risk", 0), actual=effects.get("risk", 0), involved_ref=module_ref))
    for cap in module.get("requires", {}).get("capabilities", []):
        if cap.get("id") == "cap.provider.call" and not policy.get("provider", {}).get("allowed", False):
            diagnostics.append(Diagnostic(CGNK_PROPOSAL_INVALID, "error", f"{path}.requires.capabilities", "Module capability violates policy", expected="provider allowed", actual=cap.get("id"), involved_ref=module_ref))
    return diagnostics


def _endpoint_type(flow: dict[str, Any], endpoint: dict[str, Any], side: str, registry: ContractRegistry) -> str | None:
    if side == "output" and "flow_input" in endpoint:
        return flow.get("inputs", {}).get(endpoint["flow_input"])
    if side == "input" and "flow_output" in endpoint:
        return flow.get("outputs", {}).get(endpoint["flow_output"])
    if "node" not in endpoint:
        return None
    node = next((n for n in flow.get("nodes", []) if n["id"] == endpoint["node"]), None)
    if node is None:
        return None
    module = registry.resolve_module(node["uses"])
    if module is None:
        return None
    spec = module.get("ports", {}).get(side, {}).get(endpoint.get("port"))
    return spec.get("artifact_type") if spec else None


def _artifact_compatible(src: str | None, tgt: str | None, registry: ContractRegistry) -> bool:
    if src is None or tgt is None:
        return False
    if src == tgt:
        return True
    artifact = registry.resolve_artifact(src) or {}
    return tgt in artifact.get("compatibility", {}).get("backward_compatible_with", [])


def _first_compatible_port(module: dict[str, Any], side: str, artifact_type: str | None, registry: ContractRegistry) -> str | None:
    for port, spec in module.get("ports", {}).get(side, {}).items():
        candidate = spec.get("artifact_type")
        if side == "input" and _artifact_compatible(artifact_type, candidate, registry):
            return port
        if side == "output" and _artifact_compatible(candidate, artifact_type, registry):
            return port
    return None


def _gate_references_node(flow: dict[str, Any], node_id: str) -> bool:
    def walk(pred: dict[str, Any]) -> bool:
        if not isinstance(pred, dict):
            return False
        if pred.get("node_passed") == node_id:
            return True
        if "artifact_exists" in pred and pred["artifact_exists"].get("node") == node_id:
            return True
        return any(walk(child) for key in ("all", "any") for child in pred.get(key, [])) or ("not" in pred and walk(pred["not"]))

    return any(walk(gate.get("require", {})) for gate in flow.get("gates", []))
