from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping): return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)): return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping): return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple): return [_thaw(item) for item in value]
    return value


def _items(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


@dataclass(frozen=True)
class CapabilityNode:
    """One node in the Agent-expanded composition tree.

    parent_id is structural composition. depends_on is execution dependency.
    A node without capability_ref is structural/grouping only.
    """

    id: str
    parent_id: str = ""
    capability_ref: str = ""
    depends_on: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        node_id = self.id.strip()
        if not node_id:
            raise ValueError("capability node id is required")
        if self.parent_id.strip() == node_id:
            raise ValueError(f"capability node cannot parent itself: {node_id}")
        object.__setattr__(self, "id", node_id)
        object.__setattr__(self, "parent_id", self.parent_id.strip())
        object.__setattr__(self, "capability_ref", self.capability_ref.strip())
        object.__setattr__(self, "depends_on", _items(self.depends_on))
        object.__setattr__(self, "config", _freeze(self.config))

    @property
    def executable(self) -> bool:
        return bool(self.capability_ref)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "capability_ref": self.capability_ref,
            "depends_on": list(self.depends_on),
            "config": _thaw(self.config),
        }


@dataclass(frozen=True)
class CapabilityTree:
    goal: str
    nodes: tuple[CapabilityNode, ...]

    def __post_init__(self) -> None:
        goal = self.goal.strip()
        if not goal:
            raise ValueError("capability tree goal is required")
        values = tuple(self.nodes)
        errors = validate_tree(values)
        if errors:
            raise ValueError(";".join(errors))
        object.__setattr__(self, "goal", goal)
        object.__setattr__(self, "nodes", values)

    @property
    def by_id(self) -> dict[str, CapabilityNode]:
        return {node.id: node for node in self.nodes}

    @property
    def roots(self) -> tuple[CapabilityNode, ...]:
        return tuple(node for node in self.nodes if not node.parent_id)

    def children(self, node_id: str) -> tuple[CapabilityNode, ...]:
        return tuple(node for node in self.nodes if node.parent_id == node_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGKNCapabilityTree",
            "schema_version": "1.0",
            "goal": self.goal,
            "nodes": [node.as_dict() for node in self.nodes],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityTree":
        if set(value) != {"kind", "schema_version", "goal", "nodes"} or value.get("kind") != "CGKNCapabilityTree" or value.get("schema_version") != "1.0":
            raise ValueError("malformed capability tree")
        if not isinstance(value.get("nodes"), list): raise ValueError("malformed capability tree nodes")
        allowed = {"id", "parent_id", "capability_ref", "depends_on", "config"}
        nodes = []
        for raw in value["nodes"]:
            if not isinstance(raw, Mapping) or set(raw) - allowed: raise ValueError("malformed capability node")
            nodes.append(CapabilityNode(str(raw["id"]), str(raw.get("parent_id", "")), str(raw.get("capability_ref", "")), tuple(str(item) for item in raw.get("depends_on", ())), dict(raw.get("config", {}))))
        return cls(str(value["goal"]), tuple(nodes))


def validate_tree(nodes: Iterable[CapabilityNode]) -> list[str]:
    values = tuple(nodes)
    errors: list[str] = []
    by_id = {node.id: node for node in values}
    if len(by_id) != len(values):
        return ["capability_tree.unique_nonempty_ids"]

    for node in values:
        if node.parent_id and node.parent_id not in by_id:
            errors.append(f"capability_tree.unknown_parent:{node.id}:{node.parent_id}")
        for dependency in node.depends_on:
            if dependency not in by_id:
                errors.append(f"capability_tree.unknown_dependency:{node.id}:{dependency}")
            elif dependency == node.id:
                errors.append(f"capability_tree.self_dependency:{node.id}")
            elif not by_id[dependency].executable:
                errors.append(f"capability_tree.dependency_not_executable:{node.id}:{dependency}")

    for node in values:
        seen: set[str] = set()
        current = node
        while current.parent_id:
            if current.id in seen:
                errors.append(f"capability_tree.parent_cycle:{node.id}")
                break
            seen.add(current.id)
            parent = by_id.get(current.parent_id)
            if parent is None:
                break
            current = parent

    return sorted(set(errors))
