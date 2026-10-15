from __future__ import annotations

from .execution_dag import ExecutionDAG


def downstream_closure(dag: ExecutionDAG, node_ids: set[str] | frozenset[str]) -> tuple[str, ...]:
    unknown = set(node_ids) - set(dag.by_id)
    if unknown:
        raise ValueError("unknown invalidation nodes: " + ",".join(sorted(unknown)))
    affected = set(node_ids)
    changed = True
    while changed:
        changed = False
        for node in dag.nodes:
            if node.id not in affected and any(dependency in affected for dependency in node.depends_on):
                affected.add(node.id)
                changed = True
    order = dag.topological_order()
    return tuple(node_id for node_id in order if node_id in affected)


def invalidate_affected_subgraph(dag: ExecutionDAG, changed_nodes: set[str] | frozenset[str]) -> tuple[str, ...]:
    return downstream_closure(dag, changed_nodes)
