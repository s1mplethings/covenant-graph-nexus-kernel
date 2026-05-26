from __future__ import annotations

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
