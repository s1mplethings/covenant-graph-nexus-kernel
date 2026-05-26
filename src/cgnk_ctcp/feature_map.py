from __future__ import annotations

import pathlib
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_FEATURE_DUPLICATE,
    CGNK_FEATURE_ENTRYPOINT_MISSING,
    CGNK_FEATURE_LEGACY_FILE_MISSING,
    CGNK_FEATURE_MAP_INVALID,
    CGNK_FEATURE_MIGRATION_SPEC_MISSING,
    CGNK_FEATURE_TARGET_ARTIFACT_MISSING,
    CGNK_FEATURE_TARGET_FLOW_MISSING,
    CGNK_FEATURE_TARGET_MODULE_MISSING,
    Diagnostic,
)
from cgnk_core.registry import ContractRegistry
from cgnk_core.schema_loader import load_json

SELECTED_FEATURES = {
    "project_generation_pipeline": {
        "status": "selected",
        "maps_to": ["flow.project_generation@1", "module.plan.generate.provider@1"],
    },
    "artifact_evidence": {
        "status": "selected",
        "maps_to": ["artifact.validation_report@1", "artifact.benchmark_report@1"],
    },
    "provider_capability_boundary": {
        "status": "selected",
        "maps_to": ["policy.safe_project_generation@1", "policy.safe_project_refactor@1"],
    },
    "graph_edit_recomposition": {
        "status": "selected",
        "maps_to": ["GraphEditProposal"],
    },
    "decision_gate": {
        "status": "selected",
        "maps_to": ["module.decision.gate@1"],
    },
    "contract_arena": {
        "status": "selected",
        "maps_to": ["module.design.arena@1"],
    },
    "strong_intent_burst": {
        "status": "selected",
        "maps_to": ["module.intent.expand@1"],
    },
    "verify_hygiene": {
        "status": "selected",
        "maps_to": ["module.runtime.validate@1"],
    },
    "migration_spec": {
        "status": "selected",
        "maps_to": ["migration.project_generation@1"],
    },
    "benchmark_proof_shape": {
        "status": "selected",
        "maps_to": ["artifact.benchmark_report@1"],
    },
    "old_telegram_bot_main_flow": {"status": "rejected", "reason": "legacy runtime path"},
    "old_progress_fallback": {"status": "rejected", "reason": "legacy fallback behavior"},
    "old_public_delivery_sanitizer": {"status": "rejected", "reason": "rebuild as contract-only public.send.guard"},
    "old_monolithic_orchestrator": {"status": "rejected", "reason": "violates module contracts"},
    "legacy_outbox_questions_primary_flow": {"status": "rejected", "reason": "legacy support path"},
}


def selected_features() -> dict[str, dict]:
    return {k: v for k, v in SELECTED_FEATURES.items() if v["status"] == "selected"}


def rejected_features() -> dict[str, dict]:
    return {k: v for k, v in SELECTED_FEATURES.items() if v["status"] == "rejected"}


def load_feature_map(path: pathlib.Path) -> dict[str, Any]:
    return load_json(path)


def check_feature_map(spec: dict[str, Any], registry: ContractRegistry, ctcp_root: pathlib.Path | None = None) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    schema_diagnostics = registry.schema_loader.validate(spec, "ctcp_feature_map.schema.json", "$.feature_map")
    diagnostics.extend(
        Diagnostic(CGNK_FEATURE_MAP_INVALID, "error", d.path, d.message, expected=d.expected, actual=d.actual)
        for d in schema_diagnostics
    )

    seen: set[str] = set()
    valid_targets = 0
    features = spec.get("features", [])
    for index, feature in enumerate(features):
        path = f"$.features[{index}]"
        feature_id = feature.get("id", "")
        if feature_id in seen:
            diagnostics.append(Diagnostic(CGNK_FEATURE_DUPLICATE, "error", f"{path}.id", "Feature id is duplicated", actual=feature_id, involved_ref=feature_id))
        seen.add(feature_id)

        target_ok = True
        migration_ref = feature.get("migration")
        if migration_ref and migration_ref not in registry.migration_specs:
            target_ok = False
            diagnostics.append(Diagnostic(CGNK_FEATURE_MIGRATION_SPEC_MISSING, "error", f"{path}.migration", "Referenced migration spec is missing", expected="known migration ref", actual=migration_ref, involved_ref=migration_ref))

        target = feature.get("target", {})
        flow_ref = target.get("flow")
        if flow_ref and registry.resolve_flow(flow_ref) is None:
            target_ok = False
            diagnostics.append(Diagnostic(CGNK_FEATURE_TARGET_FLOW_MISSING, "error", f"{path}.target.flow", "Target flow is missing", expected="known flow ref", actual=flow_ref, involved_ref=flow_ref))
        for module_ref in target.get("modules", []):
            if registry.resolve_module(module_ref) is None:
                target_ok = False
                diagnostics.append(Diagnostic(CGNK_FEATURE_TARGET_MODULE_MISSING, "error", f"{path}.target.modules", "Target module is missing", expected="known module ref", actual=module_ref, involved_ref=module_ref))
        for artifact_ref in target.get("artifacts", []):
            if registry.resolve_artifact(artifact_ref) is None:
                target_ok = False
                diagnostics.append(Diagnostic(CGNK_FEATURE_TARGET_ARTIFACT_MISSING, "error", f"{path}.target.artifacts", "Target artifact is missing", expected="known artifact ref", actual=artifact_ref, involved_ref=artifact_ref))

        if ctcp_root is not None:
            legacy = feature.get("legacy", {})
            readable_texts: dict[str, str] = {}
            for rel in legacy.get("files", []):
                legacy_path = ctcp_root / rel
                if not legacy_path.is_file():
                    diagnostics.append(Diagnostic(CGNK_FEATURE_LEGACY_FILE_MISSING, "error", f"{path}.legacy.files", "Legacy feature file is missing", expected="file under --ctcp-root", actual=rel, involved_ref=feature_id))
                    continue
                readable_texts[rel] = legacy_path.read_text(encoding="utf-8", errors="replace")
            for entrypoint in legacy.get("entrypoints", []):
                locations = [rel for rel, text in readable_texts.items() if entrypoint in text]
                if not locations:
                    diagnostics.append(Diagnostic(CGNK_FEATURE_ENTRYPOINT_MISSING, "error", f"{path}.legacy.entrypoints", "Legacy feature entrypoint is missing", expected="entrypoint text in legacy files", actual=entrypoint, involved_ref=feature_id))

        if target_ok:
            valid_targets += 1

    by_status: dict[str, int] = {}
    for feature in features:
        status = feature.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    diagnostic_dicts = [d.as_dict() for d in diagnostics]
    return {
        "kind": "CTCPFeatureMapReport",
        "ok": not any(d["severity"] == "error" for d in diagnostic_dicts),
        "features_total": len(features),
        "features_by_status": by_status,
        "features_with_valid_targets": valid_targets,
        "diagnostics": diagnostic_dicts,
    }
