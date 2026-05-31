
#!/usr/bin/env python3
from __future__ import annotations
import argparse, fnmatch, json, pathlib, sys, warnings
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def ref_of(doc: dict[str, Any]) -> str:
    return f"{doc['id']}@{doc['version']}"

@dataclass
class Diagnostic:
    code: str
    severity: str
    path: str
    message: str
    expected: Any = None
    actual: Any = None
    def as_dict(self) -> dict[str, Any]:
        out = {"code": self.code, "severity": self.severity, "path": self.path, "message": self.message}
        if self.expected is not None: out["expected"] = self.expected
        if self.actual is not None: out["actual"] = self.actual
        return out

class ContractIndex:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.artifacts = {ref_of(d): d for d in self._load_dir("examples/artifacts")}
        self.modules = {ref_of(d): d for d in self._load_dir("examples/modules")}
        self.policies = {ref_of(d): d for d in self._load_dir("examples/policies")}
        self.flows = {ref_of(d): d for d in self._load_dir("examples/flows")}
        self.migrations = {ref_of(d): d for d in self._load_dir("examples/migrations")}
        self.contract_packs = self._load_glob("examples/*.contract_pack.json")
        self.compile_results = self._load_glob("examples/compile_results/*.json")
        self.proposals = self._load_dir("examples/proposals")
    def _load_dir(self, rel: str) -> list[dict[str, Any]]:
        return [load_json(p) for p in sorted((self.root / rel).glob("*.json"))]
    def _load_glob(self, pattern: str) -> list[tuple[pathlib.Path, dict[str, Any]]]:
        return [(p, load_json(p)) for p in sorted(self.root.glob(pattern))]

class Compiler:
    def __init__(self, index: ContractIndex):
        self.idx = index
    def compile(self, flow_ref: str) -> dict[str, Any]:
        diags: list[Diagnostic] = []
        flow = self.idx.flows.get(flow_ref)
        if flow is None:
            diags.append(Diagnostic("CGNK_FLOW_NOT_FOUND", "error", "flow", "Flow ref not found", actual=flow_ref))
            return self._result(flow_ref, None, diags)
        policy = self.idx.policies.get(flow.get("policy_ref", ""))
        if policy is None:
            diags.append(Diagnostic("CGNK_POLICY_NOT_FOUND", "error", "policy_ref", "Policy ref not found", actual=flow.get("policy_ref")))
        for name, aref in {**flow.get("inputs", {}), **flow.get("outputs", {})}.items():
            if aref not in self.idx.artifacts:
                diags.append(Diagnostic("CGNK_ARTIFACT_TYPE_NOT_FOUND", "error", f"flow.{name}", "Artifact ref not found", actual=aref))
        node_map = {}
        for node in flow.get("nodes", []):
            uses = node.get("uses")
            mod = self.idx.modules.get(uses)
            if mod is None:
                diags.append(Diagnostic("CGNK_MODULE_NOT_FOUND", "error", f"nodes.{node.get('id')}.uses", "Module ref not found", actual=uses))
            else:
                node_map[node["id"]] = {"node": node, "module": mod}
                self._check_policy(node["id"], mod, policy, diags)
                for side in ("input", "output"):
                    for port, spec in mod.get("ports", {}).get(side, {}).items():
                        aref = spec.get("artifact_type")
                        if aref not in self.idx.artifacts:
                            diags.append(Diagnostic("CGNK_ARTIFACT_TYPE_NOT_FOUND", "error", f"module.{mod['id']}.{side}.{port}", "Artifact ref not found", actual=aref))
        bound_inputs: dict[tuple[str, str], int] = {}
        output_sources = set()
        graph_edges = []
        for i, edge in enumerate(flow.get("edges", [])):
            src_type = self._endpoint_type(edge.get("from", {}), flow, node_map, "output", diags, f"edges.{i}.from")
            tgt_type = self._endpoint_type(edge.get("to", {}), flow, node_map, "input", diags, f"edges.{i}.to")
            if src_type and tgt_type and not self._artifact_compatible(src_type, tgt_type):
                diags.append(Diagnostic("CGNK_EDGE_TYPE_MISMATCH", "error", f"edges.{i}", "Edge artifact type mismatch", expected=tgt_type, actual=src_type))
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
                    diags.append(Diagnostic("CGNK_INPUT_UNBOUND", "error", f"nodes.{nid}.ports.input.{port}", "Required input port is not bound"))
                if bound_inputs.get((nid, port), 0) > 1 and not spec.get("multi", False):
                    diags.append(Diagnostic("CGNK_INPUT_MULTI_PRODUCER", "error", f"nodes.{nid}.ports.input.{port}", "Input port has multiple producers"))
        for out_name in flow.get("outputs", {}):
            if out_name not in output_sources:
                diags.append(Diagnostic("CGNK_OUTPUT_UNBOUND", "error", f"outputs.{out_name}", "Flow output is not bound"))
        if self._has_cycle(graph_edges):
            diags.append(Diagnostic("CGNK_GRAPH_CYCLE", "error", "edges", "Flow node graph contains a cycle"))
        self._check_gates(flow, node_map, diags)
        return self._result(flow_ref, flow, diags)
    def _endpoint_type(self, ep, flow, node_map, side, diags, path):
        if side == "output" and "flow_input" in ep:
            aref = flow.get("inputs", {}).get(ep["flow_input"])
            if not aref: diags.append(Diagnostic("CGNK_FLOW_INPUT_NOT_FOUND", "error", path, "Flow input not found", actual=ep.get("flow_input")))
            return aref
        if side == "input" and "flow_output" in ep:
            aref = flow.get("outputs", {}).get(ep["flow_output"])
            if not aref: diags.append(Diagnostic("CGNK_FLOW_OUTPUT_NOT_FOUND", "error", path, "Flow output not found", actual=ep.get("flow_output")))
            return aref
        if "node" in ep:
            row = node_map.get(ep.get("node"))
            if row is None:
                diags.append(Diagnostic("CGNK_NODE_NOT_FOUND", "error", path, "Node not found", actual=ep.get("node"))); return None
            port_spec = row["module"].get("ports", {}).get(side, {}).get(ep.get("port"))
            if port_spec is None:
                diags.append(Diagnostic("CGNK_PORT_NOT_FOUND", "error", path, f"{side} port not found", actual=ep.get("port"))); return None
            return port_spec.get("artifact_type")
        diags.append(Diagnostic("CGNK_ENDPOINT_INVALID", "error", path, "Endpoint has invalid direction")); return None
    def _artifact_compatible(self, src, tgt):
        if src == tgt: return True
        sdoc = self.idx.artifacts.get(src, {})
        return tgt in sdoc.get("compatibility", {}).get("backward_compatible_with", [])
    def _check_policy(self, node_id, mod, policy, diags):
        if not policy: return
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
    def _check_gates(self, flow, node_map, diags):
        def walk(pred, path):
            if "all" in pred:
                for i, p in enumerate(pred["all"]): walk(p, f"{path}.all.{i}")
            elif "any" in pred:
                for i, p in enumerate(pred["any"]): walk(p, f"{path}.any.{i}")
            elif "not" in pred: walk(pred["not"], f"{path}.not")
            elif "node_passed" in pred and pred["node_passed"] not in node_map:
                diags.append(Diagnostic("CGNK_PREDICATE_NODE_NOT_FOUND", "error", path, "Predicate node ref not found", actual=pred["node_passed"]))
        for i, gate in enumerate(flow.get("gates", [])):
            walk(gate.get("require", {}), f"gates.{i}.require")
    def _has_cycle(self, edges):
        graph = {}
        for a,b in edges: graph.setdefault(a, []).append(b)
        visiting, visited = set(), set()
        def dfs(n):
            if n in visiting: return True
            if n in visited: return False
            visiting.add(n)
            for m in graph.get(n, []):
                if dfs(m): return True
            visiting.remove(n); visited.add(n); return False
        return any(dfs(n) for n in graph)
    def _result(self, flow_ref, flow, diags):
        ok = not any(d.severity == "error" for d in diags)
        return {"kind":"CompileResult","ok":ok,"flow_ref":flow_ref,"diagnostics":[d.as_dict() for d in diags],"compiled_bundle": None if not ok else {"kind":"CompiledContractBundle","flow_ref":flow_ref,"policy_ref":flow.get("policy_ref","") if flow else "","symbols":{"node_count":len(flow.get("nodes",[])) if flow else 0,"edge_count":len(flow.get("edges",[])) if flow else 0},"checks":{"refs":"ok","types":"ok","policy":"ok"},"normalized_flow":flow,"metadata":{"compiler":"reference_validate_bundle.py"}},"statistics":{"errors":sum(1 for d in diags if d.severity=='error'),"warnings":sum(1 for d in diags if d.severity=='warning')}}

def validate_cross_refs(idx: ContractIndex, compile_results: dict[str, dict[str, Any]]) -> list[Diagnostic]:
    diags: list[Diagnostic] = []

    def has_ref(table: dict[str, Any], ref: str, code: str, path: str, label: str) -> None:
        if ref not in table:
            diags.append(Diagnostic(code, "error", path, f"{label} ref not found", actual=ref))

    for migration_ref, migration in sorted(idx.migrations.items()):
        prefix = f"migrations.{migration_ref}"
        target = migration.get("target", {})
        flow_ref = target.get("flow")
        if flow_ref:
            has_ref(idx.flows, flow_ref, "CGNK_MIGRATION_FLOW_NOT_FOUND", f"{prefix}.target.flow", "Migration target flow")
        else:
            diags.append(Diagnostic("CGNK_MIGRATION_FLOW_NOT_FOUND", "error", f"{prefix}.target.flow", "Migration target flow is missing"))
        for i, module_ref in enumerate(target.get("modules", [])):
            has_ref(idx.modules, module_ref, "CGNK_MIGRATION_MODULE_NOT_FOUND", f"{prefix}.target.modules.{i}", "Migration target module")
        if flow_ref in idx.flows:
            flow_modules = {node.get("uses") for node in idx.flows[flow_ref].get("nodes", [])}
            for i, module_ref in enumerate(target.get("modules", [])):
                if module_ref in idx.modules and module_ref not in flow_modules:
                    diags.append(Diagnostic("CGNK_MIGRATION_MODULE_NOT_IN_FLOW", "error", f"{prefix}.target.modules.{i}", "Migration target module is not used by target flow", expected=flow_ref, actual=module_ref))

    for path, pack in idx.contract_packs:
        prefix = path.relative_to(idx.root).as_posix()
        flow_ref = pack.get("flow")
        policy_ref = pack.get("policy")
        migration_ref = pack.get("migration")
        if flow_ref:
            has_ref(idx.flows, flow_ref, "CGNK_CONTRACT_PACK_FLOW_NOT_FOUND", f"{prefix}.flow", "ContractPack flow")
        if policy_ref:
            has_ref(idx.policies, policy_ref, "CGNK_CONTRACT_PACK_POLICY_NOT_FOUND", f"{prefix}.policy", "ContractPack policy")
        if migration_ref:
            has_ref(idx.migrations, migration_ref, "CGNK_CONTRACT_PACK_MIGRATION_NOT_FOUND", f"{prefix}.migration", "ContractPack migration")
        for i, module_ref in enumerate(pack.get("required_modules", [])):
            has_ref(idx.modules, module_ref, "CGNK_CONTRACT_PACK_MODULE_NOT_FOUND", f"{prefix}.required_modules.{i}", "ContractPack required module")
        for i, artifact_ref in enumerate(pack.get("required_artifacts", [])):
            has_ref(idx.artifacts, artifact_ref, "CGNK_CONTRACT_PACK_ARTIFACT_NOT_FOUND", f"{prefix}.required_artifacts.{i}", "ContractPack required artifact")
        if flow_ref in idx.flows:
            flow = idx.flows[flow_ref]
            if policy_ref and policy_ref != flow.get("policy_ref"):
                diags.append(Diagnostic("CGNK_CONTRACT_PACK_POLICY_MISMATCH", "error", f"{prefix}.policy", "ContractPack policy does not match flow policy", expected=flow.get("policy_ref"), actual=policy_ref))
            flow_modules = {node.get("uses") for node in flow.get("nodes", [])}
            for i, module_ref in enumerate(pack.get("required_modules", [])):
                if module_ref in idx.modules and module_ref not in flow_modules:
                    diags.append(Diagnostic("CGNK_CONTRACT_PACK_MODULE_NOT_IN_FLOW", "error", f"{prefix}.required_modules.{i}", "ContractPack required module is not used by flow", expected=flow_ref, actual=module_ref))

    for proposal in idx.proposals:
        proposal_id = proposal.get("id", "<unknown>")
        prefix = f"proposals.{proposal_id}"
        target_flow = proposal.get("target_flow")
        if target_flow:
            has_ref(idx.flows, target_flow, "CGNK_PROPOSAL_FLOW_NOT_FOUND", f"{prefix}.target_flow", "Proposal target flow")
        for i, edit in enumerate(proposal.get("edits", [])):
            op = edit.get("op")
            if op == "add_node":
                module_ref = edit.get("node", {}).get("uses")
                has_ref(idx.modules, module_ref, "CGNK_PROPOSAL_MODULE_NOT_FOUND", f"{prefix}.edits.{i}.node.uses", "Proposal node module")
            elif op == "replace_node":
                module_ref = edit.get("replacement", {}).get("uses")
                has_ref(idx.modules, module_ref, "CGNK_PROPOSAL_MODULE_NOT_FOUND", f"{prefix}.edits.{i}.replacement.uses", "Proposal replacement module")
            elif op == "upgrade_module_version":
                has_ref(idx.modules, edit.get("module_ref"), "CGNK_PROPOSAL_MODULE_NOT_FOUND", f"{prefix}.edits.{i}.module_ref", "Proposal module")
            elif op == "change_policy_ref":
                has_ref(idx.policies, edit.get("policy_ref"), "CGNK_PROPOSAL_POLICY_NOT_FOUND", f"{prefix}.edits.{i}.policy_ref", "Proposal policy")

    for path, snapshot in idx.compile_results:
        prefix = path.relative_to(idx.root).as_posix()
        flow_ref = snapshot.get("flow_ref")
        if not flow_ref:
            diags.append(Diagnostic("CGNK_COMPILE_RESULT_FLOW_NOT_FOUND", "error", f"{prefix}.flow_ref", "CompileResult flow_ref is missing"))
            continue
        has_ref(idx.flows, flow_ref, "CGNK_COMPILE_RESULT_FLOW_NOT_FOUND", f"{prefix}.flow_ref", "CompileResult flow")
        current = compile_results.get(flow_ref)
        if not current:
            continue
        if snapshot.get("ok") != current.get("ok"):
            diags.append(Diagnostic("CGNK_COMPILE_RESULT_OK_MISMATCH", "error", f"{prefix}.ok", "CompileResult ok does not match current compile", expected=current.get("ok"), actual=snapshot.get("ok")))
        snap_bundle = snapshot.get("compiled_bundle") or {}
        cur_bundle = current.get("compiled_bundle") or {}
        for key in ("flow_ref", "policy_ref"):
            if snap_bundle.get(key) != cur_bundle.get(key):
                diags.append(Diagnostic("CGNK_COMPILE_RESULT_BUNDLE_MISMATCH", "error", f"{prefix}.compiled_bundle.{key}", "CompileResult bundle field does not match current compile", expected=cur_bundle.get(key), actual=snap_bundle.get(key)))
        snap_symbols = snap_bundle.get("symbols", {})
        cur_symbols = cur_bundle.get("symbols", {})
        for key in ("node_count", "edge_count"):
            if snap_symbols.get(key) != cur_symbols.get(key):
                diags.append(Diagnostic("CGNK_COMPILE_RESULT_SYMBOL_MISMATCH", "error", f"{prefix}.compiled_bundle.symbols.{key}", "CompileResult symbol count does not match current compile", expected=cur_symbols.get(key), actual=snap_symbols.get(key)))
        snap_diags = snapshot.get("diagnostics", [])
        cur_diags = current.get("diagnostics", [])
        if snap_diags != cur_diags:
            diags.append(Diagnostic("CGNK_COMPILE_RESULT_DIAGNOSTICS_MISMATCH", "error", f"{prefix}.diagnostics", "CompileResult diagnostics do not match current compile", expected=cur_diags, actual=snap_diags))

    return diags

def validate_schemas(root: pathlib.Path) -> list[str]:
    # Optional jsonschema validation with local relative-reference resolution.
    try:
        import jsonschema  # type: ignore
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
    errs=[]
    def validate_doc(doc: dict[str, Any], schema_file: str, rel_label: str) -> None:
        schema_path = schemas_dir / schema_file
        schema = load_json(schema_path)
        resolver = RefResolver(base_uri=schema_path.resolve().as_uri(), referrer=schema, store=store)
        validator = Draft202012Validator(schema, resolver=resolver)
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
            loc = "/".join(str(x) for x in err.path)
            errs.append(f"{rel_label}: {loc}: {err.message}")
    for rel, schema_file in schema_map.items():
        for path in (root/rel).glob("*.json"):
            validate_doc(load_json(path), schema_file, path.relative_to(root).as_posix())
    for path in root.glob("examples/*.contract_pack.json"):
        validate_doc(load_json(path), "contract_pack.schema.json", path.relative_to(root).as_posix())
    for path in (root/"examples/compile_results").glob("*.json"):
        validate_doc(load_json(path), "compile_result.schema.json", path.relative_to(root).as_posix())
    return errs

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--flow", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--schema", action="store_true", help="Run optional jsonschema validation. Semantic compile checks run by default.")
    args = ap.parse_args()
    root = pathlib.Path(args.root).resolve()
    schema_errs = validate_schemas(root) if args.schema else ["schema validation skipped; pass --schema to enable optional jsonschema checks"]
    idx = ContractIndex(root)
    comp = Compiler(idx)
    flows = args.flow or sorted(idx.flows.keys())
    results = [comp.compile(f) for f in flows]
    all_compile_results = {flow_ref: comp.compile(flow_ref) for flow_ref in sorted(idx.flows.keys())}
    ref_diags = validate_cross_refs(idx, all_compile_results)
    out = {"schema_validation": schema_errs, "reference_validation": [d.as_dict() for d in ref_diags], "results": results}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for msg in schema_errs:
            print(f"SCHEMA: {msg}")
        if ref_diags:
            print(f"REFS: FAIL errors={sum(1 for d in ref_diags if d.severity == 'error')}")
            for d in ref_diags:
                row = d.as_dict()
                print(f"  {d.severity.upper()} {d.code} {d.path}: {d.message}")
                if "expected" in row or "actual" in row:
                    print(f"    expected={row.get('expected')} actual={row.get('actual')}")
        else:
            print("REFS: OK errors=0")
        for r in results:
            print(f"{r['flow_ref']}: {'OK' if r['ok'] else 'FAIL'} errors={r['statistics']['errors']}")
            for d in r["diagnostics"]:
                print(f"  {d['severity'].upper()} {d['code']} {d['path']}: {d['message']}")
    real_schema_errs = [m for m in schema_errs if not m.startswith("schema validation skipped")]
    real_ref_errs = [d for d in ref_diags if d.severity == "error"]
    return 0 if not real_schema_errs and not real_ref_errs and all(r["ok"] for r in results) else 1
if __name__ == "__main__":
    raise SystemExit(main())
