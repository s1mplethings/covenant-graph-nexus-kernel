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
    parser.add_argument("--executor-config", type=pathlib.Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-node")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    tree, run_id, project_root = load_tree(args.tree.resolve())
    project_root.mkdir(parents=True, exist_ok=True)
    registry = ExecutorRegistry()
    for executor in (LocalActionExecutorAdapter(project_root), CommandExecutor(project_root), PythonTestExecutor(project_root), FileExecutor(project_root)):
        registry.register(executor)
    summary = DAGRunner(registry, FileRunStore(args.run_root)).run(project_id=args.project_id, run_id=run_id, tree=tree, dag=compile_tree(tree), resume=args.resume or bool(args.retry_node), retry_node=args.retry_node)
    rendered = json.dumps(summary.as_dict(), indent=2, sort_keys=True)
    print(rendered if args.json else f"{summary.status}: {summary.run_id} ({len(summary.actual_executions)} executed, {len(summary.reused_nodes)} reused)")
    return 0 if summary.status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
