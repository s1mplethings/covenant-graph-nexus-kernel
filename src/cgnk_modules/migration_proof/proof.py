from __future__ import annotations

import pathlib
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_MIGRATION_ENTRYPOINT_MISSING,
    CGNK_MIGRATION_LEGACY_FILE_MISSING,
    CGNK_MIGRATION_PRESERVE_CONSTRAINT_MISSING,
    CGNK_MIGRATION_REQUIRED_ARTIFACT_MISSING,
    CGNK_MIGRATION_REQUIRED_SCHEMA_MISSING,
    CGNK_MIGRATION_REQUIRED_TEST_MISSING,
    CGNK_MIGRATION_TARGET_ARTIFACT_MISSING,
    CGNK_MIGRATION_TARGET_FLOW_MISSING,
    CGNK_MIGRATION_TARGET_MODULE_MISSING,
    Diagnostic,
)
from cgnk_core.refs import ref_of

REQUIRED_PRESERVE = {
    "cli_args",
    "summary_json_schema",
    "benchmark_report_format",
    "provider_call_semantics",
}


def build_migration_proof(
    migration_spec: dict[str, Any],
    ctcp_root: str | pathlib.Path | None = None,
    compile_result: dict[str, Any] | None = None,
    feature_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    legacy = migration_spec.get("legacy", {}) if isinstance(migration_spec, dict) else {}
    target = migration_spec.get("target", {}) if isinstance(migration_spec, dict) else {}
    proof_spec = migration_spec.get("proof", {}) if isinstance(migration_spec, dict) else {}
    preserve = {key for key, value in migration_spec.get("preserve", {}).items() if value} if isinstance(migration_spec, dict) else set()
    legacy_files = list(legacy.get("files", []))
    public_entrypoints = list(legacy.get("public_entrypoints", legacy.get("entrypoints", [])))

    legacy_evidence = []
    entrypoint_evidence = []
    if ctcp_root is not None:
        root = pathlib.Path(ctcp_root)
        readable_texts: dict[str, str] = {}
        for rel in legacy_files:
            path = root / rel
            exists = path.is_file()
            legacy_evidence.append({"path": rel, "exists": exists})
            if exists:
                readable_texts[rel] = path.read_text(encoding="utf-8", errors="replace")
            else:
                diagnostics.append(Diagnostic(CGNK_MIGRATION_LEGACY_FILE_MISSING, "error", f"$.legacy.files[{rel}]", "Legacy file is missing", expected="file under ctcp_root", actual=rel, involved_ref=rel))
        for entrypoint in public_entrypoints:
            locations = [rel for rel, text in readable_texts.items() if entrypoint in text]
            entrypoint_evidence.append({"entrypoint": entrypoint, "locations": locations})
            if not locations:
                diagnostics.append(Diagnostic(CGNK_MIGRATION_ENTRYPOINT_MISSING, "error", f"$.legacy.public_entrypoints[{entrypoint}]", "Legacy public entrypoint is missing", expected="entrypoint text in legacy files", actual=entrypoint, involved_ref=entrypoint))
    else:
        legacy_evidence = [{"path": rel, "exists": None} for rel in legacy_files]
        entrypoint_evidence = [{"entrypoint": entrypoint, "locations": []} for entrypoint in public_entrypoints]

    if compile_result is not None:
        if target.get("flow") and compile_result.get("flow_ref") != target.get("flow"):
            diagnostics.append(Diagnostic(CGNK_MIGRATION_TARGET_FLOW_MISSING, "error", "$.target.flow", "Compile result does not match target flow", expected=target.get("flow"), actual=compile_result.get("flow_ref"), involved_ref=target.get("flow")))
        resolved_modules = set(compile_result.get("symbol_table", {}).get("modules", []) or compile_result.get("compiled_bundle", {}).get("symbols", {}).get("modules", []))
        for module_ref in target.get("modules", []):
            if resolved_modules and module_ref not in resolved_modules:
                diagnostics.append(Diagnostic(CGNK_MIGRATION_TARGET_MODULE_MISSING, "error", "$.target.modules", "Target module not present in compile context", expected=module_ref, actual=sorted(resolved_modules), involved_ref=module_ref))
        resolved_artifacts = set(compile_result.get("resolved_artifacts", []))
        for artifact_ref in target.get("artifacts", []):
            if resolved_artifacts and artifact_ref not in resolved_artifacts:
                diagnostics.append(Diagnostic(CGNK_MIGRATION_TARGET_ARTIFACT_MISSING, "error", "$.target.artifacts", "Target artifact not present in compile context", expected=artifact_ref, actual=sorted(resolved_artifacts), involved_ref=artifact_ref))

    for key in sorted(REQUIRED_PRESERVE - preserve):
        diagnostics.append(Diagnostic(CGNK_MIGRATION_PRESERVE_CONSTRAINT_MISSING, "warning", f"$.preserve.{key}", "Required preserve constraint is not declared", expected=True, actual=False, involved_ref=key))
    if not proof_spec.get("required_tests"):
        diagnostics.append(Diagnostic(CGNK_MIGRATION_REQUIRED_TEST_MISSING, "error", "$.proof.required_tests", "Migration proof requires declared tests", expected="non-empty required_tests", actual=proof_spec.get("required_tests")))
    if not proof_spec.get("required_artifacts"):
        diagnostics.append(Diagnostic(CGNK_MIGRATION_REQUIRED_ARTIFACT_MISSING, "error", "$.proof.required_artifacts", "Migration proof requires declared artifacts", expected="non-empty required_artifacts", actual=proof_spec.get("required_artifacts")))
    if "summary_json_schema" in preserve and not proof_spec.get("required_schemas"):
        diagnostics.append(Diagnostic(CGNK_MIGRATION_REQUIRED_SCHEMA_MISSING, "error", "$.proof.required_schemas", "Schema preservation requires declared schemas", expected="non-empty required_schemas", actual=proof_spec.get("required_schemas")))

    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    return {
        "kind": "MigrationProof",
        "schema_version": "1",
        "migration_ref": _migration_ref(migration_spec),
        "target_flow": target.get("flow", ""),
        "preserved_constraints": sorted(preserve),
        "evidence": {
            "legacy_files": legacy_evidence,
            "public_entrypoints": entrypoint_evidence,
            "target_modules": sorted(target.get("modules", [])),
            "target_artifacts": sorted(target.get("artifacts", [])),
            "required_tests": sorted(proof_spec.get("required_tests", [])),
            "required_artifacts": sorted(proof_spec.get("required_artifacts", [])),
            "required_schemas": sorted(proof_spec.get("required_schemas", [])),
            "feature_map": feature_map.get("id") if isinstance(feature_map, dict) else None,
        },
        "diagnostics": diagnostic_dicts,
        "ok": not any(row["severity"] == "error" for row in diagnostic_dicts),
    }


def _migration_ref(spec: dict[str, Any]) -> str:
    try:
        return ref_of(spec)
    except Exception:
        return "migration.unknown@1"
