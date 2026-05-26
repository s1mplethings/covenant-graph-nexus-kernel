from __future__ import annotations

from copy import deepcopy
from typing import Any

from cgnk_core.compiler import compile_flow
from cgnk_core.contract_pack import build_agent_contract_pack
from cgnk_core.diagnostics import (
    CGNK_SLICE_CONTRACT_PACK_MISSING,
    CGNK_SLICE_FEATURE_MISSING,
    CGNK_SLICE_FLOW_MISSING,
    CGNK_SLICE_MIGRATION_MISSING,
    CGNK_SLICE_NOT_READY,
    CGNK_SLICE_PROOF_INCOMPLETE,
    Diagnostic,
)
from cgnk_core.graph_edit import apply_graph_edit_proposal
from cgnk_core.registry import ContractRegistry
from cgnk_core.schema_loader import load_json

from .migration import build_migration_proof

REQUIRED_PROJECT_GENERATION_PRESERVE = {
    "cli_args",
    "summary_json_schema",
    "benchmark_report_format",
    "provider_call_semantics",
}

REQUIRED_PROOF_REQUIREMENTS = {
    "legacy_file_presence",
    "public_entrypoint_presence",
    "required_tests_declared",
    "required_artifacts_declared",
    "required_schemas_declared",
    "agent_contract_pack_generation",
    "graph_hashes_available",
    "proposal_preview_available",
}


def check_slice_readiness(
    feature_id: str,
    feature_map: dict[str, Any],
    registry: ContractRegistry,
    ctcp_root,
    proposal_path,
) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    missing: list[str] = []
    feature = next((row for row in feature_map.get("features", []) if row.get("id") == feature_id), None)
    if feature is None:
        diagnostics.append(Diagnostic(CGNK_SLICE_FEATURE_MISSING, "error", "$.feature", "Feature is missing from CTCPFeatureMapSpec", expected=feature_id, actual=None, involved_ref=feature_id))
        return _report(False, feature_id, None, None, "blocked", missing, diagnostics)

    migration_ref = feature.get("migration")
    migration = registry.migration_specs.get(migration_ref)
    if migration is None:
        diagnostics.append(Diagnostic(CGNK_SLICE_MIGRATION_MISSING, "error", "$.migration", "Migration spec is missing", expected="known migration ref", actual=migration_ref, involved_ref=migration_ref))
        missing.append("migration.project_generation exists")

    target_flow = feature.get("target", {}).get("flow")
    flow = registry.resolve_flow(target_flow or "")
    if flow is None:
        diagnostics.append(Diagnostic(CGNK_SLICE_FLOW_MISSING, "error", "$.target_flow", "Target flow is missing", expected="known flow ref", actual=target_flow, involved_ref=target_flow))
        missing.append("target flow exists")

    if migration is not None:
        preserve = {key for key, value in migration.get("preserve", {}).items() if value}
        for required in sorted(REQUIRED_PROJECT_GENERATION_PRESERVE - preserve):
            missing.append(f"preserve constraint declared: {required}")
            diagnostics.append(Diagnostic(CGNK_SLICE_PROOF_INCOMPLETE, "error", f"$.preserve.{required}", "Required preserve constraint is missing", expected=True, actual=False, involved_ref=migration_ref))
        proof = build_migration_proof(migration, registry, ctcp_root)
        diagnostics.extend(_slice_diag_from_proof(row) for row in proof.get("diagnostics", []))
        _check_migration_proof_requirements(proof, missing, diagnostics, migration_ref)
    else:
        proof = None
        missing.extend(sorted(REQUIRED_PROOF_REQUIREMENTS))

    compile_result = compile_flow(target_flow, registry) if target_flow else {"ok": False}
    if not compile_result.get("ok"):
        missing.append("target flow compiles")
    if not all(compile_result.get(name) for name in ("surface_hash", "policy_hash", "graph_hash")):
        missing.append("graph hashes available")
        diagnostics.append(Diagnostic(CGNK_SLICE_PROOF_INCOMPLETE, "error", "$.compile.hashes", "Compile result does not include all graph hashes", expected=["surface_hash", "policy_hash", "graph_hash"], actual=compile_result.get("hashes"), involved_ref=target_flow))

    if flow is not None and compile_result.get("ok"):
        policy = registry.resolve_policy(compile_result.get("policy_ref", ""))
        if policy is None:
            diagnostics.append(Diagnostic(CGNK_SLICE_CONTRACT_PACK_MISSING, "error", "$.contract_pack", "Policy unavailable for AgentContractPack generation", actual=compile_result.get("policy_ref")))
            missing.append("agent contract pack generation")
        else:
            pack = build_agent_contract_pack(compile_result, flow, policy, list(registry.modules.values()), list(registry.artifacts.values()), "migration")
            pack_diags = registry.schema_loader.validate(pack, "agent_contract_pack.schema.json", "$.agent_contract_pack")
            if pack_diags:
                diagnostics.append(Diagnostic(CGNK_SLICE_CONTRACT_PACK_MISSING, "error", "$.agent_contract_pack", "AgentContractPack failed schema validation", actual=[d.as_dict() for d in pack_diags], involved_ref=target_flow))
                missing.append("agent contract pack generation")

    proposal = load_json(proposal_path)
    preview = apply_graph_edit_proposal(proposal, registry, dry_run=True)
    if not preview.get("ok"):
        diagnostics.append(Diagnostic(CGNK_SLICE_PROOF_INCOMPLETE, "error", "$.proposal_preview", "Required proposal preview is not available", expected="ok preview", actual=preview.get("diagnostics"), involved_ref=proposal.get("id")))
        missing.append("proposal preview available")

    missing = sorted(set(missing))
    if missing:
        diagnostics.append(Diagnostic(CGNK_SLICE_NOT_READY, "error", "$.readiness_status", "Slice is not ready for refactor", expected="ready_for_refactor", actual="blocked", involved_ref=feature_id))
    return _report(not missing and not any(d.severity == "error" for d in diagnostics), feature_id, migration_ref, target_flow, "ready_for_refactor" if not missing else "blocked", missing, diagnostics)


def _check_migration_proof_requirements(proof: dict[str, Any], missing: list[str], diagnostics: list[Diagnostic], migration_ref: str | None) -> None:
    evidence = proof.get("evidence", {})
    if not evidence.get("legacy_files") or not all(row.get("exists") is True for row in evidence.get("legacy_files", [])):
        missing.append("legacy file presence")
    if not evidence.get("public_entrypoints") or not all(row.get("locations") for row in evidence.get("public_entrypoints", [])):
        missing.append("public entrypoint presence")
    if not evidence.get("required_tests"):
        missing.append("required tests declared")
    if not evidence.get("required_artifacts"):
        missing.append("required artifacts declared")
    if not evidence.get("required_schemas"):
        missing.append("required schemas declared")
    for requirement in missing:
        if requirement in {
            "legacy file presence",
            "public entrypoint presence",
            "required tests declared",
            "required artifacts declared",
            "required schemas declared",
        }:
            diagnostics.append(Diagnostic(CGNK_SLICE_PROOF_INCOMPLETE, "error", "$.migration_proof", "Migration proof requirement is incomplete", expected=requirement, actual=False, involved_ref=migration_ref))


def _slice_diag_from_proof(row: dict[str, Any]) -> Diagnostic:
    return Diagnostic(
        row.get("code", CGNK_SLICE_PROOF_INCOMPLETE),
        row.get("severity", "error"),
        row.get("path", "$.migration_proof"),
        row.get("message", "Migration proof diagnostic"),
        expected=row.get("expected"),
        actual=row.get("actual"),
        involved_ref=row.get("involved_ref"),
    )


def _report(
    ok: bool,
    feature_id: str,
    migration_ref: str | None,
    target_flow: str | None,
    readiness_status: str,
    missing: list[str],
    diagnostics: list[Diagnostic],
) -> dict[str, Any]:
    return {
        "kind": "SliceReadinessReport",
        "ok": ok,
        "feature": feature_id,
        "migration": migration_ref,
        "target_flow": target_flow,
        "readiness_status": readiness_status,
        "missing_requirements": missing,
        "diagnostics": [d.as_dict() for d in diagnostics],
        "required_next_outputs": [
            "MigrationProof",
            "AgentContractPack",
            "GraphEditProposal preview",
            "CompileResult with graph hashes"
        ],
    }
