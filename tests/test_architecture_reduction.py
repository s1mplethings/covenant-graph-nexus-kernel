from __future__ import annotations

import ast
import pathlib

from scripts.provider_jobs import (
    provider_job_from_work_node,
    provider_jobs_from_leaf_graph,
    work_node_from_provider_job,
)
from scripts.work_nodes import WorkNode, bounded_work_node_context, validate_work_nodes


ROOT = pathlib.Path(__file__).resolve().parents[1]
PRODUCTION_MODULES = [
    ROOT / "scripts" / "codex_conversation.py",
    ROOT / "scripts" / "run_local_pipeline_impl.py",
    ROOT / "scripts" / "provider_jobs.py",
    ROOT / "scripts" / "post_build_finalize.py",
    ROOT / "scripts" / "local_packager.py",
]


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.add(node.module)
    return values


def test_no_production_imports_from_legacy() -> None:
    offenders = {
        path.name: sorted(name for name in _imports(path) if name == "legacy" or name.startswith("legacy."))
        for path in PRODUCTION_MODULES
    }
    assert not {path: names for path, names in offenders.items() if names}


def test_no_formal_generation_uses_legacy() -> None:
    source = (ROOT / "scripts" / "codex_conversation.py").read_text(encoding="utf-8")
    start = source.split("def start_generation_from_income", 1)[1].split("\ndef ", 1)[0]
    launcher = source.split("def start_agent_generation", 1)[1].split("\ndef ", 1)[0]
    assert "start_agent_generation(" in start
    assert "target=run_provider_generation_job" in launcher
    assert "run_agent_generation_job" not in start
    assert "generate_project_legacy" not in start
    assert "generate_project_legacy" not in launcher


def test_normal_project_generation_does_not_require_artifact_runtime_context() -> None:
    forbidden = ("cgkn.artifacts", "cgkn.compiler", "cgkn.runtime")
    for path in PRODUCTION_MODULES:
        assert not tuple(name for name in _imports(path) if name.startswith(forbidden))


def test_worknode_preserves_provider_dependency_and_ownership() -> None:
    node = WorkNode(
        id="grade",
        goal="Grade a normalized formula",
        depends_on=("recognize",),
        inputs=("RecognizedFormula",),
        outputs=("GradingResult",),
        interfaces=("RecognizedFormula->GradingResult",),
        owns=("grading/",),
        acceptance=("correct answers pass",),
    )
    job = provider_job_from_work_node(node)
    restored = work_node_from_provider_job(job)
    assert restored.depends_on == node.depends_on
    assert restored.owns == node.owns
    assert restored.interfaces == node.interfaces
    assert restored.acceptance == node.acceptance


def test_leaf_maps_to_one_worknode_truth_via_provider_adapter() -> None:
    jobs = provider_jobs_from_leaf_graph("ui", {"leaves": [{"leaf_id": "a", "path": "a.py", "purpose": "A", "acceptance_checks": ["ok"]}, {"leaf_id": "b", "path": "b.py", "purpose": "B", "depends_on": ["a.py"], "acceptance_checks": ["done"]}]})
    nodes = [work_node_from_provider_job(job) for job in jobs]
    assert nodes[1].depends_on == ("a",)
    assert nodes[1].acceptance == ("done",)


def test_cycle_detection_and_ownership_conflict() -> None:
    cycle = [WorkNode("a", "A", ("b",)), WorkNode("b", "B", ("a",))]
    assert any("cycle" in item for item in validate_work_nodes(cycle))
    conflict = [WorkNode("a", "A", owns=("shared/",)), WorkNode("b", "B", owns=("shared/x.py",))]
    assert any("ownership_conflict" in item for item in validate_work_nodes(conflict))


def test_large_dag_context_is_bounded_to_direct_dependencies() -> None:
    nodes = [WorkNode(f"n{i}", f"Node {i}", (f"n{i-1}",) if i else ()) for i in range(101)]
    context = bounded_work_node_context(nodes[-1], nodes, goal_summary="large project")
    assert len(context["direct_dependencies"]) == 1
    assert context["context_sources"] == ["goal_summary", "work_node", "direct_dependencies", "related_code", "constraints", "acceptance"]
    assert "artifact_runtime" not in str(context).lower()
