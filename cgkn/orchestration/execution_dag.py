from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .capability_tree import CapabilityTree


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class ExecutionNode:
    id: str
    capability_ref: str
    depends_on: tuple[str, ...]
    config: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.capability_ref.strip():
            raise ValueError("execution node id and capability_ref are required")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))
        object.__setattr__(self, "config", _freeze(self.config))


@dataclass(frozen=True)
class ExecutionDAG:
    goal: str
    nodes: tuple[ExecutionNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(self.nodes))
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("execution_dag.duplicate_node_id")

    @property
    def by_id(self) -> dict[str, ExecutionNode]:
        return {node.id: node for node in self.nodes}

    def topological_order(self) -> tuple[str, ...]:
        by_id = self.by_id
        indegree = {node_id: 0 for node_id in by_id}
        dependents: dict[str, list[str]] = {node_id: [] for node_id in by_id}
        for node in self.nodes:
            for dependency in node.depends_on:
                if dependency not in by_id:
                    raise ValueError(f"execution_dag.unknown_dependency:{node.id}:{dependency}")
                indegree[node.id] += 1
                dependents[dependency].append(node.id)

        ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            node_id = ready.pop(0)
            ordered.append(node_id)
            for dependent in sorted(dependents[node_id]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()

        if len(ordered) != len(by_id):
            remaining = sorted(node_id for node_id, degree in indegree.items() if degree)
            raise ValueError("execution_dag.cycle:" + ",".join(remaining))
        return tuple(ordered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGKNExecutionDAG",
            "schema_version": "1.0",
            "goal": self.goal,
            "nodes": [
                {
                    "id": node.id,
                    "capability_ref": node.capability_ref,
                    "depends_on": list(node.depends_on),
                    "config": _thaw(node.config),
                }
                for node in self.nodes
            ],
            "topological_order": list(self.topological_order()),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExecutionDAG":
        if value.get("kind") != "CGKNExecutionDAG" or value.get("schema_version") != "1.0":
            raise ValueError("execution_dag.invalid_schema")
        dag = cls(
            goal=str(value["goal"]),
            nodes=tuple(
                ExecutionNode(
                    id=str(node["id"]),
                    capability_ref=str(node["capability_ref"]),
                    depends_on=tuple(str(item) for item in node.get("depends_on", ())),
                    config=dict(node.get("config", {})),
                )
                for node in value.get("nodes", ())
            ),
        )
        dag.topological_order()
        if "topological_order" in value and tuple(value["topological_order"]) != dag.topological_order():
            raise ValueError("execution_dag.topological_order_mismatch")
        return dag


def compile_tree(tree: CapabilityTree) -> ExecutionDAG:
    executable = {node.id: node for node in tree.nodes if node.executable}
    nodes: list[ExecutionNode] = []
    for node in tree.nodes:
        if not node.executable:
            continue
        unknown = [dependency for dependency in node.depends_on if dependency not in executable]
        if unknown:
            raise ValueError(
                f"execution_dag.non_executable_dependency:{node.id}:" + ",".join(sorted(unknown))
            )
        nodes.append(
            ExecutionNode(
                id=node.id,
                capability_ref=node.capability_ref,
                depends_on=node.depends_on,
                config=node.config,
            )
        )
    dag = ExecutionDAG(goal=tree.goal, nodes=tuple(nodes))
    dag.topological_order()
    return dag
