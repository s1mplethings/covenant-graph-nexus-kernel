#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED_INVARIANTS = {f"INV-{index:02d}" for index in range(1, 11)}

FORBIDDEN_ACTIVE_PATHS = {
    "docs/06_agent_led_layered_architecture.md",
    "docs/requirement_decision_first.md",
    "docs/requirement_decision_lane.md",
    "docs/77_decomposition_tree_mainline.md",
    "docs/78_role_driven_autonomous_validation.md",
    "docs/79_role_driven_validation_pass2.md",
    "docs/80_autonomous_validation_pass3.md",
    "docs/81_adaptive_autonomous_validation.md",
    "docs/82_autonomous_project_acceptance_integration.md",
    "START_QWEN_L1_SMOKE.ps1",
    "CHECK_QWEN_L1_SMOKE.ps1",
    "scripts/RUN_QWEN_L1_SMOKE_WORKER.ps1",
    "scripts/run_function_stress_pass.py",
    "scripts/run_pass2_operational_closure.py",
    "scripts/run_pass3_regression.py",
    "scripts/run_pass6_latency_audit.py",
    "scripts/run_pass6_long_horizon.py",
    "scripts/run_real_workload_recovery_stress.py",
    "scripts/role_driven_validation.py",
    "scripts/role_driven_validation_pass2.py",
    "scripts/autonomous_validation_pass3.py",
    "scripts/adaptive_autonomous_validation.py",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check() -> list[str]:
    errors: list[str] = []
    for path in ("PRODUCT_GOAL.md", "MVP_SCOPE.md", "governance/product_invariants.json"):
        if not (ROOT / path).is_file():
            errors.append(f"missing_product_authority:{path}")
    if errors:
        return errors

    product = _read("PRODUCT_GOAL.md")
    scope = _read("MVP_SCOPE.md")
    if "Capability Tree" not in product or "Tree-to-DAG" not in product:
        errors.append("product_goal_missing_capability_tree_mainline")
    if "high-capability Agent" not in product:
        errors.append("product_goal_missing_agent_decision_authority")
    if "Provider-owned project planning" not in scope:
        errors.append("mvp_scope_missing_provider_planning_exclusion")

    invariants = json.loads(_read("governance/product_invariants.json"))
    ids = {
        str(item.get("id", ""))
        for item in invariants.get("invariants", [])
        if isinstance(item, dict)
    }
    if ids != REQUIRED_INVARIANTS:
        errors.append("product_invariants_identity_mismatch")

    architecture = json.loads(_read("governance/current_architecture.json"))
    if architecture.get("architecture_generation") != "capability-tree-mvp":
        errors.append("current_architecture_not_capability_tree_mvp")

    for path in sorted(FORBIDDEN_ACTIVE_PATHS):
        if (ROOT / path).exists():
            errors.append(f"obsolete_active_path:{path}")

    for path in (
        "cgkn/component/spec.py",
        "cgkn/component/ports.py",
        "cgkn/orchestration/capability_tree.py",
        "cgkn/orchestration/execution_dag.py",
    ):
        if not (ROOT / path).is_file():
            errors.append(f"missing_mvp_core:{path}")
    return errors


def main() -> int:
    errors = check()
    print(json.dumps({
        "kind": "CGKNProductDirectionGate",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
