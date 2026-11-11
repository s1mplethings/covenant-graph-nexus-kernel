from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.executors import CommandExecutor, ExecutorRegistry, FileExecutor, LocalActionExecutorAdapter, PythonTestExecutor
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


def load_tree(path: pathlib.Path) -> tuple[CapabilityTree, str, pathlib.Path]:
    value = json.loads(path.read_text(encoding="utf-8"))
    tree = CapabilityTree(str(value["goal"]), tuple(CapabilityNode(id=str(node["id"]), parent_id=str(node.get("parent_id", "")), capability_ref=str(node.get("capability_ref", "")), depends_on=tuple(node.get("depends_on", ())), config=dict(node.get("config", {}))) for node in value["nodes"]))
    return tree, str(value.get("run_id", "run-" + uuid.uuid4().hex[:12])), (path.parent / str(value.get("project_root", "workspace"))).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute the canonical CGKN MVP CapabilityTree runtime")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--tree", type=pathlib.Path, required=True)
    parser.add_argument("--run-root", type=pathlib.Path, required=True)
    parser.add_argument("--project-root", type=pathlib.Path, help="override the fixture workspace directory")
    parser.add_argument("--executor-config", type=pathlib.Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-node")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    tree, run_id, project_root = load_tree(args.tree.resolve())
    project_root = args.project_root.resolve() if args.project_root else project_root
    project_root.mkdir(parents=True, exist_ok=True)
    registry = ExecutorRegistry()
    for executor in (LocalActionExecutorAdapter(project_root), CommandExecutor(project_root), PythonTestExecutor(project_root), FileExecutor(project_root)):
        registry.register(executor)
    from cgkn.execution.checker_bindings import install_file_checks
    if not args.executor_config:
        raise ValueError('independent checker bindings required via --executor-config')
    bindings=install_file_checks(registry,project_root,json.loads(args.executor_config.read_text(encoding='utf-8')))
    from dataclasses import asdict, replace
    from cgkn.agent.project_agent import AdmissionPolicy
    from cgkn.runtime.node_authority import ExecutionAuthority
    from cgkn.runtime.governed import admit_declared_tree
    from veriarbor.capability import CapabilityContract
    # This operator-selected local graph is an explicit batch proposal, not a
    # model planning route. Map historical effect labels by registered executor.
    effects={'local.file@1':'filesystem','local.command@1':'local_process','local.python-test@1':'local_process'}
    nodes=[];contracts={}
    for node in tree.nodes:
        if not node.executable:nodes.append(node);continue
        cfg=node.as_dict()['config'];ref=cfg['executor_ref']
        effect=effects.get(ref)
        if ref=='local.action@1':
            action=cfg.get('action')
            effect='filesystem' if action in {'write_file','read_file','list_files'} else 'local_process' if action=='run_command' else None
        if effect is None:raise ValueError('LOCAL_ENTRY_EXECUTOR_NOT_AUTHORIZED: '+ref)
        leaf=dict(cfg['leaf_contract']);leaf['effect_domains']=[effect];cfg['leaf_contract']=leaf
        contracts[node.capability_ref]=asdict(CapabilityContract(node.capability_ref,leaf['leaf_goal'],
            critical=False,positive_controls=tuple(leaf['acceptance']),
            evidence_requirements={'allow_imported_unmanaged':True}))
        nodes.append(replace(node,config=cfg))
    tree=replace(tree,nodes=tuple(nodes));store=FileRunStore(args.run_root)
    policy=AdmissionPolicy(project_id=args.project_id,capability_contracts=contracts,incremental_mode=False,
        allowed_effect_domains=frozenset(effects.values()),execution_budget={'calls':0})
    tree=admit_declared_tree(ExecutionAuthority(store,args.project_id,run_id),tree,policy=policy,
        proposal_id='operator-'+uuid.uuid4().hex,reason='Explicit local CLI tree and checker bindings',retry_node=args.retry_node)
    summary = DAGRunner(registry, store,deliverable_checkers=bindings).run(project_id=args.project_id, run_id=run_id, tree=tree, dag=compile_tree(tree), resume=args.resume or bool(args.retry_node), retry_node=args.retry_node)
    rendered = json.dumps(summary.as_dict(), indent=2, sort_keys=True)
    print(rendered if args.json else f"{summary.status}: {summary.run_id} ({len(summary.actual_executions)} executed, {len(summary.reused_nodes)} reused)")
    return 0 if summary.status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
