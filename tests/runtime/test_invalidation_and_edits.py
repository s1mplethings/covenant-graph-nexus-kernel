from __future__ import annotations

import pytest

from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.invalidation import downstream_closure, invalidate_affected_subgraph
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edit


def graph():
    tree = CapabilityTree("repair", (
        CapabilityNode("inspect", capability_ref="inspect@1"), CapabilityNode("research", capability_ref="research@1"),
        CapabilityNode("implement", capability_ref="implement@1", depends_on=("inspect", "research")),
        CapabilityNode("test", capability_ref="test@1", depends_on=("implement",)),
        CapabilityNode("report", capability_ref="report@1", depends_on=("test",)),
    ))
    return tree, compile_tree(tree)


def test_downstream_closure_is_smallest_affected_subgraph() -> None:
    _, dag = graph()
    assert downstream_closure(dag, {"test"}) == ("test", "report")
    assert downstream_closure(dag, {"implement"}) == ("implement", "test", "report")
    assert downstream_closure(dag, set()) == ()
    assert invalidate_affected_subgraph(dag, {"research"}) == ("research", "implement", "test", "report")
    with pytest.raises(ValueError, match="unknown invalidation"):
        downstream_closure(dag, {"missing"})


def test_tree_edit_validates_preview_dag_and_provenance() -> None:
    tree, _ = graph()
    edited = apply_tree_edit(tree, TreeEdit("e1", "replace_executor", "test", {"executor_ref": "local.command@1"}, {"actor": "agent"}), known_capabilities={node.capability_ref for node in tree.nodes})
    assert edited.by_id["test"].config["executor_ref"] == "local.command@1"
    with pytest.raises(ValueError):
        apply_tree_edit(tree, TreeEdit("e2", "add_dependency", "inspect", {"dependency": "report"}, {"actor": "agent"}), known_capabilities={node.capability_ref for node in tree.nodes})
    with pytest.raises(ValueError, match="still depended"):
        apply_tree_edit(tree, TreeEdit("e3", "remove_node", "test", {}, {"actor": "agent"}), known_capabilities={node.capability_ref for node in tree.nodes})
