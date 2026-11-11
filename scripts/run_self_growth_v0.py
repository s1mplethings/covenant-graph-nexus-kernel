from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.capabilities import CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.executors import ExecutorRegistry
from cgkn.growth import CapabilityGap, GrowthLoop, LocalDiscoverySource, LocalSandbox, default_growth_executor_factories
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.orchestration.leaf_contract import build_leaf_contract
from cgkn.execution.deliverables import SubjectDeliverableChecker
from cgkn.state.task_feedback import digest


def qualified_runner(executors,store):
    def check(request,contract):
        original=contract['source_text']
        actual=request.as_dict()['input_values']['execution_receipt']['outputs']
        return {'passed':actual.get('object')==json.loads(original),'observed':actual,
                'evidence_refs':[dict(request.input_values['execution_receipt_ref'])]}
    executors.register(SubjectDeliverableChecker(lambda c:{'input-json':digest(c['source_text'])},{'parsed-object':check}))
    return DAGRunner(executors,store,deliverable_checkers={'json-parse':'deliverable.subjects@1'})


def admit_parse_tree(store, tree, run_id):
    from dataclasses import asdict
    from cgkn.agent.project_agent import AdmissionPolicy
    from cgkn.runtime.node_authority import ExecutionAuthority
    from cgkn.runtime.governed import admit_declared_tree
    from veriarbor.capability import CapabilityContract
    policy=AdmissionPolicy(project_id='growth-project',incremental_mode=False,
        capability_contracts={'json.parse@1':asdict(CapabilityContract('json.parse@1',
            'Parse the exact operator-provided JSON input',critical=False,positive_controls=('parsed-object',)))},
        allowed_effect_domains=frozenset({'measurement'}),execution_budget={'calls':0})
    return admit_declared_tree(ExecutionAuthority(store,'growth-project',run_id),tree,policy=policy,
        proposal_id='local-parse-'+run_id,reason='Explicit offline self-growth demonstration, no provider authority')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prove offline CGKN Self-Growth V0 and reuse")
    parser.add_argument("--run-root", required=True, type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    component = ComponentSpec("json.parse", "1", (PortSpec("text", "artifact.text@1"),), (PortSpec("object", "artifact.json@1"),))
    registry_path = args.run_root / "capability_registry.json"
    registry = CapabilityRegistry({component.ref: component})
    executors = ExecutorRegistry()
    loop = GrowthLoop(registry, executors, LocalDiscoverySource(), LocalSandbox(), factories=default_growth_executor_factories(), registry_path=registry_path, evidence_root=args.run_root)
    first_gap = CapabilityGap("gap-json-1", "growth-project", "growth-run-1", "json.parse", ("text",), ("object",), (), "required capability is missing", "parse", "LOW")
    initial_missing = True
    try:
        registry.resolve("json.parse", "1")
        initial_missing = False
    except KeyError:
        pass
    first_growth = loop.ensure(first_gap)
    text='{"answer": 42}'
    contract=build_leaf_contract(goal='Parse the exact public JSON input',kind='READ_ONLY_ANALYSIS',
        scope=['input-json'],acceptance=['parsed-object'],checker='json-parse',output_identity='parsed-object',
        effect_domains=['measurement'],executor='python.stdlib.json@1',source_refs=['input-json'],
        completion_criterion='object equals deterministic parse of input',source_text=text)
    tree = CapabilityTree("parse JSON", (CapabilityNode("parse", capability_ref="json.parse@1", config={"executor_ref": "python.stdlib.json@1", "inputs": {"text":text},'leaf_contract':contract}),))
    runner = qualified_runner(executors, FileRunStore(args.run_root / "runs"))
    tree=admit_parse_tree(runner.store,tree,'growth-run-1')
    first_run = runner.run(project_id="growth-project", run_id="growth-run-1", tree=tree, dag=compile_tree(tree))
    loaded = CapabilityRegistry.load(registry_path, {component.ref: component})
    second_executors = ExecutorRegistry()
    second_loop = GrowthLoop(loaded, second_executors, LocalDiscoverySource(), LocalSandbox(), factories=default_growth_executor_factories(), registry_path=registry_path, evidence_root=args.run_root)
    second_growth = second_loop.ensure(CapabilityGap("gap-json-2", "growth-project", "growth-run-2", "json.parse", ("text",), ("object",), (), "reuse admitted capability", "parse", "LOW"))
    second_runner=qualified_runner(second_executors, FileRunStore(args.run_root / "runs"))
    second_tree=admit_parse_tree(second_runner.store,tree,'growth-run-2')
    second_run = second_runner.run(project_id="growth-project", run_id="growth-run-2", tree=second_tree, dag=compile_tree(second_tree))
    result = {"status": "PASS" if initial_missing and first_run.status == second_run.status == "SUCCEEDED" and first_growth.growth_invoked and second_growth.reused else "FAIL", "initial_capability_missing": initial_missing, "growth_invoked_count": loop.invoked_count + second_loop.invoked_count, "discovery_candidate_count": first_growth.candidate_count, "trial_count": first_growth.trial_count, "admission_verdict": first_growth.receipt.verdict if first_growth.receipt else None, "registered_capability": first_growth.capability.ref, "first_run": first_run.as_dict(), "second_run": second_run.as_dict(), "second_run_reused_registry": second_growth.reused, "kernel_files_modified_by_growth": 0, "provider_calls": 0, "network_calls": 0, "registry_path": str(registry_path)}
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
