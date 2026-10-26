from __future__ import annotations

import pytest

from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree


def test_tree_structure_is_separate_from_execution_dependencies() -> None:
    tree = CapabilityTree(
        goal="Add CSV import to a local application",
        nodes=(
            CapabilityNode(id="project"),
            CapabilityNode(id="inspect", parent_id="project", capability_ref="component.inspect_repo@1"),
            CapabilityNode(id="research", parent_id="project", capability_ref="component.search_library@1"),
            CapabilityNode(
                id="implement",
                parent_id="project",
                capability_ref="component.generate_patch@1",
                depends_on=("inspect", "research"),
            ),
            CapabilityNode(
                id="test",
                parent_id="project",
                capability_ref="component.pytest@1",
                depends_on=("implement",),
            ),
        ),
    )
    dag = compile_tree(tree)
    assert "project" not in dag.by_id
    assert dag.by_id["implement"].depends_on == ("inspect", "research")
    order = dag.topological_order()
    assert order.index("inspect") < order.index("implement")
    assert order.index("research") < order.index("implement")
    assert order.index("implement") < order.index("test")


def test_tree_rejects_structural_cycles() -> None:
    with pytest.raises(ValueError, match="parent_cycle"):
        CapabilityTree(
            goal="cycle",
            nodes=(
                CapabilityNode(id="a", parent_id="b"),
                CapabilityNode(id="b", parent_id="a"),
            ),
        )


def test_dag_rejects_execution_cycle() -> None:
    tree = CapabilityTree(
        goal="cycle",
        nodes=(
            CapabilityNode(id="root"),
            CapabilityNode(id="a", parent_id="root", capability_ref="component.a@1", depends_on=("b",)),
            CapabilityNode(id="b", parent_id="root", capability_ref="component.b@1", depends_on=("a",)),
        ),
    )
    with pytest.raises(ValueError, match="execution_dag.cycle"):
        compile_tree(tree)


def test_dependency_must_target_executable_node() -> None:
    with pytest.raises(ValueError, match="dependency_not_executable"):
        CapabilityTree(
            goal="invalid dependency",
            nodes=(
                CapabilityNode(id="root"),
                CapabilityNode(
                    id="task",
                    parent_id="root",
                    capability_ref="component.task@1",
                    depends_on=("root",),
                ),
            ),
        )
