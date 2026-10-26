from __future__ import annotations

import pytest

from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edit, apply_tree_edits


KNOWN = {"a@1", "b@1", "c@1"}
P = {"actor": "agent"}
pytestmark = [pytest.mark.happy_path, pytest.mark.boundary, pytest.mark.security]


def base() -> CapabilityTree:
    return CapabilityTree("goal", (CapabilityNode("root"), CapabilityNode("a", "root", "a@1"), CapabilityNode("b", "root", "b@1", ("a",), {"executor_ref": "old"})))


def edit(identifier, operation, node, payload=None): return TreeEdit(identifier, operation, node, payload or {}, P)


def test_all_mutating_operations_and_control_edits() -> None:
    tree = base()
    tree = apply_tree_edit(tree, edit("1", "add_node", "c", {"parent_id": "root", "capability_ref": "c@1", "depends_on": ["b"], "config": {}}), known_capabilities=KNOWN)
    tree = apply_tree_edit(tree, edit("2", "move_node", "c", {"parent_id": "a"}), known_capabilities=KNOWN)
    tree = apply_tree_edit(tree, edit("3", "remove_dependency", "c", {"dependency": "b"}), known_capabilities=KNOWN)
    tree = apply_tree_edit(tree, edit("4", "add_dependency", "c", {"dependency": "a"}), known_capabilities=KNOWN)
    tree = apply_tree_edit(tree, edit("5", "replace_executor", "c", {"executor_ref": "local@1"}), known_capabilities=KNOWN)
    tree = apply_tree_edit(tree, edit("6", "update_config", "c", {"config": {"nested": {"x": 1}}}), known_capabilities=KNOWN)
    tree = apply_tree_edit(tree, edit("7", "replace_node", "c", {"capability_ref": "b@1", "config": {"executor_ref": "other"}}), known_capabilities=KNOWN)
    assert tree.by_id["c"].capability_ref == "b@1" and tree.by_id["c"].parent_id == "a"
    tree = apply_tree_edit(tree, edit("8", "remove_node", "c"), known_capabilities=KNOWN)
    assert "c" not in tree.by_id
    assert apply_tree_edit(tree, edit("9", "retry_node", "a"), known_capabilities=KNOWN) is tree


@pytest.mark.negative
@pytest.mark.parametrize("candidate, message", [
    (lambda: TreeEdit("", "add_node", "x", {}, P), "invalid"),
    (lambda: TreeEdit("1", "unsupported", "x", {}, P), "invalid"),
    (lambda: TreeEdit("1", "remove_node", "x", {}, {}), "provenance"),
    (lambda: TreeEdit("1", "remove_node", "x", {"command": "rm"}, P), "payload"),
])
def test_invalid_edit_contract_is_rejected(candidate, message) -> None:
    with pytest.raises(ValueError, match=message): candidate()


@pytest.mark.negative
def test_unknown_nodes_capabilities_dependencies_and_invalid_payloads_fail_closed() -> None:
    tree = base()
    cases = [
        (edit("1", "add_node", "a", {"capability_ref": "a@1"}), "already exists"),
        (edit("2", "add_node", "x", {"capability_ref": "unknown@1"}), "unknown capability"),
        (edit("3", "remove_node", "missing"), "does not exist"),
        (edit("4", "replace_node", "a", {"capability_ref": "unknown@1"}), "unknown capability"),
        (edit("5", "add_dependency", "a", {"dependency": "missing"}), "dependency does not exist"),
        (edit("6", "remove_dependency", "a", {"dependency": "b"}), "does not exist on node"),
        (edit("7", "replace_executor", "a", {"executor_ref": ""}), "executor_ref"),
        (edit("8", "retry_node", "missing"), "node does not exist"),
    ]
    for candidate, message in cases:
        with pytest.raises(ValueError, match=message): apply_tree_edit(tree, candidate, known_capabilities=KNOWN)


@pytest.mark.fault_injection
@pytest.mark.recovery
def test_batch_duplicate_cycle_and_late_failure_roll_back_atomically() -> None:
    tree = base(); original = tree.as_dict()
    with pytest.raises(ValueError, match="duplicate tree edit"):
        apply_tree_edits(tree, (edit("same", "retry_node", "a"), edit("same", "retry_node", "b")), known_capabilities=KNOWN)
    edits = (edit("1", "add_node", "c", {"capability_ref": "c@1"}), edit("2", "add_dependency", "a", {"dependency": "b"}))
    with pytest.raises(ValueError, match="cycle"):
        apply_tree_edits(tree, edits, known_capabilities=KNOWN)
    assert tree.as_dict() == original and "c" not in tree.by_id
