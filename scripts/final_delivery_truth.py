#!/usr/bin/env python3
from __future__ import annotations

import pathlib
from typing import Any

try:
    import artifact_integrity
    import formal_model_contract
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import artifact_integrity
    from scripts import formal_model_contract
    from scripts.pipeline_contracts import base_result


def evaluate(project_dir: pathlib.Path, manifest: dict[str, Any] | None = None, session: dict[str, Any] | None = None, *, evidence: dict[str, Any] | None = None, phase: str = "final") -> dict[str, Any]:
    import codex_conversation as bridge

    project = pathlib.Path(project_dir)
    if (project / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").exists():
        return base_result(
            status="fail",
            verdict="final_delivery_rejected",
            blockers=["candidate project cannot pass final delivery"],
            metadata={"delivery_allowed": False, "phase": phase},
        )
    gate = bridge.evaluate_public_delivery_gate(project, manifest or {}, session or {}, evidence=evidence, phase=phase)
    integrity = artifact_integrity.validate_final_package(project, project / "final_project_bundle.zip", project / "delivery_manifest.json")
    evidence_doc = evidence or {}
    run_dir = evidence_doc.get("run_dir") or (manifest or {}).get("run_dir") or (session or {}).get("run_dir") or project
    usage_plan = evidence_doc.get("usage_plan")
    if not isinstance(usage_plan, dict):
        usage_plan_path = pathlib.Path(str(run_dir)) / "agent_usage" / "usage_plan.json"
        if usage_plan_path.exists():
            try:
                import json

                usage_plan = json.loads(usage_plan_path.read_text(encoding="utf-8"))
            except Exception:
                usage_plan = {}
        else:
            usage_plan = {}
    model_gate = formal_model_contract.evaluate_model_participation(
        context="formal_live_generation" if phase == "final" else "delivery_candidate_generation",
        run_dir=run_dir,
        usage_plan=usage_plan,
    )
    allowed = bool(gate.get("delivery_allowed")) and integrity.get("status") == "pass" and model_gate.get("status") == "pass"
    return base_result(
        status="pass" if allowed else "fail",
        verdict="final_delivery_allowed" if allowed else "final_delivery_rejected",
        blockers=list(gate.get("missing", [])) + list(integrity.get("blockers", [])) + ([] if model_gate.get("status") == "pass" else [str(model_gate.get("reason", "FORMAL_MODEL_EVIDENCE_MISSING"))]),
        metadata={"delivery_allowed": allowed, "public_final_gate": gate, "integrity": integrity, "formal_model_gate": model_gate},
    )


def run_if_applicable(**kwargs: Any) -> dict[str, Any]:
    return evaluate(**kwargs)


def contract() -> dict[str, Any]:
    return base_result(
        status="pass",
        verdict="truth_module",
        metadata={
            "responsibilities": [
                "final_project_bundle.zip truth",
                "delivery_manifest.json truth",
                "final public delivery gate",
                "fake final artifact rejection",
                "candidate cannot be final",
            ],
            "replaceable": False,
        },
    )
