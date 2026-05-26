from __future__ import annotations

import fnmatch
from typing import Any

from .diagnostics import (
    CGNK_ARTIFACT_NOT_FOUND,
    CGNK_EDGE_TYPE_MISMATCH,
    CGNK_ENDPOINT_DIRECTION_INVALID,
    CGNK_GATE_PREDICATE_INVALID,
    CGNK_GRAPH_CYCLE,
    CGNK_INPUT_MULTI_PRODUCER,
    CGNK_INPUT_UNBOUND,
    CGNK_MODULE_NOT_FOUND,
    CGNK_NODE_NOT_FOUND,
    CGNK_OUTPUT_UNUSED,
    CGNK_POLICY_CAPABILITY_DENIED,
    CGNK_POLICY_EFFECT_DENIED,
    CGNK_POLICY_NOT_FOUND,
    CGNK_POLICY_RISK_EXCEEDED,
    CGNK_POLICY_WRITE_DENIED,
    CGNK_PORT_NOT_FOUND,
    Diagnostic,
)
from .registry import ContractRegistry


class SemanticValidator:
    def __init__(self, registry: ContractRegistry):
        self.registry = registry

    def validate_flow(self, flow: dict[str, Any]) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        policy_ref = flow.get("policy_ref")
        policy = self.registry.resolve_policy(policy_ref) if policy_ref else None
        if policy_ref and policy is None:
            diagnostics.append(Diagnostic(CGNK_POLICY_NOT_FOUND, "error", "$.policy_ref", "Policy ref not found", actual=policy_ref, involved_ref=policy_ref))

        for name, aref in {**flow.get("inputs", {}), **flow.get("outputs", {})}.items():
            if self.registry.resolve_artifact(aref) is None:
                diagnostics.append(Diagnostic(CGNK_ARTIFACT_NOT_FOUND, "error", f"$.{name}", "Artifact ref not found", actual=aref, involved_ref=aref))

        node_map: dict[str, dict[str, Any]] = {}
        for i, node in enumerate(flow.get("nodes", [])):
            module_ref = node.get("uses")
            module = self.registry.resolve_module(module_ref)
            if module is None:
                diagnostics.append(
                    Diagnostic(
                        CGNK_MODULE_NOT_FOUND,
                        "error",
                        f"$.nodes[{i}].uses",
                        "Module ref not found",
                        actual=module_ref,
                        involved_ref=module_ref,
                        repair_hints=[{"op": "replace_node", "target_node": node.get("id")}],
                    )
                )
                continue
            node_map[node["id"]] = {"node": node, "module": module}
            self._validate_module_artifacts(node["id"], module, diagnostics)
            self._validate_policy(node["id"], module, policy, diagnostics)

        bound_inputs: dict[tuple[str, str], int] = {}
        graph_edges: list[tuple[str, str]] = []
        output_sources: set[str] = set()
        for i, edge in enumerate(flow.get("edges", [])):
            src_type = self._source_type(edge.get("from", {}), flow, node_map, f"$.edges[{i}].from", diagnostics)
            tgt_type = self._target_type(edge.get("to", {}), flow, node_map, f"$.edges[{i}].to", diagnostics)
            if src_type and tgt_type and not self._artifact_compatible(src_type, tgt_type):
                diagnostics.append(
                    Diagnostic(
                        CGNK_EDGE_TYPE_MISMATCH,
                        "error",
                        f"$.edges[{i}]",
                        "Edge artifact type mismatch",
                        expected=tgt_type,
                        actual=src_type,
                        source=edge.get("from", {}),
                        target=edge.get("to", {}),
                        repair_hints=[{"op": "disconnect", "from": edge.get("from", {}), "to": edge.get("to", {})}],
                    )
                )
            src = edge.get("from", {})
            tgt = edge.get("to", {})
            if "node" in tgt:
                key = (tgt["node"], tgt["port"])
                bound_inputs[key] = bound_inputs.get(key, 0) + 1
            if "node" in src and "node" in tgt:
                graph_edges.append((src["node"], tgt["node"]))
            if "flow_output" in tgt:
                output_sources.add(tgt["flow_output"])

        for node_id, row in node_map.items():
            module = row["module"]
            for port, spec in module.get("ports", {}).get("input", {}).items():
                count = bound_inputs.get((node_id, port), 0)
                if spec.get("required", False) and count == 0:
                    diagnostics.append(
                        Diagnostic(
                            CGNK_INPUT_UNBOUND,
                            "error",
                            f"$.nodes.{node_id}.ports.input.{port}",
                            "Required input port is not bound",
                            expected="bound input edge",
                            actual="unbound",
                            target={"node": node_id, "port": port},
                        )
                    )
                if count > 1 and not spec.get("multi", False):
                    diagnostics.append(
                        Diagnostic(
                            CGNK_INPUT_MULTI_PRODUCER,
                            "error",
                            f"$.nodes.{node_id}.ports.input.{port}",
                            "Input port has multiple producers",
                            expected="single producer or multi=true",
                            actual=count,
                            target={"node": node_id, "port": port},
                            repair_hints=[{"op": "disconnect_extra_producer", "target": {"node": node_id, "port": port}}],
                        )
                    )

        for output_name in flow.get("outputs", {}):
            if output_name not in output_sources:
                diagnostics.append(Diagnostic(CGNK_OUTPUT_UNUSED, "error", f"$.outputs.{output_name}", "Flow output has no upstream source", target={"flow_output": output_name}))

        if self._has_cycle(graph_edges):
            diagnostics.append(Diagnostic(CGNK_GRAPH_CYCLE, "error", "$.edges", "Flow node graph contains a cycle", repair_hints=[{"op": "disconnect_cycle_edge"}]))
        self._validate_gates(flow, node_map, diagnostics)
        return diagnostics

    def _validate_module_artifacts(self, node_id: str, module: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
        for side in ("input", "output"):
            for port, spec in module.get("ports", {}).get(side, {}).items():
                aref = spec.get("artifact_type")
                if self.registry.resolve_artifact(aref) is None:
                    diagnostics.append(Diagnostic(CGNK_ARTIFACT_NOT_FOUND, "error", f"$.nodes.{node_id}.{side}.{port}", "Artifact ref not found", actual=aref, involved_ref=aref))

    def _source_type(self, ep: dict[str, Any], flow: dict[str, Any], node_map: dict[str, dict[str, Any]], path: str, diagnostics: list[Diagnostic]) -> str | None:
        if "flow_output" in ep:
            diagnostics.append(Diagnostic(CGNK_ENDPOINT_DIRECTION_INVALID, "error", path, "Source endpoint cannot be flow_output", actual=ep))
            return None
        if "flow_input" in ep:
            aref = flow.get("inputs", {}).get(ep["flow_input"])
            if not aref:
                diagnostics.append(Diagnostic(CGNK_ARTIFACT_NOT_FOUND, "error", path, "Flow input not found", actual=ep["flow_input"], source=ep))
            return aref
        return self._node_port_type(ep, node_map, "output", path, diagnostics)

    def _target_type(self, ep: dict[str, Any], flow: dict[str, Any], node_map: dict[str, dict[str, Any]], path: str, diagnostics: list[Diagnostic]) -> str | None:
        if "flow_input" in ep:
            diagnostics.append(Diagnostic(CGNK_ENDPOINT_DIRECTION_INVALID, "error", path, "Target endpoint cannot be flow_input", actual=ep))
            return None
        if "flow_output" in ep:
            aref = flow.get("outputs", {}).get(ep["flow_output"])
            if not aref:
                diagnostics.append(Diagnostic(CGNK_ARTIFACT_NOT_FOUND, "error", path, "Flow output not found", actual=ep["flow_output"], target=ep))
            return aref
        return self._node_port_type(ep, node_map, "input", path, diagnostics)

    def _node_port_type(self, ep: dict[str, Any], node_map: dict[str, dict[str, Any]], side: str, path: str, diagnostics: list[Diagnostic]) -> str | None:
        node_id = ep.get("node")
        row = node_map.get(node_id)
        if row is None:
            diagnostics.append(Diagnostic(CGNK_NODE_NOT_FOUND, "error", path, "Node not found", actual=node_id, involved_ref=node_id))
            return None
        port = ep.get("port")
        spec = row["module"].get("ports", {}).get(side, {}).get(port)
        if spec is None:
            diagnostics.append(Diagnostic(CGNK_PORT_NOT_FOUND, "error", path, f"{side} port not found", expected=f"{side} port", actual=port, involved_ref=row["node"].get("uses")))
            return None
        return spec.get("artifact_type")

    def _artifact_compatible(self, src: str, tgt: str) -> bool:
        if src == tgt:
            return True
        source = self.registry.resolve_artifact(src) or {}
        return tgt in source.get("compatibility", {}).get("backward_compatible_with", [])

    def _validate_policy(self, node_id: str, module: dict[str, Any], policy: dict[str, Any] | None, diagnostics: list[Diagnostic]) -> None:
        if policy is None:
            return
        effects = module.get("effects", {})
        if effects.get("network") and not policy.get("network", {}).get("allowed", False):
            diagnostics.append(Diagnostic(CGNK_POLICY_EFFECT_DENIED, "error", f"$.nodes.{node_id}.effects.network", "Network effect denied by policy", expected=False, actual=True, involved_ref=policy.get("id") + "@" + policy.get("version")))
        if effects.get("provider_call") and not policy.get("provider", {}).get("allowed", False):
            diagnostics.append(Diagnostic(CGNK_POLICY_EFFECT_DENIED, "error", f"$.nodes.{node_id}.effects.provider_call", "Provider effect denied by policy", expected=False, actual=True, involved_ref=policy.get("id") + "@" + policy.get("version")))
        max_risk = int(policy.get("risk", {}).get("max_risk", 0))
        if int(effects.get("risk", 0)) > max_risk:
            diagnostics.append(Diagnostic(CGNK_POLICY_RISK_EXCEEDED, "error", f"$.nodes.{node_id}.effects.risk", "Risk exceeds policy", expected=max_risk, actual=effects.get("risk"), involved_ref=policy.get("id") + "@" + policy.get("version")))
        for path in effects.get("fs_write", []):
            for denied in policy.get("fs", {}).get("denied_write", []):
                if fnmatch.fnmatch(path, denied) or fnmatch.fnmatch(denied, path):
                    diagnostics.append(Diagnostic(CGNK_POLICY_WRITE_DENIED, "error", f"$.nodes.{node_id}.effects.fs_write", "Write path denied by policy", expected=f"not {denied}", actual=path, involved_ref=policy.get("id") + "@" + policy.get("version")))
        for cap in module.get("requires", {}).get("capabilities", []):
            cap_id = cap.get("id")
            if cap_id == "cap.provider.call" and not policy.get("provider", {}).get("allowed", False):
                diagnostics.append(Diagnostic(CGNK_POLICY_CAPABILITY_DENIED, "error", f"$.nodes.{node_id}.requires.capabilities", "Provider capability denied by policy", expected="provider allowed", actual=cap_id, involved_ref=policy.get("id") + "@" + policy.get("version")))

    def _validate_gates(self, flow: dict[str, Any], node_map: dict[str, dict[str, Any]], diagnostics: list[Diagnostic]) -> None:
        def walk(pred: dict[str, Any], path: str) -> None:
            if not isinstance(pred, dict) or not pred:
                diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Gate predicate must be a structured predicate"))
                return
            keys = set(pred)
            if "all" in pred:
                for i, child in enumerate(pred["all"]):
                    walk(child, f"{path}.all[{i}]")
            elif "any" in pred:
                for i, child in enumerate(pred["any"]):
                    walk(child, f"{path}.any[{i}]")
            elif "not" in pred:
                walk(pred["not"], f"{path}.not")
            elif "node_passed" in pred:
                if pred["node_passed"] not in node_map:
                    diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate node ref not found", expected="known node id", actual=pred["node_passed"], involved_ref=pred["node_passed"]))
            elif "artifact_exists" in pred:
                endpoint = pred["artifact_exists"]
                if "flow_input" in endpoint and endpoint["flow_input"] not in flow.get("inputs", {}):
                    diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate flow input ref not found", expected="known flow input", actual=endpoint["flow_input"]))
                elif "flow_output" in endpoint and endpoint["flow_output"] not in flow.get("outputs", {}):
                    diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate flow output ref not found", expected="known flow output", actual=endpoint["flow_output"]))
                elif "node" in endpoint:
                    node = node_map.get(endpoint.get("node"))
                    if node is None:
                        diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate node ref not found", expected="known node id", actual=endpoint.get("node")))
                    else:
                        port = endpoint.get("port")
                        ports = node["module"].get("ports", {}).get("input", {}) | node["module"].get("ports", {}).get("output", {})
                        if port not in ports:
                            diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate port ref not found", expected="known port id", actual=port))
            elif "flow_input_bound" in pred:
                if pred["flow_input_bound"] not in flow.get("inputs", {}):
                    diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate flow input ref not found", expected="known flow input", actual=pred["flow_input_bound"]))
            elif "flow_output_bound" in pred:
                if pred["flow_output_bound"] not in flow.get("outputs", {}):
                    diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Predicate flow output ref not found", expected="known flow output", actual=pred["flow_output_bound"]))
            elif "policy_allows" in pred:
                return
            else:
                diagnostics.append(Diagnostic(CGNK_GATE_PREDICATE_INVALID, "error", path, "Unknown predicate shape", actual=pred))

        for i, gate in enumerate(flow.get("gates", [])):
            walk(gate.get("require", {}), f"$.gates[{i}].require")

    def _has_cycle(self, edges: list[tuple[str, str]]) -> bool:
        graph: dict[str, list[str]] = {}
        for src, tgt in edges:
            graph.setdefault(src, []).append(tgt)
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            for nxt in graph.get(node, []):
                if dfs(nxt):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(dfs(node) for node in graph)
