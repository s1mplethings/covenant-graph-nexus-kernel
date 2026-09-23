#!/usr/bin/env python3
"""Small canonical planning contract for bounded project work.

WorkNode owns no scheduler, worker pool, Provider transport, evidence authority,
packaging, or delivery behavior.  Executors adapt a validated node into their
existing internal contract; production Provider concurrency remains ProviderJob.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


EXECUTOR_TYPES = {"agent", "deterministic", "skill", "external"}


def _items(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _path(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    while raw.startswith("./"):
        raw = raw[2:]
    directory = raw.endswith("/")
    if not raw or raw.startswith("/") or ":" in raw.split("/", 1)[0]:
        return ""
    parts = pathlib.PurePosixPath(raw).parts
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    normalized = pathlib.PurePosixPath(*parts).as_posix()
    return normalized + "/" if directory else normalized


@dataclass(frozen=True)
class WorkNode:
    id: str
    goal: str
    depends_on: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    executor_type: str = "agent"
    owns: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkNode":
        executor = value.get("executor", {})
        executor_type = str(executor.get("type", "agent") if isinstance(executor, Mapping) else executor).strip()
        return cls(
            id=str(value.get("id", "")).strip(),
            goal=str(value.get("goal", "")).strip(),
            depends_on=_items(value.get("depends_on", [])),
            inputs=_items(value.get("inputs", [])),
            outputs=_items(value.get("outputs", [])),
            interfaces=_items(value.get("interfaces", [])),
            executor_type=executor_type or "agent",
            owns=tuple(path for path in (_path(item) for item in value.get("owns", [])) if path),
            acceptance=_items(value.get("acceptance", [])),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "depends_on": list(self.depends_on),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "interfaces": list(self.interfaces),
            "executor": {"type": self.executor_type},
            "owns": list(self.owns),
            "acceptance": list(self.acceptance),
        }


def validate_work_nodes(nodes: Iterable[WorkNode]) -> list[str]:
    values = list(nodes)
    errors: list[str] = []
    by_id = {node.id: node for node in values if node.id}
    if len(by_id) != len(values):
        errors.append("work_nodes.unique_nonempty_ids")
    for node in values:
        if not node.goal:
            errors.append(f"work_node.goal:{node.id}")
        if node.executor_type not in EXECUTOR_TYPES:
            errors.append(f"work_node.executor_type:{node.id}:{node.executor_type}")
        for dependency in node.depends_on:
            if dependency not in by_id:
                errors.append(f"work_node.unknown_dependency:{node.id}:{dependency}")
            if dependency == node.id:
                errors.append(f"work_node.self_dependency:{node.id}")
    for index, left in enumerate(values):
        for right in values[index + 1 :]:
            for left_owner in left.owns:
                for right_owner in right.owns:
                    if left_owner == right_owner or (left_owner.endswith("/") and right_owner.startswith(left_owner)) or (right_owner.endswith("/") and left_owner.startswith(right_owner)):
                        errors.append(f"work_node.ownership_conflict:{left.id}:{right.id}:{left_owner}:{right_owner}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            errors.append(f"work_node.cycle:{node_id}")
            return
        if node_id in visited or node_id not in by_id:
            return
        visiting.add(node_id)
        for dependency in by_id[node_id].depends_on:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(by_id):
        visit(node_id)
    return sorted(set(errors))


def bounded_work_node_context(
    node: WorkNode,
    nodes: Iterable[WorkNode],
    *,
    goal_summary: str,
    related_code: Iterable[str] = (),
    constraints: Iterable[str] = (),
) -> dict[str, Any]:
    """Return local execution context independent of unrelated DAG size."""
    by_id = {item.id: item for item in nodes}
    direct = [by_id[item].as_dict() for item in node.depends_on if item in by_id]
    return {
        "goal_summary": str(goal_summary).strip(),
        "work_node": node.as_dict(),
        "direct_dependencies": direct,
        "related_code": list(dict.fromkeys(str(item) for item in related_code if str(item).strip())),
        "constraints": list(dict.fromkeys(str(item) for item in constraints if str(item).strip())),
        "acceptance": list(node.acceptance),
        "context_sources": ["goal_summary", "work_node", "direct_dependencies", "related_code", "constraints", "acceptance"],
    }
