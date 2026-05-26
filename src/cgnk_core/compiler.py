from __future__ import annotations

from copy import deepcopy
from typing import Any

from .diagnostics import CGNK_FLOW_NOT_FOUND, CGNK_POLICY_NOT_FOUND, Diagnostic
from .contract_pack import build_contract_pack
from .normalization import build_compiled_flow, build_normalized_bundle, build_symbol_table
from .refs import ref_of
from .registry import ContractRegistry
from .semantic_validator import SemanticValidator


def compile_flow(flow_ref: str, registry: ContractRegistry, policy_ref: str | None = None, flow_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    flow = deepcopy(flow_doc) if flow_doc is not None else deepcopy(registry.resolve_flow(flow_ref))
    if flow is None:
        diagnostics.append(Diagnostic(CGNK_FLOW_NOT_FOUND, "error", "$.flow_ref", "Flow ref not found", actual=flow_ref))
        return _result(flow_ref, policy_ref or "", diagnostics)
    if policy_ref is not None:
        flow["policy_ref"] = policy_ref
    policy = registry.resolve_policy(flow.get("policy_ref", ""))
    if policy is None:
        diagnostics.append(Diagnostic(CGNK_POLICY_NOT_FOUND, "error", "$.policy_ref", "Policy ref not found", actual=flow.get("policy_ref")))
    diagnostics.extend(registry.schema_loader.validate(flow, path="$.flow"))
    diagnostics.extend(SemanticValidator(registry).validate_flow(flow))

    ok = not any(d.severity == "error" for d in diagnostics)
    modules = []
    artifacts: set[str] = set(flow.get("inputs", {}).values()) | set(flow.get("outputs", {}).values())
    artifact_docs: dict[str, dict[str, Any]] = {}
    for node in flow.get("nodes", []):
        module = registry.resolve_module(node.get("uses"))
        if module:
            modules.append(module)
            for side in ("input", "output"):
                for spec in module.get("ports", {}).get(side, {}).values():
                    artifacts.add(spec["artifact_type"])
    for artifact_ref in artifacts:
        artifact = registry.resolve_artifact(artifact_ref)
        if artifact:
            artifact_docs[artifact_ref] = artifact

    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    symbol_table = build_symbol_table(flow, policy, modules, artifact_docs) if policy is not None else {}
    compiled_flow = build_compiled_flow(flow, symbol_table) if policy is not None else None
    normalized_bundle = (
        build_normalized_bundle(flow, policy, modules, artifact_docs, diagnostic_dicts)
        if policy is not None
        else None
    )

    bundle = None
    contract_pack = None
    if ok and policy is not None:
        contract_pack = build_contract_pack(flow, policy, modules, list(artifacts))
        bundle = {
            "kind": "CompiledContractBundle",
            "flow_ref": ref_of(flow),
            "policy_ref": ref_of(policy),
            "symbols": {
                "artifacts": sorted(artifacts),
                "modules": [f"{m['id']}@{m['version']}" for m in modules],
                "nodes": [n["id"] for n in flow.get("nodes", [])],
            },
            "checks": {"schema": "ok", "semantic": "ok", "policy": "ok"},
            "normalized_bundle": normalized_bundle,
            "compiled_flow": compiled_flow,
            "symbol_table": symbol_table,
            "diagnostics": diagnostic_dicts,
            "normalized_flow": flow,
            "metadata": {"compiler": "cgnk_core.compiler"},
        }

    result = _result(ref_of(flow), flow.get("policy_ref", ""), diagnostics, bundle)
    result.update(
        {
            "schema_version": "1",
            "policy_ref": flow.get("policy_ref", ""),
            "normalized_bundle": normalized_bundle,
            "compiled_flow": compiled_flow,
            "symbol_table": symbol_table,
            "resolved_nodes": flow.get("nodes", []),
            "resolved_edges": flow.get("edges", []),
            "resolved_artifacts": sorted(artifacts),
            "required_inputs": flow.get("inputs", {}),
            "produced_outputs": flow.get("outputs", {}),
            "effect_summary": _effect_summary(modules),
            "capability_summary": _capability_summary(modules),
            "gates": flow.get("gates", []),
            "compiled_contract_bundle": bundle,
            "contract_pack": contract_pack,
        }
    )
    return result


def _result(flow_ref: str, policy_ref: str, diagnostics: list[Diagnostic], compiled_bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "CompileResult",
        "ok": not any(d.severity == "error" for d in diagnostics),
        "flow_ref": flow_ref,
        "policy_ref": policy_ref,
        "diagnostics": [d.as_dict() for d in diagnostics],
        "compiled_bundle": compiled_bundle,
        "statistics": {
            "errors": sum(1 for d in diagnostics if d.severity == "error"),
            "warnings": sum(1 for d in diagnostics if d.severity == "warning"),
        },
    }


def _effect_summary(modules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "network": any(m.get("effects", {}).get("network", False) for m in modules),
        "provider_call": any(m.get("effects", {}).get("provider_call", False) for m in modules),
        "max_risk": max([m.get("effects", {}).get("risk", 0) for m in modules] or [0]),
    }


def _capability_summary(modules: list[dict[str, Any]]) -> list[str]:
    caps: set[str] = set()
    for module in modules:
        for cap in module.get("requires", {}).get("capabilities", []):
            if "id" in cap:
                caps.add(cap["id"])
    return sorted(caps)
