from __future__ import annotations

import fnmatch
import json
import pathlib
import warnings
from dataclasses import dataclass
from typing import Any


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ref_of(doc: dict[str, Any]) -> str:
    return f"{doc['id']}@{doc['version']}"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    path: str
    message: str
    expected: Any = None
    actual: Any = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "code": self.code,
            "severity": self.severity,
            "path": self.path,
            "message": self.message,
        }
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        return out


class ContractIndex:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.artifacts = {ref_of(d): d for d in self._load_dir("examples/artifacts")}
        self.modules = {ref_of(d): d for d in self._load_dir("examples/modules")}
        self.policies = {ref_of(d): d for d in self._load_dir("examples/policies")}
        self.flows = {ref_of(d): d for d in self._load_dir("examples/flows")}

    def _load_dir(self, rel: str) -> list[dict[str, Any]]:
        return [load_json(p) for p in sorted((self.root / rel).glob("*.json"))]


class ReferenceCompiler:
    """Dependency-light Phase 0 semantic checker for bundled contracts."""

    def __init__(self, index: ContractIndex):
        self.idx = index

    def compile(self, flow_ref: str) -> dict[str, Any]:
        diags: list[Diagnostic] = []
        flow = self.idx.flows.get(flow_ref)
        if flow is None:
            diags.append(
                Diagnostic(
                    "CGNK_FLOW_NOT_FOUND",
                    "error",
                    "flow",
                    "Flow ref not found",
                    actual=flow_ref,
                )
            )
            return self._result(flow_ref, None, diags)

        policy = self.idx.policies.get(flow.get("policy_ref", ""))
        if policy is None:
            diags.append(
                Diagnostic(
                    "CGNK_POLICY_NOT_FOUND",
                    "error",
                    "policy_ref",
                    "Policy ref not found",
                    actual=flow.get("policy_ref"),
                )
            )

        for name, aref in {**flow.get("inputs", {}), **flow.get("outputs", {})}.items():
            if aref not in self.idx.artifacts:
                diags.append(
                    Diagnostic(
                        "CGNK_ARTIFACT_TYPE_NOT_FOUND",
                        "error",
                        f"flow.{name}",
                        "Artifact ref not found",
                        actual=aref,
                    )
                )

        node_map: dict[str, dict[str, Any]] = {}
        for node in flow.get("nodes", []):
            uses = node.get("uses")
            mod = self.idx.modules.get(uses)
            if mod is None:
                diags.append(
                    Diagnostic(
                        "CGNK_MODULE_NOT_FOUND",
                        "error",
                        f"nodes.{node.get('id')}.uses",
                        "Module ref not found",
                        actual=uses,
                    )
                )
            else:
                node_map[node["id"]] = {"node": node, "module": mod}
                self._check_policy(node["id"], mod, policy, diags)
                for side in ("input", "output"):
                    for port, spec in mod.get("ports", {}).get(side, {}).items():
                        aref = spec.get("artifact_type")
                        if aref not in self.idx.artifacts:
                            diags.append(
                                Diagnostic(
                                    "CGNK_ARTIFACT_TYPE_NOT_FOUND",
                                    "error",
                                    f"module.{mod['id']}.{side}.{port}",
                                    "Artifact ref not found",
                                    actual=aref,
                                )
                            )

        bound_inputs: dict[tuple[str, str], int] = {}
        output_sources: set[str] = set()
        graph_edges: list[tuple[str, str]] = []
        for i, edge in enumerate(flow.get("edges", [])):
            src_type = self._endpoint_type(edge.get("from", {}), flow, node_map, "output", diags, f"edges.{i}.from")
            tgt_type = self._endpoint_type(edge.get("to", {}), flow, node_map, "input", diags, f"edges.{i}.to")
            if src_type and tgt_type and not self._artifact_compatible(src_type, tgt_type):
                diags.append(
                    Diagnostic(
                        "CGNK_EDGE_TYPE_MISMATCH",
                        "error",
                        f"edges.{i}",
                        "Edge artifact type mismatch",
                        expected=tgt_type,
                        actual=src_type,
                    )
                )
            to = edge.get("to", {})
            if "node" in to:
                key = (to["node"], to["port"])
                bound_inputs[key] = bound_inputs.get(key, 0) + 1
            if "node" in edge.get("from", {}) and "node" in to:
                graph_edges.append((edge["from"]["node"], to["node"]))
            if "flow_output" in to:
                output_sources.add(to["flow_output"])

        for nid, row in node_map.items():
            mod = row["module"]
            for port, spec in mod.get("ports", {}).get("input", {}).items():
                if spec.get("required", False) and (nid, port) not in bound_inputs:
                    diags.append(
                        Diagnostic(
                            "CGNK_INPUT_UNBOUND",
                            "error",
                            f"nodes.{nid}.ports.input.{port}",
                            "Required input port is not bound",
                        )
                    )
                if bound_inputs.get((nid, port), 0) > 1 and not spec.get("multi", False):
                    diags.append(
                        Diagnostic(
                            "CGNK_INPUT_MULTI_PRODUCER",
                            "error",
                            f"nodes.{nid}.ports.input.{port}",
                            "Input port has multiple producers",
                        )
                    )

        for out_name in flow.get("outputs", {}):
            if out_name not in output_sources:
                diags.append(Diagnostic("CGNK_OUTPUT_UNBOUND", "error", f"outputs.{out_name}", "Flow output is not bound"))

        if self._has_cycle(graph_edges):
            diags.append(Diagnostic("CGNK_GRAPH_CYCLE", "error", "edges", "Flow node graph contains a cycle"))

        self._check_gates(flow, node_map, diags)
        return self._result(flow_ref, flow, diags)

    def _endpoint_type(self, ep: dict[str, Any], flow: dict[str, Any], node_map: dict[str, dict[str, Any]], side: str, diags: list[Diagnostic], path: str) -> str | None:
        if side == "output" and "flow_input" in ep:
            aref = flow.get("inputs", {}).get(ep["flow_input"])
            if not aref:
                diags.append(Diagnostic("CGNK_FLOW_INPUT_NOT_FOUND", "error", path, "Flow input not found", actual=ep.get("flow_input")))
            return aref
        if side == "input" and "flow_output" in ep:
            aref = flow.get("outputs", {}).get(ep["flow_output"])
            if not aref:
                diags.append(Diagnostic("CGNK_FLOW_OUTPUT_NOT_FOUND", "error", path, "Flow output not found", actual=ep.get("flow_output")))
            return aref
        if "node" in ep:
            row = node_map.get(ep.get("node"))
            if row is None:
                diags.append(Diagnostic("CGNK_NODE_NOT_FOUND", "error", path, "Node not found", actual=ep.get("node")))
                return None
            port_spec = row["module"].get("ports", {}).get(side, {}).get(ep.get("port"))
            if port_spec is None:
                diags.append(Diagnostic("CGNK_PORT_NOT_FOUND", "error", path, f"{side} port not found", actual=ep.get("port")))
                return None
            return port_spec.get("artifact_type")
        diags.append(Diagnostic("CGNK_ENDPOINT_INVALID", "error", path, "Endpoint has invalid direction"))
        return None

    def _artifact_compatible(self, src: str, tgt: str) -> bool:
        if src == tgt:
            return True
        sdoc = self.idx.artifacts.get(src, {})
        return tgt in sdoc.get("compatibility", {}).get("backward_compatible_with", [])

    def _check_policy(self, node_id: str, mod: dict[str, Any], policy: dict[str, Any] | None, diags: list[Diagnostic]) -> None:
        if not policy:
            return
        eff = mod.get("effects", {})
        if eff.get("network") and not policy.get("network", {}).get("allowed", False):
            diags.append(Diagnostic("CGNK_POLICY_EFFECT_DENIED", "error", f"nodes.{node_id}.effects.network", "Network effect denied by policy"))
        if eff.get("provider_call") and not policy.get("provider", {}).get("allowed", False):
            diags.append(Diagnostic("CGNK_POLICY_EFFECT_DENIED", "error", f"nodes.{node_id}.effects.provider_call", "Provider call denied by policy"))
        max_risk = int(policy.get("risk", {}).get("max_risk", 0))
        if int(eff.get("risk", 0)) > max_risk:
            diags.append(Diagnostic("CGNK_POLICY_RISK_EXCEEDED", "error", f"nodes.{node_id}.effects.risk", "Risk exceeds policy", expected=max_risk, actual=eff.get("risk")))
        for path in eff.get("fs_write", []):
            for denied in policy.get("fs", {}).get("denied_write", []):
                if fnmatch.fnmatch(path, denied) or fnmatch.fnmatch(denied, path):
                    diags.append(Diagnostic("CGNK_POLICY_WRITE_DENIED", "error", f"nodes.{node_id}.effects.fs_write", "Write path denied by policy", actual=path))

    def _check_gates(self, flow: dict[str, Any], node_map: dict[str, dict[str, Any]], diags: list[Diagnostic]) -> None:
        def walk(pred: dict[str, Any], path: str) -> None:
            if "all" in pred:
                for i, p in enumerate(pred["all"]):
                    walk(p, f"{path}.all.{i}")
            elif "any" in pred:
                for i, p in enumerate(pred["any"]):
                    walk(p, f"{path}.any.{i}")
            elif "not" in pred:
                walk(pred["not"], f"{path}.not")
            elif "node_passed" in pred and pred["node_passed"] not in node_map:
                diags.append(Diagnostic("CGNK_PREDICATE_NODE_NOT_FOUND", "error", path, "Predicate node ref not found", actual=pred["node_passed"]))

        for i, gate in enumerate(flow.get("gates", [])):
            walk(gate.get("require", {}), f"gates.{i}.require")

    def _has_cycle(self, edges: list[tuple[str, str]]) -> bool:
        graph: dict[str, list[str]] = {}
        for a, b in edges:
            graph.setdefault(a, []).append(b)
        visiting: set[str] = set()
        visited: set[str] = set()

        def dfs(n: str) -> bool:
            if n in visiting:
                return True
            if n in visited:
                return False
            visiting.add(n)
            for m in graph.get(n, []):
                if dfs(m):
                    return True
            visiting.remove(n)
            visited.add(n)
            return False

        return any(dfs(n) for n in graph)

    def _result(self, flow_ref: str, flow: dict[str, Any] | None, diags: list[Diagnostic]) -> dict[str, Any]:
        ok = not any(d.severity == "error" for d in diags)
        compiled_bundle = None
        if ok and flow is not None:
            compiled_bundle = {
                "kind": "CompiledContractBundle",
                "flow_ref": flow_ref,
                "policy_ref": flow.get("policy_ref", ""),
                "symbols": {
                    "node_count": len(flow.get("nodes", [])),
                    "edge_count": len(flow.get("edges", [])),
                },
                "checks": {"refs": "ok", "types": "ok", "policy": "ok"},
                "normalized_flow": flow,
                "metadata": {"compiler": "cgnk_core.reference_phase0"},
            }
        return {
            "kind": "CompileResult",
            "ok": ok,
            "flow_ref": flow_ref,
            "diagnostics": [d.as_dict() for d in diags],
            "compiled_bundle": compiled_bundle,
            "statistics": {
                "errors": sum(1 for d in diags if d.severity == "error"),
                "warnings": sum(1 for d in diags if d.severity == "warning"),
            },
        }


def validate_schemas(root: pathlib.Path) -> list[str]:
    try:
        import jsonschema  # noqa: F401

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from jsonschema import Draft202012Validator, RefResolver  # type: ignore
    except Exception:
        return ["jsonschema not installed; skipped schema validation"]

    schema_map = {
        "examples/artifacts": "artifact_type.schema.json",
        "examples/modules": "module_contract.schema.json",
        "examples/flows": "flow_spec.schema.json",
        "examples/policies": "policy_spec.schema.json",
        "examples/proposals": "graph_edit_proposal.schema.json",
        "examples/migrations": "migration_spec.schema.json",
    }
    schemas_dir = root / "schemas"
    store: dict[str, Any] = {}
    for sp in schemas_dir.glob("*.json"):
        schema_doc = load_json(sp)
        store[str(sp.resolve().as_uri())] = schema_doc
        if "$id" in schema_doc:
            store[str(schema_doc["$id"])] = schema_doc
            store[str(schema_doc["$id"]).rsplit("/", 1)[0] + "/" + sp.name] = schema_doc

    errs: list[str] = []

    def validate_doc(doc: dict[str, Any], schema_file: str, rel_label: str) -> None:
        schema_path = schemas_dir / schema_file
        schema = load_json(schema_path)
        resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema, store=store)
        validator = Draft202012Validator(schema, resolver=resolver)
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
            loc = "/".join(str(x) for x in err.path)
            errs.append(f"{rel_label}: {loc}: {err.message}")

    for rel, schema_file in schema_map.items():
        for path in (root / rel).glob("*.json"):
            validate_doc(load_json(path), schema_file, path.relative_to(root).as_posix())
    for path in root.glob("examples/*.contract_pack.json"):
        validate_doc(load_json(path), "contract_pack.schema.json", path.relative_to(root).as_posix())
    for path in (root / "examples/compile_results").glob("*.json"):
        validate_doc(load_json(path), "compile_result.schema.json", path.relative_to(root).as_posix())
    return errs


def validate_bundle(root: pathlib.Path, flows: list[str] | None = None, schema: bool = False) -> dict[str, Any]:
    schema_errs = validate_schemas(root) if schema else ["schema validation skipped; pass --schema to enable optional jsonschema checks"]
    idx = ContractIndex(root)
    compiler = ReferenceCompiler(idx)
    selected_flows = flows or sorted(idx.flows.keys())
    results = [compiler.compile(f) for f in selected_flows]
    return {"schema_validation": schema_errs, "results": results}
