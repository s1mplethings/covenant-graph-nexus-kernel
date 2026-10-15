from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .capability_tree import CapabilityNode, CapabilityTree
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


def apply_tree_edit(tree: CapabilityTree, edit: TreeEdit, *, known_capabilities: set[str] | frozenset[str]) -> CapabilityTree:
    nodes = list(tree.nodes)
    index = {node.id: position for position, node in enumerate(nodes)}
    if edit.operation in {"retry_node", "request_run", "finish"}:
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
            config["executor_ref"] = str(edit.payload.get("executor_ref", ""))
            nodes[index[edit.node_id]] = replace(old, config=config)
        elif edit.operation == "update_config":
            config = dict(old.config)
            config.update(dict(edit.payload.get("config", {})))
            nodes[index[edit.node_id]] = replace(old, config=config)
    preview = CapabilityTree(tree.goal, tuple(nodes))
    compile_tree(preview)
    return preview
