#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import subprocess
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
FROZEN_BOUNDARY_PATHS = (
    "scripts/repair_acceptance.py",
    "scripts/provider_jobs.py",
    "scripts/candidate_materializer.py",
    "tests/test_repair_acceptance.py",
    "tests/test_provider_job_partial_acceptance.py",
    "tests/test_kernel_contract.py",
    "benchmarks/project_generation_v1/cases.json",
)


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _tracked_changes(paths: tuple[str, ...]) -> list[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "HEAD", "--", *paths],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return sorted(line.strip().replace("\\", "/") for line in completed.stdout.splitlines() if line.strip())


def inspect() -> dict[str, Any]:
    failures: list[str] = []
    requirement = _text("scripts/requirement_decision_lane.py")
    pipeline = _text("scripts/run_local_pipeline_impl.py")
    delivery = _text("scripts/codex_conversation.py")
    schema = _text("contracts/product_design_depth_governance_v1.schema.json")
    registry = _text("docs/01_contract_registry.md")
    module = _text("scripts/product_design_depth_governance.py")

    checks = {
        "requirement_entry_freezes_contracts": "freeze_preimplementation_governance(" in requirement,
        "provider_receives_governance": '"product_design_governance": plan_doc.get(' in pipeline,
        "provider_core_proxy_rule": "MVP may reduce scope but may not replace the original core difficulty" in pipeline,
        "postbuild_maturity_before_packager": delivery.find("evaluate_and_write_project_reports(") < delivery.find("local_packager.package_project("),
        "public_gate_attaches_maturity": "attach_maturity_to_delivery_gate" in delivery,
        "public_summary_discloses_goal_status": "原始目标已验证" in delivery,
        "single_maturity_evaluator": delivery.count("evaluate_and_write_project_reports(") == 1,
        "schema_has_all_maturity_levels": all(level in schema for level in ("DEMO", "PROTOTYPE", "FUNCTIONAL_MVP", "TARGET_VALIDATED", "PRODUCTION_READY")),
        "registry_declares_no_authority": "do not themselves grant a formal `EvidenceStatus`" in registry,
        "synthetic_only_is_not_target_evidence": "synthetic_only_acceptance" in module and "required_real_world_evidence" in module,
        "independent_holdout_hash_is_bound": "contracted_resource_hashes.issubset(evidenced_resource_hashes)" in module,
        "frozen_boundary_unchanged": not _tracked_changes(FROZEN_BOUNDARY_PATHS),
    }
    for name, passed in checks.items():
        if not passed:
            failures.append(name)
    return {
        "kind": "CGKNProductDesignDepthRuleGuard",
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "frozen_boundary_paths": list(FROZEN_BOUNDARY_PATHS),
        "frozen_boundary_changes": _tracked_changes(FROZEN_BOUNDARY_PATHS),
        "provider_calls": 0,
    }


def main() -> int:
    result = inspect()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
