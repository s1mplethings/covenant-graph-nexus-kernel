from __future__ import annotations

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_current_product_authorities_are_explicit() -> None:
    contract = read("docs/00_kernel_contract.md")
    agents = read("AGENTS.md")
    architecture = json.loads(read("governance/current_architecture.json"))
    for authority in ("PRODUCT_GOAL.md", "MVP_SCOPE.md", "governance/product_invariants.json"):
        assert authority in contract
        assert authority in architecture["product_authority"]
    assert "CapabilityTree" in agents
    assert "ExecutionDAG" in agents


def test_capability_tree_mvp_is_the_only_current_direction() -> None:
    product = read("PRODUCT_GOAL.md")
    scope = read("MVP_SCOPE.md")
    contract = read("docs/00_kernel_contract.md")
    assert "Capability Tree" in product
    assert "Execution DAG" in product
    assert "Provider-owned project planning" in scope
    assert "must not maintain competing production task graphs" in contract
    assert "Roles are capability bundles/views" in read("AGENTS.md")


def test_existing_component_and_graph_types_remain_authoritative() -> None:
    authorities = json.loads(read("governance/current_architecture.json"))["declared_authorities"]
    assert authorities["composition"].endswith("CapabilityTree")
    assert authorities["execution_graph"].endswith("compile_tree")
    assert authorities["component_contract"].endswith("ComponentSpec")
    assert authorities["port_contract"].endswith("PortSpec")
    assert authorities["component_execution_record"].endswith("ComponentExecution")
    assert authorities["executor_resolution"].endswith("ExecutorRegistry")
    assert authorities["project_run_state"].endswith("FileRunStore")
    assert authorities["dag_runtime"].endswith("DAGRunner")
    assert authorities["capability_registry"].endswith("CapabilityRegistry")


def test_compatibility_entrypoints_are_retained_but_non_authoritative() -> None:
    architecture = json.loads(read("governance/current_architecture.json"))
    expected = {
        "scripts/codex_conversation.py",
        "scripts/run_codex_conversation_generation.py",
        "scripts/run_local_pipeline.py",
        "scripts/run_local_pipeline_impl.py",
    }
    assert set(architecture["compatibility_entrypoints"]) == expected
    assert "not the MVP planning or composition authority" in architecture["compatibility_rule"]
    assert all((ROOT / path).is_file() for path in expected)


def test_publication_authority_remains_guarded_and_unique() -> None:
    source = read("scripts/canonical_repo_publish.py")
    assert "canonical_repo_publish.py" in read("AGENTS.md")
    assert "canonical_repo_publish.py" in read("docs/00_kernel_contract.md")
    assert '\"add\", \".\"' not in source
    assert '\"add\", \"-A\"' not in source
    assert '\"push\", \"--force\"' not in source


def test_fast_ci_runs_current_direction_and_mvp_contracts() -> None:
    workflow = read(".github/workflows/repository-fast-ci.yml")
    assert "python scripts/product_direction_gate.py" in workflow
    assert "test_capability_tree_mvp.py" in workflow
    assert "tests/component" in workflow
    assert "test_kernel_contract.py" in workflow
    assert "provider" not in workflow.lower()
