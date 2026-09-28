from __future__ import annotations

import fnmatch
import json
import pathlib
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from cgkn.artifacts.types import ArtifactTypeRegistry, ArtifactValidationError
from cgkn.component import ComponentSpec, ModuleComponentAdapter
from cgkn.specs import spec_directory


@dataclass(frozen=True)
class ArtifactGraph:
    flow_ref: str
    node_dependencies: dict[str, tuple[str, ...]]
    node_consumers: dict[str, tuple[str, ...]]
    node_outputs: dict[str, dict[str, str]]

    def descendants(self, node_id: str) -> list[str]:
        result: list[str] = []
        queue = deque(self.node_consumers.get(node_id, ()))
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            result.append(current)
            queue.extend(self.node_consumers.get(current, ()))
        return result


class ArtifactFlowCompiler:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root).resolve()
        self.registry = ArtifactTypeRegistry(self.root)
        self.modules = self._load("modules")
        self.flows = self._load("flows")
        self.policies = self._load("policies")

    def component(self, module_ref: str) -> ModuleComponentAdapter | None:
        module = self.modules.get(module_ref)
        return ModuleComponentAdapter(module) if module else None

    def _load(self, category: str) -> dict[str, dict[str, Any]]:
        result = {}
        for path in sorted(spec_directory(self.root, category).glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            result[f"{doc['id']}@{doc['version']}"] = doc
        return result

    def compile(self, flow_ref: str) -> dict[str, Any]:
        diagnostics: list[dict[str, Any]] = []
        flow = self.flows.get(flow_ref)
        if not flow:
            return self._result(flow_ref, diagnostics + [self._diag("CGKN_FLOW_NOT_FOUND", "flow", flow_ref)])
        policy = self.policies.get(flow.get("policy_ref", ""))
        if not policy:
            diagnostics.append(self._diag("CGKN_POLICY_NOT_FOUND", "policy_ref", flow.get("policy_ref")))
        artifact_driven = bool(flow.get("metadata", {}).get("artifact_driven"))
        nodes = {str(node["id"]): node for node in flow.get("nodes", [])}
        node_components: dict[str, ComponentSpec] = {}
        for name, artifact_type in {**flow.get("inputs", {}), **flow.get("outputs", {})}.items():
            self._check_artifact_type(artifact_type, f"flow.{name}", diagnostics)
        for node_id, node in nodes.items():
            component = self.component(str(node.get("uses", "")))
            if not component:
                diagnostics.append(self._diag("CGKN_MODULE_NOT_FOUND", f"nodes.{node_id}.uses", node.get("uses")))
                continue
            try:
                spec = component.spec
            except (KeyError, TypeError, ValueError) as exc:
                diagnostics.append(self._diag("CGKN_MODULE_CONTRACT_INVALID", f"nodes.{node_id}.uses", node.get("uses"), message=str(exc)))
                continue
            node_components[node_id] = spec
            implementation = spec.metadata.get("implementation", {})
            if artifact_driven and not implementation.get("kind"):
                diagnostics.append(self._diag("CGKN_RUNTIME_IMPLEMENTATION_MISSING", f"nodes.{node_id}.implementation", None))
            self._check_component(node_id, spec, policy, diagnostics)

        bound_inputs: dict[tuple[str, str], int] = defaultdict(int)
        graph_edges: list[tuple[str, str]] = []
        consumers: dict[str, list[str]] = defaultdict(list)
        dependencies: dict[str, list[str]] = defaultdict(list)
        flow_outputs: set[str] = set()
        for index, edge in enumerate(flow.get("edges", [])):
            source = edge.get("from", {})
            target = edge.get("to", {})
            source_type = self._endpoint_type(source, flow, node_components, "output", diagnostics, f"edges.{index}.from")
            target_type = self._endpoint_type(target, flow, node_components, "input", diagnostics, f"edges.{index}.to")
            if source_type and target_type and not self._compatible(source_type, target_type):
                diagnostics.append(self._diag("CGKN_EDGE_TYPE_MISMATCH", f"edges.{index}", source_type, expected=target_type))
            if "node" in target:
                bound_inputs[(target["node"], target["port"])] += 1
            if "node" in source and "node" in target:
                graph_edges.append((source["node"], target["node"]))
                dependencies[target["node"]].append(source["node"])
                consumers[source["node"]].append(target["node"])
            if "flow_output" in target:
                flow_outputs.add(target["flow_output"])
        for node_id, component in node_components.items():
            for port in component.input_ports:
                count = bound_inputs[(node_id, port.name)]
                if port.required and count == 0:
                    diagnostics.append(self._diag("CGKN_INPUT_UNBOUND", f"nodes.{node_id}.ports.input.{port.name}", None))
                if count > 1 and not port.multi:
                    diagnostics.append(self._diag("CGKN_INPUT_MULTI_PRODUCER", f"nodes.{node_id}.ports.input.{port.name}", count))
        for name in flow.get("outputs", {}):
            if name not in flow_outputs:
                diagnostics.append(self._diag("CGKN_OUTPUT_UNBOUND", f"outputs.{name}", None))
        order = self._topological_order(nodes, graph_edges)
        if order is None:
            diagnostics.append(self._diag("CGKN_GRAPH_CYCLE", "edges", None))
            order = []
        graph = ArtifactGraph(
            flow_ref=flow_ref,
            node_dependencies={key: tuple(sorted(set(dependencies.get(key, [])))) for key in nodes},
            node_consumers={key: tuple(sorted(set(consumers.get(key, [])))) for key in nodes},
            node_outputs={
                key: {port.name: port.artifact_type for port in component.output_ports}
                for key, component in node_components.items()
            },
        )
        result = self._result(flow_ref, diagnostics)
        if result["ok"]:
            result["compiled_bundle"] = {
                "kind": "CompiledContractBundle",
                "flow_ref": flow_ref,
                "policy_ref": flow.get("policy_ref", ""),
                "normalized_flow": flow,
                "topological_order": order,
                "node_component_refs": {key: component.ref for key, component in node_components.items()},
                "artifact_dependency_graph": {
                    "nodeDependencies": {key: list(value) for key, value in graph.node_dependencies.items()},
                    "nodeConsumers": {key: list(value) for key, value in graph.node_consumers.items()},
                    "nodeOutputs": graph.node_outputs,
                },
                "checks": {
                    "refs": "ok",
                    "types": "ok",
                    "producers": "ok",
                    "dag": "ok",
                    "policy": "ok",
                    "projections": "ok",
                    "implementations": "ok",
                },
            }
        result["graph"] = graph
        return result

    def _check_artifact_type(self, artifact_type: str, path: str, diagnostics: list[dict[str, Any]]) -> None:
        try:
            self.registry.content_schema(str(artifact_type))
        except ArtifactValidationError as exc:
            code = "CGKN_ARTIFACT_TYPE_NOT_FOUND" if str(artifact_type) not in self.registry.specs else "CGKN_OUTPUT_SCHEMA_NOT_FOUND"
            diagnostics.append(self._diag(code, path, artifact_type, message=str(exc)))

    def _check_component(self, node_id: str, component: ComponentSpec, policy: dict[str, Any] | None, diagnostics: list[dict[str, Any]]) -> None:
        for side, ports in (("input", component.input_ports), ("output", component.output_ports)):
            for port in ports:
                artifact_type = port.artifact_type
                self._check_artifact_type(artifact_type, f"nodes.{node_id}.{side}.{port.name}", diagnostics)
                projection = port.projection
                if projection and artifact_type in self.registry.specs:
                    try:
                        allowed = self.registry.projection_fields(artifact_type)
                    except ArtifactValidationError:
                        allowed = set()
                    for field in projection:
                        if field not in allowed:
                            diagnostics.append(self._diag("CGKN_PROJECTION_FIELD_INVALID", f"nodes.{node_id}.{side}.{port.name}.projection", field))
        context = component.metadata.get("context", {})
        input_ports = {port.name for port in component.input_ports}
        for key in ("requiredArtifactPorts", "optionalArtifactPorts"):
            for port in context.get(key, []):
                if port not in input_ports:
                    diagnostics.append(self._diag("CGKN_CONTEXT_PORT_INVALID", f"nodes.{node_id}.context.{key}", port))
        implementation = component.metadata.get("implementation", {})
        if implementation.get("kind") == "provider" and not component.effects.get("provider_call", False):
            diagnostics.append(self._diag("CGKN_PROVIDER_EFFECT_UNDECLARED", f"nodes.{node_id}.effects.provider_call", False, expected=True))
        if not policy:
            return
        effects = component.effects
        if effects.get("network") and not policy.get("network", {}).get("allowed", False):
            diagnostics.append(self._diag("CGKN_POLICY_EFFECT_DENIED", f"nodes.{node_id}.effects.network", True))
        if effects.get("provider_call") and not policy.get("provider", {}).get("allowed", False):
            diagnostics.append(self._diag("CGKN_POLICY_EFFECT_DENIED", f"nodes.{node_id}.effects.provider_call", True))
        if int(effects.get("risk", 0)) > int(policy.get("risk", {}).get("max_risk", 0)):
            diagnostics.append(self._diag("CGKN_POLICY_RISK_EXCEEDED", f"nodes.{node_id}.effects.risk", effects.get("risk")))
        for constraint_index, constraint in enumerate(policy.get("effect_constraints", [])):
            effect = constraint.get("effect")
            scope = constraint.get("scope")
            maximum = constraint.get("max")
            if effect not in {"network", "provider_call", "fs_read", "fs_write", "db_write"} or scope not in {"node", "phase", "turn", "run"} or not isinstance(maximum, int) or maximum < 0:
                diagnostics.append(self._diag("CGKN_EFFECT_CONSTRAINT_INVALID", f"policy.effect_constraints.{constraint_index}", constraint))
        for write_path in effects.get("fs_write", []):
            if any(fnmatch.fnmatch(write_path, denied) or fnmatch.fnmatch(denied, write_path) for denied in policy.get("fs", {}).get("denied_write", [])):
                diagnostics.append(self._diag("CGKN_POLICY_WRITE_DENIED", f"nodes.{node_id}.effects.fs_write", write_path))

    def _endpoint_type(self, endpoint, flow, components, side, diagnostics, path):
        if side == "output" and "flow_input" in endpoint:
            value = flow.get("inputs", {}).get(endpoint["flow_input"])
            if not value:
                diagnostics.append(self._diag("CGKN_FLOW_INPUT_NOT_FOUND", path, endpoint["flow_input"]))
            return value
        if side == "input" and "flow_output" in endpoint:
            value = flow.get("outputs", {}).get(endpoint["flow_output"])
            if not value:
                diagnostics.append(self._diag("CGKN_FLOW_OUTPUT_NOT_FOUND", path, endpoint["flow_output"]))
            return value
        if "node" not in endpoint:
            diagnostics.append(self._diag("CGKN_ENDPOINT_INVALID", path, endpoint))
            return None
        component = components.get(endpoint["node"])
        if not component:
            diagnostics.append(self._diag("CGKN_NODE_NOT_FOUND", path, endpoint["node"]))
            return None
        try:
            port = component.output_port(endpoint.get("port")) if side == "output" else component.input_port(endpoint.get("port"))
        except KeyError:
            diagnostics.append(self._diag("CGKN_PORT_NOT_FOUND", path, endpoint.get("port")))
            return None
        return port.artifact_type

    def _compatible(self, source: str, target: str) -> bool:
        if source == target:
            return True
        return target in self.registry.specs.get(source, {}).get("compatibility", {}).get("backward_compatible_with", [])

    @staticmethod
    def _topological_order(nodes: dict[str, Any], edges: list[tuple[str, str]]) -> list[str] | None:
        incoming = {key: 0 for key in nodes}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for source, target in edges:
            outgoing[source].append(target)
            incoming[target] += 1
        queue = deque(sorted(key for key, count in incoming.items() if count == 0))
        result: list[str] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for target in sorted(outgoing.get(node, [])):
                incoming[target] -= 1
                if incoming[target] == 0:
                    queue.append(target)
        return result if len(result) == len(nodes) else None

    @staticmethod
    def _diag(code: str, path: str, actual: Any, *, expected: Any = None, message: str = "") -> dict[str, Any]:
        result = {"code": code, "severity": "error", "path": path, "message": message or code.replace("CGKN_", "").replace("_", " ").title()}
        if actual is not None:
            result["actual"] = actual
        if expected is not None:
            result["expected"] = expected
        return result

    @staticmethod
    def _result(flow_ref: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "kind": "CompileResult",
            "ok": not any(item["severity"] == "error" for item in diagnostics),
            "flow_ref": flow_ref,
            "diagnostics": diagnostics,
            "compiled_bundle": None,
            "statistics": {"errors": sum(item["severity"] == "error" for item in diagnostics), "warnings": 0},
        }
