from __future__ import annotations

import json
import pathlib
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_MIGRATION_ENTRYPOINT_MISSING,
    CGNK_MIGRATION_LEGACY_FILE_MISSING,
    CGNK_MIGRATION_PRESERVE_CONSTRAINT_MISSING,
    CGNK_MIGRATION_PROOF_INVALID,
    CGNK_MIGRATION_PROOF_MISSING,
    CGNK_MIGRATION_REQUIRED_ARTIFACT_MISSING,
    CGNK_MIGRATION_REQUIRED_SCHEMA_MISSING,
    CGNK_MIGRATION_REQUIRED_TEST_MISSING,
    CGNK_MIGRATION_TARGET_ARTIFACT_MISSING,
    CGNK_MIGRATION_TARGET_FLOW_MISSING,
    CGNK_MIGRATION_TARGET_MODULE_MISSING,
    Diagnostic,
)
from cgnk_core.registry import ContractRegistry
from cgnk_core.refs import ref_of

from .feature_map import SELECTED_FEATURES, rejected_features, selected_features

REQUIRED_PRESERVE = {
    "cli_args",
    "summary_json_schema",
    "benchmark_report_format",
    "provider_call_semantics",
    "timeout_guard_semantics",
    "file_hash_cache_evidence",
    "support decision flow",
    "repo hygiene guard",
}


def build_migration_proof(spec: dict[str, Any], registry: ContractRegistry, ctcp_root: pathlib.Path | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    legacy_files = spec.get("legacy", {}).get("files", [])
    public_entrypoints = spec.get("legacy", {}).get("public_entrypoints", [])
    legacy_evidence: list[dict[str, Any]] = []
    entrypoint_evidence: list[dict[str, Any]] = []
    if ctcp_root is not None:
        for rel in legacy_files:
            path = ctcp_root / rel
            exists = path.exists() and path.is_file()
            legacy_evidence.append({"path": rel, "exists": exists})
            if not exists:
                diagnostics.append(Diagnostic(CGNK_MIGRATION_LEGACY_FILE_MISSING, "error", f"$.legacy.files[{rel}]", "Legacy file is missing", expected="file exists under --ctcp-root", actual=rel, involved_ref=rel))
        readable_texts = _read_legacy_texts(ctcp_root, legacy_files)
        for entrypoint in public_entrypoints:
            locations = [rel for rel, text in readable_texts.items() if entrypoint in text]
            entrypoint_evidence.append({"entrypoint": entrypoint, "locations": locations})
            if not locations:
                diagnostics.append(Diagnostic(CGNK_MIGRATION_ENTRYPOINT_MISSING, "error", f"$.legacy.public_entrypoints[{entrypoint}]", "Declared public entrypoint is missing from legacy files", expected="entrypoint text in a legacy file", actual=entrypoint, involved_ref=entrypoint))
    elif legacy_files:
        legacy_evidence = [{"path": rel, "exists": None} for rel in legacy_files]
        entrypoint_evidence = [{"entrypoint": entrypoint, "locations": []} for entrypoint in public_entrypoints]

    target = spec.get("target", {})
    for module_ref in target.get("modules", []):
        if registry.resolve_module(module_ref) is None:
            diagnostics.append(Diagnostic(CGNK_MIGRATION_TARGET_MODULE_MISSING, "error", "$.target.modules", "Target module cannot be resolved", expected="known module ref", actual=module_ref, involved_ref=module_ref))
    flow_ref = target.get("flow")
    if flow_ref and registry.resolve_flow(flow_ref) is None:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_TARGET_FLOW_MISSING, "error", "$.target.flow", "Target flow cannot be resolved", expected="known flow ref", actual=flow_ref, involved_ref=flow_ref))
    for artifact_ref in target.get("artifacts", []):
        if registry.resolve_artifact(artifact_ref) is None:
            diagnostics.append(Diagnostic(CGNK_MIGRATION_TARGET_ARTIFACT_MISSING, "error", "$.target.artifacts", "Target artifact cannot be resolved", expected="known artifact ref", actual=artifact_ref, involved_ref=artifact_ref))

    preserve = set(k for k, v in spec.get("preserve", {}).items() if v)
    missing_preserve = sorted(REQUIRED_PRESERVE - preserve)
    for key in missing_preserve:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_PRESERVE_CONSTRAINT_MISSING, "warning", f"$.preserve.{key}", "Recommended external behavior preserve proof is missing", expected="declared preserve=true", actual=key, involved_ref=key))

    proof = spec.get("proof", {})
    required_tests = proof.get("required_tests", [])
    required_artifacts = proof.get("required_artifacts", [])
    required_schemas = proof.get("required_schemas", [])
    if not required_tests:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_REQUIRED_TEST_MISSING, "error", "$.proof.required_tests", "MigrationSpec must declare required tests", expected="non-empty required_tests", actual=required_tests))
    if not required_artifacts:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_REQUIRED_ARTIFACT_MISSING, "error", "$.proof.required_artifacts", "MigrationSpec must declare required proof artifacts", expected="non-empty required_artifacts", actual=required_artifacts))
    if spec.get("preserve", {}).get("summary_json_schema") and not required_schemas:
        diagnostics.append(Diagnostic(CGNK_MIGRATION_REQUIRED_SCHEMA_MISSING, "error", "$.proof.required_schemas", "Output schema preservation requires declared schemas", expected="required_schemas", actual=required_schemas))

    proof_doc = {
        "kind": "MigrationProof",
        "schema_version": "1",
        "migration_ref": ref_of(spec),
        "target_flow": flow_ref or "",
        "preserved_constraints": sorted(preserve),
        "evidence": {
            "legacy_files": legacy_evidence,
            "public_entrypoints": entrypoint_evidence,
            "target_modules": sorted(target.get("modules", [])),
            "target_artifacts": sorted(target.get("artifacts", [])),
            "required_tests": sorted(required_tests),
            "required_artifacts": sorted(required_artifacts),
            "required_schemas": sorted(required_schemas),
        },
        "diagnostics": [d.as_dict() for d in diagnostics],
        "ok": not any(d.severity == "error" for d in diagnostics),
    }
    schema_diagnostics = registry.schema_loader.validate(proof_doc, "migration_proof.schema.json", "$.migration_proof")
    if schema_diagnostics:
        diagnostics.extend(
            Diagnostic(CGNK_MIGRATION_PROOF_INVALID, "error", diag.path, diag.message, expected=diag.expected, actual=diag.actual)
            for diag in schema_diagnostics
        )
        proof_doc["diagnostics"] = [d.as_dict() for d in diagnostics]
        proof_doc["ok"] = False
    return proof_doc


def check_migration_spec(spec: dict[str, Any], registry: ContractRegistry, ctcp_root: pathlib.Path | None = None) -> dict[str, Any]:
    proof = build_migration_proof(spec, registry, ctcp_root)
    return {
        "kind": "MigrationReport",
        "migration_ref": ref_of(spec),
        "target_flow": spec.get("target", {}).get("flow"),
        "ok": proof["ok"],
        "diagnostics": proof["diagnostics"],
        "migration_proof": proof,
        "selected": selected_features(),
        "rejected": rejected_features(),
        "deferred": {k: v for k, v in SELECTED_FEATURES.items() if v.get("status") == "deferred"},
    }


def write_reports(report: dict[str, Any], output_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "migration_report.json"
    md_path = output_dir / "migration_report.md"
    proof_path = output_dir / "migration_proof.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown_report(report), encoding="utf-8")
    proof_path.write_text(json.dumps(report["migration_proof"], indent=2, ensure_ascii=False), encoding="utf-8")
    return json_path, md_path, proof_path


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [f"# Migration Report: {report['migration_ref']}", "", f"OK: {report['ok']}", "", "## Selected"]
    lines.extend(f"- {name}: {', '.join(row.get('maps_to', []))}" for name, row in report["selected"].items())
    lines.extend(["", "## Rejected"])
    lines.extend(f"- {name}: {row.get('reason', '')}" for name, row in report["rejected"].items())
    lines.extend(["", "## Diagnostics"])
    lines.extend(f"- {d['severity']} {d['code']} {d['path']}: {d['message']}" for d in report["diagnostics"])
    return "\n".join(lines) + "\n"


def _read_legacy_texts(ctcp_root: pathlib.Path, legacy_files: list[str]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for rel in legacy_files:
        path = ctcp_root / rel
        if path.exists() and path.is_file():
            try:
                texts[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                texts[rel] = ""
    return texts
