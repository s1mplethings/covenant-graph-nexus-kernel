#!/usr/bin/env python3
"""Read-only shadow report for the impact planner on a real host run.

This script does not schedule, execute, mutate the DAG/store, or change
certificates.  It only reads execution_dag.json and goal_acceptance.json.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import replace

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.orchestration.execution_dag import ExecutionDAG
from cgkn.adapters.veriarbor.impact_adapter import node_block, shadow_report
from veriarbor.contract import Contract
from veriarbor.model import stable_hash
from veriarbor.variant import Variant


def _load(run_dir):
    run = pathlib.Path(run_dir).resolve()
    dag = ExecutionDAG.from_dict(json.loads(
        (run / "execution_dag.json").read_text(encoding="utf-8")))
    acceptance = json.loads(
        (run / "goal_acceptance.json").read_text(encoding="utf-8"))
    return dag, acceptance


def _pick_node(dag, acceptance):
    dependents = {node.id: [] for node in dag.nodes}
    for node in dag.nodes:
        for dependency in node.depends_on:
            dependents.setdefault(dependency, []).append(node.id)
    for node in dag.nodes:
        if dependents.get(node.id) and node_block(node.id, acceptance) is not None:
            return node.id
    raise SystemExit("no buildable node with dependents")


def _changed_block(old, kind):
    if kind == "internal":
        artifact, digest = old.variant.artifacts[0]
        variant = Variant("shadow-" + stable_hash({"artifact": artifact})[:16],
                          ((artifact, stable_hash({"changed": digest})),))
        return replace(old, variants=(variant,), active_variant=variant.variant_id)
    if kind == "breaking":
        port = old.output_ports[0]
        contract = Contract.create(
            {"host_contract": {"shadow": "breaking-boundary"}},
            "shadow breaking boundary")
        return replace(old, output_ports=(replace(port, contract=contract),))
    if kind == "input":
        port = old.input_ports[0]
        contract = Contract.create(
            {"host_contract": {"shadow": "input-breaking"}},
            "shadow input breaking")
        return replace(old, input_ports=(replace(port, contract=contract),))
    raise SystemExit("unknown change kind: " + kind)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--changed-node")
    parser.add_argument("--change", choices=("internal", "breaking", "input"), default="internal")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)
    dag, acceptance = _load(args.run_dir)
    changed = args.changed_node or _pick_node(dag, acceptance)
    old = node_block(changed, acceptance)
    if old is None:
        raise SystemExit("changed node has no buildable frozen block: " + changed)
    new = _changed_block(old, args.change)
    report = shadow_report(dag, acceptance, [changed], new_blocks={changed: new})
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        pathlib.Path(args.json_out).resolve().write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
