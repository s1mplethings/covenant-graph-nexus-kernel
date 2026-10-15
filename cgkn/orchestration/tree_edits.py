from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .capability_tree import CapabilityNode, CapabilityTree, _freeze
from .execution_dag import compile_tree


SUPPORTED_OPERATIONS = {"add_node", "remove_node", "replace_node", "move_node", "add_dependency", "remove_dependency", "replace_executor", "update_config", "retry_node", "request_run", "finish"}


@dataclass(frozen=True)
class TreeEdit:
    edit_id: str
    operation: str
    node_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.edit_id or self.operation not in SUPPORTED_OPERATIONS:
            raise ValueError("invalid tree edit identity or operation")
        if not self.provenance:
            raise ValueError("tree edit provenance is required")
        allowed = {
            "add_node": {"parent_id", "capability_ref", "depends_on", "config"}, "remove_node": set(),
            "replace_node": {"capability_ref", "config"}, "move_node": {"parent_id"},
            "add_dependency": {"dependency"}, "remove_dependency": {"dependency"},
            "replace_executor": {"executor_ref"}, "update_config": {"config"},
            "retry_node": set(), "request_run": set(), "finish": set(),
        }
        if set(self.payload) - allowed[self.operation]:
            raise ValueError("invalid tree edit payload")
        object.__setattr__(self, "payload", _freeze(self.payload))
        object.__setattr__(self, "provenance", _freeze(self.provenance))


def apply_tree_edits(tree: CapabilityTree, edits: tuple[TreeEdit, ...], *, known_capabilities: set[str] | frozenset[str]) -> CapabilityTree:
    ids = [edit.edit_id for edit in edits]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate tree edit id")
    preview = tree
    for edit in edits:
        preview = apply_tree_edit(preview, edit, known_capabilities=known_capabilities)
    compile_tree(preview)
    return preview


def apply_tree_edit(tree: CapabilityTree, edit: TreeEdit, *, known_capabilities: set[str] | frozenset[str]) -> CapabilityTree:
    nodes = list(tree.nodes)
    index = {node.id: position for position, node in enumerate(nodes)}
    if edit.operation in {"retry_node", "request_run", "finish"}:
        if edit.operation == "retry_node" and edit.node_id not in {node.id for node in nodes}:
            raise ValueError("node does not exist")
        return tree
    if edit.operation == "add_node":
        if edit.node_id in index:
            raise ValueError("node already exists")
        capability_ref = str(edit.payload.get("capability_ref", ""))
        if capability_ref and capability_ref not in known_capabilities:
            raise ValueError("unknown capability")
        nodes.append(CapabilityNode(edit.node_id, str(edit.payload.get("parent_id", "")), capability_ref, tuple(edit.payload.get("depends_on", ())), dict(edit.payload.get("config", {}))))
    else:
        if edit.node_id not in index:
            raise ValueError("node does not exist")
        old = nodes[index[edit.node_id]]
        if edit.operation == "remove_node":
            if any(edit.node_id in node.depends_on for node in nodes):
                raise ValueError("cannot remove a node that is still depended on")
            if any(node.parent_id == edit.node_id for node in nodes):
                raise ValueError("cannot remove a node with children without rewiring")
            nodes.pop(index[edit.node_id])
        elif edit.operation == "replace_node":
            capability_ref = str(edit.payload.get("capability_ref", ""))
            if capability_ref not in known_capabilities:
                raise ValueError("unknown capability")
            nodes[index[edit.node_id]] = replace(old, capability_ref=capability_ref, config=dict(edit.payload.get("config", old.config)))
        elif edit.operation == "move_node":
            nodes[index[edit.node_id]] = replace(old, parent_id=str(edit.payload.get("parent_id", "")))
        elif edit.operation in {"add_dependency", "remove_dependency"}:
            dependency = str(edit.payload.get("dependency", ""))
            values = list(old.depends_on)
            if edit.operation == "add_dependency":
                if dependency not in index:
                    raise ValueError("dependency does not exist")
                if dependency not in values:
                    values.append(dependency)
            else:
                if dependency not in values:
                    raise ValueError("dependency does not exist on node")
                values.remove(dependency)
            nodes[index[edit.node_id]] = replace(old, depends_on=tuple(values))
        elif edit.operation == "replace_executor":
            config = dict(old.config)
            executor_ref = str(edit.payload.get("executor_ref", ""))
            if not executor_ref: raise ValueError("executor_ref is required")
            config["executor_ref"] = executor_ref
            nodes[index[edit.node_id]] = replace(old, config=config)
        elif edit.operation == "update_config":
            if not isinstance(edit.payload.get("config", {}), Mapping): raise ValueError("config must be an object")
            config = dict(old.config)
            config.update(dict(edit.payload.get("config", {})))
            nodes[index[edit.node_id]] = replace(old, config=config)
    preview = CapabilityTree(tree.goal, tuple(nodes))
    compile_tree(preview)
    return preview
