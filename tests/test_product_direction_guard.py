from __future__ import annotations

from scripts import product_direction_gate


def test_product_direction_gate_passes() -> None:
    assert product_direction_gate.check() == []


def test_mvp_authorities_are_explicit_and_honest() -> None:
    product = product_direction_gate._read("PRODUCT_GOAL.md")
    scope = product_direction_gate._read("MVP_SCOPE.md")
    readme = product_direction_gate._read("README.md")
    architecture = product_direction_gate._read_json("governance/current_architecture.json")
    boundary = product_direction_gate._read_json("governance/mvp_cleanup_boundary.json")

    assert "Capability Tree" in product
    assert "Tree-to-DAG" in product
    assert "Roles are capability bundles/views" in product
    assert "Provider-owned project planning" in scope
    assert "has **not** replaced the default compatibility project-generation runtime" in " ".join(readme.split())
    assert architecture["implementation_state"]["runtime_wiring"] == "ISOLATED_VERTICAL_SLICE_OPERATIONAL"
    assert architecture["implementation_state"]["compatibility_mainline_replacement"] == "NOT_IMPLEMENTED"
    assert boundary["status"] == "CLEANUP_COMPLETE_FEATURE_IMPLEMENTATION_REQUIRED"
    assert boundary["functional_readiness"] == "NOT_EVALUATED"
    assert boundary["next_increment"]["id"] == "MVP-002"


def test_pre_mvp_experiment_families_cannot_return_to_active_source() -> None:
    assert "scripts/agent_tree_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    assert "scripts/agent_growth_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    assert "scripts/commercial_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    assert "scripts/customer_agent_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    assert "scripts/agent_leaf_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    assert "scripts/full_dynamic_project_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES

    for path in (
        "run_function_stress_pass.py",
        "run_pass2_operational_closure.py",
        "demo_auto_generation.py",
        "detected_entrypoints.md",
        "docs/03_execution_flow.md",
        "docs/70_commercial_hardening_plan.md",
        "implementation_plan/CGNK_PHASED_IMPLEMENTATION_PLAN.md",
        "scripts/check_product_studio_contract.py",
        "scripts/run_agent_autonomous_diagnosis.py",
        "scripts/run_candidate_smoke_benchmark.py",
        "scripts/run_commercial_readiness.py",
        "scripts/run_continuous_verified_generation.py",
        "scripts/run_formal_live_delivery_closure.py",
        "scripts/run_reference_answer_project_trial.py",
        "scripts/release_candidate_gate.py",
        "schemas/product_studio_run.schema.json"
    ):
        assert path in product_direction_gate.FORBIDDEN_ACTIVE_PATHS

    for path in (
        "legacy/pre_mvp_reset",
        "legacy/docs/pre_mvp_reset",
        "scripts/full_pytest_timeout_diagnosis.py",
        "scripts/autonomous_project_acceptance.py",
        "scripts/pytest_hang_diagnostics.py",
        "schemas/autonomous_project_acceptance_report_v1.schema.json",
        "schemas/testability_contract_v1.schema.json",
        "tests/test_generation_scale_ladder.py",
    ):
        assert path in product_direction_gate.FORBIDDEN_ACTIVE_PATHS
        assert not (product_direction_gate.ROOT / path).exists()

    assert product_direction_gate._forbidden_import("scripts.agent_tree_orchestrator")
    assert product_direction_gate._forbidden_import("agent_director_loop")
    assert product_direction_gate._forbidden_import("check_product_studio_contract")
    assert product_direction_gate._forbidden_import("continuous_generation_ledger")
    assert product_direction_gate._forbidden_import("release_candidate_gate")


def test_compatibility_runtime_is_retained_until_replacement_exists() -> None:
    boundary = product_direction_gate._read_json("governance/mvp_cleanup_boundary.json")
    assert set(boundary["compatibility_entrypoints"]) == {
        "scripts/codex_conversation.py",
        "scripts/run_codex_conversation_generation.py",
        "scripts/run_local_pipeline.py",
        "scripts/run_local_pipeline_impl.py"
    }
