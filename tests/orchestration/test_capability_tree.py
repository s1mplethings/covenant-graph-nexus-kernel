from __future__ import annotations

import random

import pytest

from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary, pytest.mark.determinism]


@pytest.mark.roundtrip
def test_multiple_roots_structural_executable_round_trip_and_nested_immutability() -> None:
    source = {"nested": {"values": [1]}}
    tree = CapabilityTree(" goal ", (CapabilityNode("group"), CapabilityNode("task", capability_ref="cap@1", config=source), CapabilityNode("other")))
    source["nested"]["values"].append(2)
    assert tree.goal == "goal" and [node.id for node in tree.roots] == ["group", "task", "other"]
    assert tree.by_id["task"].config["nested"]["values"] == (1,)
    assert CapabilityTree.from_dict(tree.as_dict()).as_dict() == tree.as_dict()


@pytest.mark.negative
@pytest.mark.parametrize("nodes, message", [
    ((CapabilityNode("a"), CapabilityNode("a")), "unique"),
    ((CapabilityNode("a", parent_id="missing"),), "unknown_parent"),
    ((CapabilityNode("a", capability_ref="a@1", depends_on=("missing",)),), "unknown_dependency"),
    ((CapabilityNode("a", capability_ref="a@1", depends_on=("a",)),), "self_dependency"),
    ((CapabilityNode("group"), CapabilityNode("a", capability_ref="a@1", depends_on=("group",))), "dependency_not_executable"),
])
def test_tree_rejects_invalid_identity_parent_and_dependencies(nodes, message) -> None:
    with pytest.raises(ValueError, match=message):
        CapabilityTree("goal", nodes)


@pytest.mark.negative
def test_tree_rejects_empty_goal_self_parent_and_malformed_persistence() -> None:
    with pytest.raises(ValueError, match="goal"):
        CapabilityTree("", ())
    with pytest.raises(ValueError, match="parent itself"):
        CapabilityNode("a", parent_id="a")
    with pytest.raises(ValueError, match="malformed"):
        CapabilityTree.from_dict({"kind": "bad", "schema_version": "1.0", "goal": "g", "nodes": []})
    with pytest.raises(ValueError, match="malformed capability node"):
        CapabilityTree.from_dict({"kind": "CGKNCapabilityTree", "schema_version": "1.0", "goal": "g", "nodes": [{"id": "a", "extra": 1}]})


@pytest.mark.property
def test_fixed_seed_dag_dependencies_precede_dependents_and_order_is_stable() -> None:
    rng = random.Random(1729)
    nodes = []
    for index in range(40):
        candidates = [f"n{prior}" for prior in range(index)]
        dependencies = tuple(sorted(rng.sample(candidates, k=min(len(candidates), rng.randrange(0, 4)))))
        nodes.append(CapabilityNode(f"n{index}", capability_ref=f"cap.{index}@1", depends_on=dependencies))
    tree = CapabilityTree("property", tuple(nodes))
    first = compile_tree(tree).topological_order(); second = compile_tree(tree).topological_order()
    assert first == second
    positions = {node_id: index for index, node_id in enumerate(first)}
    assert all(positions[dependency] < positions[node.id] for node in tree.nodes for dependency in node.depends_on)
