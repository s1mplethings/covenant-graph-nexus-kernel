"""Shadow mapping from host DAG/acceptance facts to VeriArbor impact plans.

Read-only: this module never mutates the DAG, store, certificates or scheduling.
The host keeps execution and acceptance authority.
"""
from __future__ import annotations

from .substitution_adapter import milestone_block
from .block_adapter import local_scope, verification_key
from cgkn.orchestration.invalidation import downstream_closure
from veriarbor.compatibility import PortCompatibility
from veriarbor.impact import plan_impact


def _index(acceptance):
    goals = {goal["id"]: goal for goal in acceptance["plans"][-1]["goals"]}
    checks = {}
    for check in acceptance.get("checks", ()):
        checks.setdefault(check["node_id"], []).append(check)
    return goals, checks, acceptance["subjects"]


def _block_for_node(node_id, goals, checks, subjects):
    rows = checks.get(node_id) or []
    if not rows:
        return None, None, None, None
    check = rows[-1]
    goal = goals.get(check["goal_id"])
    if not goal or not goal.get("milestone_contract"):
        return None, goal, check, None
    try:
        block = milestone_block(goal, subjects)
    except (OSError, ValueError, KeyError, TypeError):
        return None, goal, check, None
    checker = (check.get("provenance") or {}).get("chain", {}).get("checker", {})
    return block, goal, check, checker


def _consumer_evidence(consumer_ids, goals, checks, subjects):
    old_keys, authenticated, observations = {}, {}, {}
    for node_id in consumer_ids:
        block, goal, check, checker = _block_for_node(node_id, goals, checks, subjects)
        if block is None or not goal or not checker.get("hash"):
            continue
        key = verification_key(block, goal["id"], checker["hash"])
        old_keys[node_id] = key
        trusted = (check.get("provenance") or {}).get("status") == "TRUSTED"
        if trusted:
            authenticated[node_id] = key.fingerprint
        observations[node_id] = [{
            "key": key.fingerprint,
            "status": "PASS" if check.get("verdict") == "VERIFIED" else "FAIL",
            "authenticated": trusted,
        }]
    return old_keys, authenticated, observations


def plan_acceptance_changes(dag, acceptance, changed_nodes, *, new_blocks=None,
                            external_context_unchanged=False,
                            unmapped_consumers=None,
                            expand_breaking=True):
    """Return one plan per changed node; no scheduling or persistence."""
    goals, checks, subjects = _index(acceptance)
    new_blocks = new_blocks or {}
    unmapped_consumers = set(unmapped_consumers or ())
    dependents = {}
    for node in dag.nodes:
        for dependency in node.depends_on:
            dependents.setdefault(dependency, []).append(node.id)
    plans = []
    for changed in sorted(set(changed_nodes)):
        if changed not in dag.by_id:
            raise ValueError("unknown changed node: " + changed)
        old_block, goal, _, _ = _block_for_node(changed, goals, checks, subjects)
        if old_block is None or goal is None:
            raise ValueError("no buildable frozen block for changed node: " + changed)
        new_block = new_blocks.get(changed, old_block)
        consumers = {node_id: ("response",) for node_id in dependents.get(changed, ())}
        for node_id in consumers:
            consumer_block = node_block(node_id, acceptance)
            if consumer_block is None or not consumer_block.input_ports:
                unmapped_consumers.add(node_id)
        adjacency = {key: tuple(sorted(value)) for key, value in dependents.items()}
        old_keys, authenticated, observations = _consumer_evidence(
            tuple(consumers), goals, checks, subjects)
        input_producers, producer_ports = {}, {}
        if len(dag.by_id[changed].depends_on) == 1 and len(old_block.input_ports) == 1:
            producer = dag.by_id[changed].depends_on[0]
            producer_block, _, _, _ = _block_for_node(producer, goals, checks, subjects)
            if producer_block is not None and producer_block.output_ports:
                port_id = old_block.input_ports[0].port_id
                input_producers[port_id] = producer
                producer_ports[producer] = {port_id: producer_block.output_ports[0]}
        plans.append(plan_impact(
            old_block.block_id, old_block, new_block,
            consumers=consumers, adjacency=adjacency,
            old_keys=old_keys, authenticated_keys=authenticated,
            observations=observations,
            input_producers=input_producers, producer_ports=producer_ports,
            unmapped_consumers=tuple(sorted(unmapped_consumers)),
            external_context_unchanged=external_context_unchanged,
            expand_breaking=expand_breaking,
        ))
    return tuple(plans)


def node_block(node_id, acceptance):
    """Build the frozen host block for a DAG node, or None."""
    goals, checks, subjects = _index(acceptance)
    return _block_for_node(node_id, goals, checks, subjects)[0]


def shadow_report(dag, acceptance, changed_nodes, *, new_blocks=None,
                  external_context_unchanged=False,
                  unmapped_consumers=None,
                  expand_breaking=True):
    """Compare planner scope with host downstream closure and default local scope."""
    changed = set(changed_nodes)
    plans = plan_acceptance_changes(dag, acceptance, changed_nodes,
                                    new_blocks=new_blocks,
                                    external_context_unchanged=external_context_unchanged,
                                    unmapped_consumers=unmapped_consumers,
                                    expand_breaking=expand_breaking)
    by_node = {}
    relations = {}
    impacted, retest = set(), set()
    reuse = {}
    for plan in plans:
        changed_id = plan.changed
        # The block id is a goal id; map it back to the DAG node for comparison.
        node_id = next((node.id for node in dag.nodes
                        if node.config.get("goal_id") == changed_id), changed_id)
        by_node[changed_id] = node_id
        relations[node_id] = PortCompatibility(plan.block_relation)
        for item in plan.impacted:
            impacted.add(node_id if item.node_id == changed_id else item.node_id)
        for item in plan.retest():
            retest.add(node_id if item == changed_id else item)
        reuse.update(dict(plan.reuse))
        if changed_id in reuse:
            reuse[node_id] = reuse.pop(changed_id)
    host_closure = set(downstream_closure(dag, changed))
    host_default, _ = local_scope(dag, changed)
    host_relation, _ = local_scope(dag, changed, boundary_relations=relations)
    return {
        "kind": "CGKNImpactShadowReport",
        "changed_nodes": sorted(changed),
        "block_node_map": by_node,
        "host_closure": sorted(host_closure),
        "host_revalidation_default": sorted(host_default),
        "host_local_with_relation": sorted(host_relation),
        "planner_impacted": sorted(impacted),
        "planner_retest": sorted(retest),
        "planner_minus_host_default": sorted(impacted - set(host_default)),
        "host_default_minus_planner": sorted(set(host_default) - impacted),
        "planner_minus_host_closure": sorted(impacted - host_closure),
        "host_closure_minus_planner": sorted(host_closure - impacted),
        "planner_minus_host_local_relation": sorted(impacted - set(host_relation)),
        "host_local_relation_minus_planner": sorted(set(host_relation) - impacted),
        "reuse_pass": sorted(node for node, value in reuse.items() if value == "REUSE_PASS"),
        "reuse_execute": sorted(node for node, value in reuse.items() if value == "EXECUTE"),
        "reuse_unverified": sorted(node for node, value in reuse.items() if value == "UNVERIFIED"),
        "reuse_no_novel_delta": sorted(node for node, value in reuse.items() if value == "NO_NOVEL_DELTA"),
        "consumer_reuse_allowed": all(plan.consumer_reuse_allowed for plan in plans) if plans else False,
        "reuse_gate": sorted({plan.reuse_gate for plan in plans}),
        "unmapped_consumers": sorted({node for plan in plans for node in plan.unmapped_consumers}),
        "plans": [plan.as_dict() for plan in plans],
        "authority": "shadow advice only; host execution and scheduling unchanged",
    }
