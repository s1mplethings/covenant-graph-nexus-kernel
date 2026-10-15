#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED_INVARIANTS = {f"INV-{index:02d}" for index in range(1, 11)}
BOUNDARY_STATUS = "CLEANUP_COMPLETE_FEATURE_IMPLEMENTATION_REQUIRED"
RUNTIME_WIRING_STATUS = "NOT_IMPLEMENTED"

FORBIDDEN_ACTIVE_PATHS = {
    "docs/00_product_studio_contract.md",
    "docs/01_virtual_team_contract.md",
    "docs/02_product_story_contract.md",
    "docs/03_execution_flow.md",
    "docs/04_acceptance_and_evidence.md",
    "docs/05_agent_operating_contract.md",
    "docs/06_agent_led_layered_architecture.md",
    "docs/62_agent_failure_routing_cheatsheet.md",
    "docs/70_commercial_hardening_plan.md",
    "docs/71_commercial_readiness_gate.md",
    "docs/77_decomposition_tree_mainline.md",
    "docs/78_role_driven_autonomous_validation.md",
    "docs/79_role_driven_validation_pass2.md",
    "docs/80_autonomous_validation_pass3.md",
    "docs/81_adaptive_autonomous_validation.md",
    "docs/82_autonomous_project_acceptance_integration.md",
    "docs/agent_test_integrated_behavior.md",
    "docs/continuous_verified_generation_loop.md",
    "docs/customer_agent_long_journey_trial.md",
    "docs/release_candidate_acceptance.md",
    "docs/requirement_decision_first.md",
    "docs/requirement_decision_lane.md",
    "implementation_plan/CGNK_PHASED_IMPLEMENTATION_PLAN.md",
    "implementation_plan/LONG_CONTEXT_STATE_PROCESS.md",
    "implementation_plan/MODULAR_PROJECT_GENERATION_PROCESS.md",
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
    "benchmarks/project_generation_v1",
    "benchmarks/orbit_360_workbench",
    "scripts/RUN_QWEN_L1_SMOKE_WORKER.ps1",
    "scripts/check_product_studio_contract.py",
    "scripts/agent_long_run_evaluator.py",
    "scripts/agent_long_run_trace_bundle.py",
    "scripts/agent_problem_classifier.py",
    "scripts/adaptive_autonomous_validation.py",
    "scripts/autonomous_validation_pass3.py",
    "scripts/commercial_promotion_gate.py",
    "scripts/commercial_ready_gate.py",
    "scripts/commercial_warning_policy.py",
    "scripts/continuous_generation_ledger.py",
    "scripts/customer_agent_scorecard.py",
    "scripts/customer_agent_simulator.py",
    "scripts/generalization_benchmark_audit.py",
    "scripts/large_project_complexity_audit.py",
    "scripts/release_candidate_gate.py",
    "scripts/rerun_case01_case03_product_convergence.py",
    "scripts/role_driven_validation.py",
    "scripts/role_driven_validation_pass2.py",
    "scripts/run_acfv_scale_benchmark.py",
    "scripts/run_agent_autonomous_diagnosis.py",
    "scripts/run_agent_fault_injection_suite.py",
    "scripts/run_agent_led_generalization_benchmark.py",
    "scripts/run_agent_led_verify.py",
    "scripts/run_candidate_smoke_benchmark.py",
    "scripts/run_canonical_textcounter_smoke.ps1",
    "scripts/run_commercial_readiness.py",
    "scripts/run_complexity_scale_benchmark.py",
    "scripts/run_complexity_scale_workbench_benchmark.py",
    "scripts/run_continuous_verified_generation.py",
    "scripts/run_customer_agent_long_journey_trial.py",
    "scripts/run_formal_live_delivery_closure.py",
    "scripts/run_full_dynamic_real_project_eval.py",
    "scripts/run_function_stress_pass.py",
    "scripts/run_general_requirement_compiler_smokes.py",
    "scripts/run_large_project_agent_led_benchmark.py",
    "scripts/run_live_project_regression.py",
    "scripts/run_long_agent_led_stability_test.py",
    "scripts/run_mixed_backend_branch_phase.py",
    "scripts/run_pass2_operational_closure.py",
    "scripts/run_pass3_regression.py",
    "scripts/run_pass6_latency_audit.py",
    "scripts/run_pass6_long_horizon.py",
    "scripts/run_product_design_depth_governance_acceptance.py",
    "scripts/run_provider_failure_boundary.py",
    "scripts/run_quick_large_sync_tree_benchmark.py",
    "scripts/run_real_provider_frontend_branch_phase.py",
    "scripts/run_real_provider_leaf_phase.py",
    "scripts/run_real_workload_recovery_stress.py",
    "scripts/run_reference_answer_project_trial.py",
    "scripts/run_requirement_decision_benchmark.py",
    "scripts/run_test_profile.py",
    "scripts/run_vn_real_provider_e2e.py",
    "scripts/verify_repo.ps1",
    "scripts/write_canonical_finalization_acceptance_reports.py",
    "scripts/write_general_requirement_compiler_reports.py",
    "tests/test_adaptive_autonomous_validation.py",
    "tests/test_agent_autonomous_diagnosis.py",
    "tests/test_agent_diagnosis_report_schema.py",
    "tests/test_agent_fault_injection_suite.py",
    "tests/test_agent_led_generalization_benchmark.py",
    "tests/test_agent_problem_classifier.py",
    "tests/test_agent_test_integrated_behavior.py",
    "tests/test_autonomous_validation_pass3.py",
    "tests/test_backend_large_project_generation_eval.py",
    "tests/test_commercial_promotion_gate.py",
    "tests/test_commercial_readiness.py",
    "tests/test_commercial_ready_gate.py",
    "tests/test_commercial_warning_policy.py",
    "tests/test_complexity_scale_benchmark.py",
    "tests/test_continuous_verified_generation.py",
    "tests/test_customer_agent_long_journey_trial.py",
    "tests/test_dynamic_agent_tree_growth_eval.py",
    "tests/test_dynamic_agent_tree_long_run_eval.py",
    "tests/test_external_api_dependency_policy.py",
    "tests/test_failure_to_repair.py",
    "tests/test_full_dynamic_real_project_eval.py",
    "tests/test_full_dynamic_real_project_scope_injection.py",
    "tests/test_full_dynamic_real_project_trace_bundle.py",
    "tests/test_function_stress_runner.py",
    "tests/test_large_project_agent_led_benchmark.py",
    "tests/test_long_agent_led_stability_test.py",
    "tests/test_mixed_backend_branch_phase.py",
    "tests/test_mixed_backend_branch_scope_violation.py",
    "tests/test_mixed_backend_branch_trace_bundle.py",
    "tests/test_pass2_operational_closure.py",
    "tests/test_pass6_latency_audit.py",
    "tests/test_pass6_long_horizon.py",
    "tests/test_product_studio_contract.py",
    "tests/test_product_studio_discipline.py",
    "tests/test_project_generation_benchmark_v1.py",
    "tests/test_provider_failure_boundary.py",
    "tests/test_quick_large_provider_readiness_probe.py",
    "tests/test_quick_large_sync_tree_benchmark.py",
    "tests/test_real_provider_frontend_branch_phase.py",
    "tests/test_real_provider_frontend_branch_scope_violation.py",
    "tests/test_real_provider_frontend_branch_trace_bundle.py",
    "tests/test_real_provider_large_project_delivery_eval.py",
    "tests/test_real_provider_leaf_phase_resume.py",
    "tests/test_real_workload_recovery_stress.py",
    "tests/test_reference_answer_project_trial.py",
    "tests/test_release_candidate_gate.py",
    "tests/test_rerun_case01_case03_product_convergence.py",
    "tests/test_role_driven_validation.py",
    "tests/test_role_driven_validation_pass2.py",
    "tests/test_run_test_profile.py",
    "tests/test_run_vn_real_provider_e2e.py",
    "tests/test_start_control_model_semantics_real_provider_eval.py",
    "tests/test_sync_tree_growth_audit.py",
    "tests/test_trimmed_case_debug.py",
    "tests/test_verify_repo_agent_led_mode.py",
    "schemas/adaptive_autonomous_validation_report_v1.schema.json",
    "schemas/autonomous_validation_pass3_report_v1.schema.json",
    "schemas/decision_ledger.v1.schema.json",
    "schemas/product_studio_run.schema.json",
    "schemas/project_generation_benchmark_case_v1.schema.json",
    "schemas/project_generation_benchmark_report_v1.schema.json",
    "schemas/role_driven_validation_pass2_report_v1.schema.json",
    "schemas/role_driven_validation_report_v1.schema.json"
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
    "scripts/commercial_",
    "tests/test_commercial_",
    "scripts/customer_agent_",
    "tests/test_customer_agent_"
}

FORBIDDEN_IMPORT_PREFIXES = {
    "benchmarks.project_generation_v1",
    "scripts.check_product_studio_contract",
    "check_product_studio_contract",
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
    "release_candidate_gate"
}


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _read_json(path: str) -> dict[str, object]:
    return json.loads(_read(path))


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
    required_authority = (
        "PRODUCT_GOAL.md",
        "MVP_SCOPE.md",
        "README.md",
        "governance/product_invariants.json",
        "governance/current_architecture.json",
        "governance/mvp_cleanup_boundary.json",
        "docs/MVP_RUNTIME_MIGRATION_BOUNDARY.md"
    )
    for path in required_authority:
        if not (ROOT / path).is_file():
            errors.append(f"missing_product_authority:{path}")
    if errors:
        return sorted(set(errors))

    product = _read("PRODUCT_GOAL.md")
    scope = _read("MVP_SCOPE.md")
    readme = _read("README.md")
    if "Capability Tree" not in product or "Tree-to-DAG" not in product:
        errors.append("product_goal_missing_capability_tree_mainline")
    if "high-capability Agent" not in product:
        errors.append("product_goal_missing_agent_decision_authority")
    if "Provider-owned project planning" not in scope:
        errors.append("mvp_scope_missing_provider_planning_exclusion")
    if "not yet wired into the default project runtime" not in readme:
        errors.append("readme_overstates_runtime_wiring")

    invariants = _read_json("governance/product_invariants.json")
    ids = {
        str(item.get("id", ""))
        for item in invariants.get("invariants", [])
        if isinstance(item, dict)
    }
    if ids != REQUIRED_INVARIANTS:
        errors.append("product_invariants_identity_mismatch")

    architecture = _read_json("governance/current_architecture.json")
    if architecture.get("architecture_generation") != "capability-tree-mvp":
        errors.append("current_architecture_not_capability_tree_mvp")
    implementation_state = architecture.get("implementation_state", {})
    if not isinstance(implementation_state, dict) or implementation_state.get("runtime_wiring") != RUNTIME_WIRING_STATUS:
        errors.append("current_architecture_runtime_wiring_misreported")

    boundary = _read_json("governance/mvp_cleanup_boundary.json")
    if boundary.get("status") != BOUNDARY_STATUS:
        errors.append("cleanup_boundary_status_mismatch")
    if boundary.get("current_runtime_wiring") != RUNTIME_WIRING_STATUS:
        errors.append("cleanup_boundary_runtime_wiring_mismatch")
    if boundary.get("functional_readiness") != "NOT_EVALUATED":
        errors.append("cleanup_boundary_overstates_functional_readiness")

    compatibility_entrypoints = boundary.get("compatibility_entrypoints", [])
    if not isinstance(compatibility_entrypoints, list) or not compatibility_entrypoints:
        errors.append("cleanup_boundary_missing_compatibility_entrypoints")
    else:
        for path in compatibility_entrypoints:
            if not isinstance(path, str) or not (ROOT / path).is_file():
                errors.append(f"missing_compatibility_entrypoint:{path}")

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
        "benchmarks/mvp_decision_efficiency/README.md"
    ):
        if not (ROOT / path).is_file():
            errors.append(f"missing_mvp_core:{path}")
    return sorted(set(errors))


def main() -> int:
    errors = check()
    print(json.dumps({
        "kind": "CGKNProductDirectionGate",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors
    }, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
