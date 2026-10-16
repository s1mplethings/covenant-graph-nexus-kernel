from __future__ import annotations

import pathlib
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.application.software_project.snapshot import ProjectSnapshotExecutor
from cgkn.executors import CommandExecutor, ExecutorRegistry, PythonTestExecutor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.providers import CompletionClient, ModelRoleConfig
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .csv import compile_csv_cleaner
from .execution import ObligationWorkUnitExecutor
from .receipt import write_obligation_preflight
from .test_plan import TestPlanCompiler
from .work_unit import compile_csv_work_units


@dataclass(frozen=True)
class ObligationDAGResult:
    status: str
    project_id: str
    run_id: str
    workspace: pathlib.Path
    summary: Mapping[str, Any]
    provider_calls: int
    wall_time_ms: int


class ObligationDAGService:
    """Application adapter: canonical Kernel DAG execution over obligation work units."""

    def __init__(self, repository_root: pathlib.Path, client: CompletionClient, worker: ModelRoleConfig):
        if worker.role != "worker":
            raise ValueError("obligation DAG requires a worker role")
        self.root, self.client, self.worker = repository_root.resolve(), client, worker

    def run_csv(self, workspace: pathlib.Path, run_root: pathlib.Path) -> ObligationDAGResult:
        started = time.perf_counter()
        workspace, run_root = workspace.resolve(), run_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=True)
        compilation = compile_csv_cleaner()
        if compilation.preflight.as_dict()["status"] != "COMPLETE":
            raise ValueError("obligation preflight must be COMPLETE before Provider execution")
        write_obligation_preflight(run_root / "obligation_preflight.json", compilation.preflight)
        test_plan = TestPlanCompiler().compile(compilation.obligations)
        units = compile_csv_work_units(compilation)
        obligation_by_id = {item.obligation_id: item for item in compilation.obligations.obligations}
        nodes: list[CapabilityNode] = []
        for unit in units:
            nodes.append(CapabilityNode(
                unit.work_unit_id,
                capability_ref="project.obligation-work-unit@1",
                depends_on=unit.depends_on,
                config={
                    "executor_ref": "project.obligation-worker@1",
                    "goal": "; ".join(unit.responsibilities),
                    "work_unit_contract": unit.as_dict(),
                    "obligations": [obligation_by_id[identifier].as_dict() for identifier in unit.obligation_ids],
                    "dependency_policy": compilation.obligations.obligations[0].dependency_policy.as_dict() if compilation.obligations.obligations[0].dependency_policy else next(item.dependency_policy.as_dict() for item in compilation.obligations.obligations if item.dependency_policy),
                    "test_plan": test_plan.as_dict() if unit.work_unit_id == "WU-TESTS" else {},
                    "interface_manifest": {"required": list(unit.required_interfaces), "preserved": list(unit.preserved_interfaces)},
                },
            ))
        worker_ids = tuple(item.work_unit_id for item in units)
        nodes.extend((
            CapabilityNode("compile", capability_ref="project.python.compile@1", depends_on=worker_ids, config={"executor_ref": "local.command@1", "goal": "compile", "command": [sys.executable, "-m", "compileall", "-q", "."], "timeout_seconds": 60}),
            CapabilityNode("pytest", capability_ref="project.python.pytest@1", depends_on=("compile",), config={"executor_ref": "local.python-test@1", "goal": "public pytest", "pytest_args": ["-q"], "timeout_seconds": 60}),
            CapabilityNode("runtime", capability_ref="project.command.smoke@1", depends_on=("compile",), config={"executor_ref": "local.command@1", "goal": "runtime", "command": [sys.executable, "-m", "csv_cleaner", "--help"], "timeout_seconds": 60}),
            CapabilityNode("snapshot", capability_ref="project.snapshot@1", depends_on=("pytest", "runtime"), config={"executor_ref": "project.snapshot@1", "goal": "snapshot", "entrypoints": ["csv_cleaner/__main__.py"], "test_commands": [f"{sys.executable} -m pytest -q"], "runtime_commands": [f"{sys.executable} -m csv_cleaner --help"]}),
            CapabilityNode("accept", capability_ref="project.acceptance.external@1", depends_on=("snapshot",), config={"executor_ref": "project.acceptance@1", "goal": "hidden acceptance", "case_id": "cli_csv_cleaner", "dependency_policy": next(item.dependency_policy.as_dict() for item in compilation.obligations.obligations if item.dependency_policy), "timeout_seconds": 60}),
        ))
        tree = CapabilityTree("execute compiled CSV obligations", tuple(nodes))
        registry = ExecutorRegistry()
        registry.register(ObligationWorkUnitExecutor(workspace, self.client, self.worker))
        registry.register(CommandExecutor(workspace)); registry.register(PythonTestExecutor(workspace))
        registry.register(ProjectSnapshotExecutor(workspace)); registry.register(ExternalAcceptanceExecutor(workspace, self.root / "benchmarks" / "real_project_generation" / "acceptance"))
        run_id = f"csv-obligation-{uuid.uuid4().hex[:10]}"
        store = FileRunStore(run_root)
        summary = DAGRunner(registry, store).run(
            project_id="cli_csv_cleaner", run_id=run_id, tree=tree, dag=compile_tree(tree),
            constraints=("compiled obligations are authoritative", "no hidden acceptance access", "no outbound network"),
        )
        hidden = "FAIL"
        try:
            hidden = str(store.load_result("cli_csv_cleaner", run_id, "accept").outputs.get("status", "FAIL"))
        except Exception:
            pass
        status = "PASS" if summary.status == "SUCCEEDED" and hidden == "PASS" else "FAIL"
        calls = len(getattr(self.client, "calls", ()))
        return ObligationDAGResult(status, "cli_csv_cleaner", run_id, workspace, summary.as_dict(), calls, int((time.perf_counter() - started) * 1000))
