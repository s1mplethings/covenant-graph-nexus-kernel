from __future__ import annotations

from scripts import product_direction_gate


def test_product_direction_gate_passes() -> None:
    assert product_direction_gate.check() == []


def test_mvp_authorities_are_explicit() -> None:
    product = product_direction_gate._read("PRODUCT_GOAL.md")
    scope = product_direction_gate._read("MVP_SCOPE.md")
    assert "Capability Tree" in product
    assert "Tree-to-DAG" in product
    assert "Roles are capability bundles/views" in product
    assert "Provider-owned project planning" in scope
    assert "Fixed10 as a product-readiness gate" in scope


def test_pre_mvp_experiment_families_cannot_return_to_active_source() -> None:
    assert "scripts/agent_tree_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    assert "scripts/agent_growth_" in product_direction_gate.FORBIDDEN_ACTIVE_PREFIXES
    for path in (
        "run_function_stress_pass.py",
        "run_pass2_operational_closure.py",
        "demo_auto_generation.py",
        "detected_entrypoints.md",
        "scripts/run_agent_autonomous_diagnosis.py",
        "scripts/run_continuous_verified_generation.py",
        "scripts/release_candidate_gate.py",
    ):
        assert path in product_direction_gate.FORBIDDEN_ACTIVE_PATHS
    assert product_direction_gate._forbidden_import("scripts.agent_tree_orchestrator")
    assert product_direction_gate._forbidden_import("agent_director_loop")
    assert product_direction_gate._forbidden_import("continuous_generation_ledger")
    assert product_direction_gate._forbidden_import("release_candidate_gate")
