#!/usr/bin/env python3
from __future__ import annotations

import ast
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
    "docs/62_agent_failure_routing_cheatsheet.md",
    "docs/agent_test_integrated_behavior.md",
    "docs/continuous_verified_generation_loop.md",
    "docs/release_candidate_acceptance.md",
    "EDITION.md",
    "TEST_E2E_REPORT.md",
    "WORKTREE_AUDIT.md",
    "test_e2e_service.py",
    "START_QWEN_L1_SMOKE.ps1",
    "CHECK_QWEN_L1_SMOKE.ps1",
    "demo_auto_generation.py",
    "detected_entrypoints.md",
    "run_function_stress_pass.py",
    "run_pass2_operational_closure.py",
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
    "scripts/agent_long_run_evaluator.py",
    "scripts/agent_long_run_trace_bundle.py",
    "scripts/run_agent_led_verify.py",
    "scripts/run_agent_led_generalization_benchmark.py",
    "scripts/run_large_project_agent_led_benchmark.py",
    "scripts/run_long_agent_led_stability_test.py",
    "scripts/run_complexity_scale_benchmark.py",
    "scripts/run_complexity_scale_workbench_benchmark.py",
    "scripts/run_quick_large_sync_tree_benchmark.py",
    "scripts/run_agent_autonomous_diagnosis.py",
    "scripts/run_agent_fault_injection_suite.py",
    "scripts/agent_problem_classifier.py",
    "scripts/continuous_generation_ledger.py",
    "scripts/run_continuous_verified_generation.py",
    "scripts/release_candidate_gate.py",
    "scripts/run_live_project_regression.py",
    "benchmarks/project_generation_v1",
    "benchmarks/orbit_360_workbench",
    "tests/test_project_generation_benchmark_v1.py",
    "tests/test_failure_to_repair.py",
    "tests/test_trimmed_case_debug.py",
    "tests/test_external_api_dependency_policy.py",
    "tests/test_adaptive_autonomous_validation.py",
    "tests/test_autonomous_validation_pass3.py",
    "tests/test_function_stress_runner.py",
    "tests/test_pass2_operational_closure.py",
    "tests/test_pass6_latency_audit.py",
    "tests/test_pass6_long_horizon.py",
    "tests/test_real_workload_recovery_stress.py",
    "tests/test_role_driven_validation.py",
    "tests/test_role_driven_validation_pass2.py",
    "tests/test_dynamic_agent_tree_growth_eval.py",
    "tests/test_dynamic_agent_tree_long_run_eval.py",
    "tests/test_agent_led_generalization_benchmark.py",
    "tests/test_large_project_agent_led_benchmark.py",
    "tests/test_long_agent_led_stability_test.py",
    "tests/test_verify_repo_agent_led_mode.py",
    "tests/test_complexity_scale_benchmark.py",
    "tests/test_quick_large_sync_tree_benchmark.py",
    "tests/test_sync_tree_growth_audit.py",
    "tests/test_agent_autonomous_diagnosis.py",
    "tests/test_agent_fault_injection_suite.py",
    "tests/test_agent_diagnosis_report_schema.py",
    "tests/test_agent_problem_classifier.py",
    "tests/test_agent_test_integrated_behavior.py",
    "tests/test_continuous_verified_generation.py",
    "tests/test_release_candidate_gate.py",
    "schemas/adaptive_autonomous_validation_report_v1.schema.json",
    "schemas/autonomous_validation_pass3_report_v1.schema.json",
    "schemas/role_driven_validation_pass2_report_v1.schema.json",
    "schemas/role_driven_validation_report_v1.schema.json",
}

FORBIDDEN_ACTIVE_PREFIXES = {
    "scripts/agent_tree_",
    "tests/test_agent_tree_",
    "scripts/agent_growth_",
    "tests/test_agent_growth_",
    "scripts/agent_pruning_",
    "tests/test_agent_pruning_",
    "scripts/agent_director_",
    "tests/test_agent_director_",
}

FORBIDDEN_IMPORT_PREFIXES = {
    "benchmarks.project_generation_v1",
    "scripts.adaptive_autonomous_validation",
    "scripts.autonomous_validation_pass3",
    "scripts.role_driven_validation",
    "scripts.role_driven_validation_pass2",
    "adaptive_autonomous_validation",
    "autonomous_validation_pass3",
    "role_driven_validation",
    "role_driven_validation_pass2",
    "scripts.agent_tree_",
    "agent_tree_",
    "scripts.agent_growth_",
    "agent_growth_",
    "scripts.agent_pruning_",
    "agent_pruning_",
    "scripts.agent_director_loop",
    "agent_director_loop",
    "scripts.agent_decision_ledger",
    "agent_decision_ledger",
    "scripts.agent_state_observer",
    "agent_state_observer",
    "scripts.agent_tool_registry",
    "agent_tool_registry",
    "scripts.agent_problem_classifier",
    "agent_problem_classifier",
    "scripts.continuous_generation_ledger",
    "continuous_generation_ledger",
    "scripts.release_candidate_gate",
    "release_candidate_gate",
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _imports(path: pathlib.Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return set()
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def _active_python_files() -> list[pathlib.Path]:
    ignored = {".git", ".venv", "venv", "__pycache__", "legacy", "generated", "artifacts", "runs"}
    return [
        path
        for path in ROOT.rglob("*.py")
        if not any(part in ignored for part in path.relative_to(ROOT).parts)
    ]


def _forbidden_import(imported: str) -> bool:
    return any(imported == prefix or imported.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES)


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

    for path in _active_python_files():
        relative = path.relative_to(ROOT).as_posix()
        if any(relative.startswith(prefix) for prefix in FORBIDDEN_ACTIVE_PREFIXES):
            errors.append(f"obsolete_active_prefix:{relative}")
        for imported in _imports(path):
            if _forbidden_import(imported):
                errors.append(f"obsolete_active_import:{relative}:{imported}")

    fast_ci_path = ROOT / ".github" / "workflows" / "repository-fast-ci.yml"
    if not fast_ci_path.is_file():
        errors.append("missing_repository_fast_ci")
    else:
        fast_ci = fast_ci_path.read_text(encoding="utf-8", errors="replace")
        if "release_candidate_gate" in fast_ci or "commercial_readiness" in fast_ci:
            errors.append("fast_ci_contains_pre_mvp_readiness_authority")

    for path in (
        "cgkn/component/spec.py",
        "cgkn/component/ports.py",
        "cgkn/orchestration/capability_tree.py",
        "cgkn/orchestration/execution_dag.py",
        "benchmarks/mvp_decision_efficiency/README.md",
    ):
        if not (ROOT / path).is_file():
            errors.append(f"missing_mvp_core:{path}")
    return sorted(set(errors))


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
