#!/usr/bin/env python3
"""Small canonical planning contract for bounded project work.

WorkNode owns no scheduler, worker pool, Provider transport, evidence authority,
packaging, or delivery behavior.  Executors adapt a validated node into their
existing internal contract; production Provider concurrency remains ProviderJob.
"""

from __future__ import annotations

import pathlib
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


EXECUTOR_TYPES = {"agent", "deterministic", "skill", "external"}


def ownership_conflicts(
    owners_by_node: Iterable[tuple[str, Iterable[str]]],
) -> list[tuple[str, str, str, str]]:
    """Return cross-node exact and directory-prefix ownership conflicts.

    The previous validator compared every owner with every later owner.  This
    sorted index keeps the no-conflict path O(P log P), while still enumerating
    every real conflict (which is necessarily O(conflicts)).
    """
    entries: list[tuple[str, int, str]] = []
    for node_index, (node_id, owners) in enumerate(owners_by_node):
        entries.extend((str(owner), node_index, str(node_id)) for owner in owners)
    entries.sort(key=lambda item: (item[0], item[1], item[2]))
    paths = [item[0] for item in entries]
    conflicts: set[tuple[int, int, str, str, str, str]] = set()

    start = 0
    while start < len(entries):
        end = start + 1
        while end < len(entries) and entries[end][0] == entries[start][0]:
            end += 1
        for left_offset in range(start, end):
            for right_offset in range(left_offset + 1, end):
                left_path, left_index, left_id = entries[left_offset]
                right_path, right_index, right_id = entries[right_offset]
                if left_index == right_index:
                    continue
                if left_index > right_index:
                    left_index, right_index = right_index, left_index
                    left_id, right_id = right_id, left_id
                    left_path, right_path = right_path, left_path
                conflicts.add((left_index, right_index, left_id, right_id, left_path, right_path))
        start = end

    for owner_path, owner_index, owner_id in entries:
        if not owner_path.endswith("/"):
            continue
        first = bisect_left(paths, owner_path)
        for other_offset in range(first, len(entries)):
            other_path, other_index, other_id = entries[other_offset]
            if not other_path.startswith(owner_path):
                break
            if other_path == owner_path or other_index == owner_index:
                continue
            if owner_index < other_index:
                conflict = (owner_index, other_index, owner_id, other_id, owner_path, other_path)
            else:
                conflict = (other_index, owner_index, other_id, owner_id, other_path, owner_path)
            conflicts.add(conflict)
    return [(left_id, right_id, left_path, right_path) for _, _, left_id, right_id, left_path, right_path in sorted(conflicts)]


def dependency_cycle_nodes(
    node_ids: Iterable[str], dependencies: Mapping[str, Iterable[str]]
) -> list[str]:
    """Detect dependency back-edges without consuming Python recursion depth."""
    known = set(node_ids)
    state: dict[str, int] = {}
    cycle_nodes: set[str] = set()
    for root in sorted(known):
        if state.get(root, 0):
            continue
        state[root] = 1
        stack: list[tuple[str, list[str], int]] = [
            (root, list(dependencies.get(root, ())), 0)
        ]
        while stack:
            node_id, node_dependencies, offset = stack[-1]
            if offset >= len(node_dependencies):
                state[node_id] = 2
                stack.pop()
                continue
            dependency = node_dependencies[offset]
            stack[-1] = (node_id, node_dependencies, offset + 1)
            if dependency not in known:
                continue
            dependency_state = state.get(dependency, 0)
            if dependency_state == 1:
                cycle_nodes.add(dependency)
            elif dependency_state == 0:
                state[dependency] = 1
                stack.append((dependency, list(dependencies.get(dependency, ())), 0))
    return sorted(cycle_nodes)


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
    executor_details: Mapping[str, Any] = field(default_factory=dict)
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
            executor_details=dict(executor) if isinstance(executor, Mapping) else {},
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
            "executor": {**dict(self.executor_details), "type": self.executor_type},
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
    for left_id, right_id, left_owner, right_owner in ownership_conflicts(
        (node.id, node.owns) for node in values
    ):
        errors.append(
            f"work_node.ownership_conflict:{left_id}:{right_id}:{left_owner}:{right_owner}"
        )
    for node_id in dependency_cycle_nodes(
        by_id, {node.id: node.depends_on for node in values if node.id}
    ):
        errors.append(f"work_node.cycle:{node_id}")
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
