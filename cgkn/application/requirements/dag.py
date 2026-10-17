from __future__ import annotations

import pathlib
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.application.software_project.snapshot import ProjectSnapshotExecutor
from cgkn.application.materialization import materialize_json
from cgkn.executors import CommandExecutor, ExecutorRegistry, PythonTestExecutor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edits
from cgkn.providers import CompletionClient, ModelRoleConfig
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .csv import compile_csv_cleaner
from .notes import compile_local_json_notes
from .execution import ObligationWorkUnitExecutor
from .receipt import write_obligation_preflight
from .work_unit import compile_csv_work_units, compile_notes_work_units


@dataclass(frozen=True)
class ObligationDAGResult:
    status: str
    project_id: str
    run_id: str
    workspace: pathlib.Path
    summary: Mapping[str, Any]
    provider_calls: int
    tokens: int
    wall_time_ms: int
    repair_rounds: int
    hidden_acceptance: str
    manual_edits: int = 0
    whole_replans: int = 0
    public_pytest: str = "FAIL"
    oracle_status: str = "NOT_EVALUATED"
    oracle_evidence: tuple[Mapping[str, Any], ...] = ()
    repair_owners: tuple[str, ...] = ()
    reused_work_units: tuple[str, ...] = ()
    contract_test_status: str = "NOT_EVALUATED"
    contract_test_reused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": "COMPOSED_DAG", "status": self.status, "project_id": self.project_id,
            "run_id": self.run_id, "workspace": str(self.workspace), "provider_calls": self.provider_calls,
            "tokens": self.tokens, "wall_time_ms": self.wall_time_ms, "repair_rounds": self.repair_rounds,
            "hidden_acceptance": self.hidden_acceptance, "manual_edits": self.manual_edits,
            "whole_replans": self.whole_replans, "public_pytest": self.public_pytest,
            "oracle_status": self.oracle_status, "oracle_evidence": materialize_json(self.oracle_evidence),
            "repair_owners": list(self.repair_owners), "reused_work_units": list(self.reused_work_units),
            "contract_test_status": self.contract_test_status, "contract_test_reused": self.contract_test_reused,
            "summary": materialize_json(self.summary),
        }


class ObligationDAGService:
    """Application adapter: canonical Kernel DAG execution over obligation work units."""

    def __init__(self, repository_root: pathlib.Path, client: CompletionClient, worker: ModelRoleConfig):
        if worker.role != "worker":
            raise ValueError("obligation DAG requires a worker role")
        self.root, self.client, self.worker = repository_root.resolve(), client, worker

    def run_csv(self, workspace: pathlib.Path, run_root: pathlib.Path) -> ObligationDAGResult:
        return self._run(workspace, run_root, "csv")

    def run_notes(self, workspace: pathlib.Path, run_root: pathlib.Path) -> ObligationDAGResult:
        return self._run(workspace, run_root, "notes")

    def _run(self, workspace: pathlib.Path, run_root: pathlib.Path, variant: str) -> ObligationDAGResult:
        started = time.perf_counter()
        workspace, run_root = workspace.resolve(), run_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        run_root.mkdir(parents=True, exist_ok=True)
        notes = variant == "notes"
        compilation = compile_local_json_notes() if notes else compile_csv_cleaner()
        project_id = "local_json_notes" if notes else "cli_csv_cleaner"
        entrypoint = "notes" if notes else "csv_cleaner"
        entrypoint_path = f"{entrypoint}/__main__.py"
        from cgkn.application.interfaces import InterfaceContractCompiler
        from cgkn.application.verification import (
            ContractTestCompilerExecutor, EvidenceComparator, ObligationOracleExecutorAdapter, OracleEvidence,
            OraclePlanCompiler, OracleStatus, PublicTestEvidence, PublicTestStatus,
        )
        if compilation.preflight.as_dict()["status"] != "COMPLETE":
            raise ValueError("obligation preflight must be COMPLETE before Provider execution")
        write_obligation_preflight(run_root / "obligation_preflight.json", compilation.preflight)
        dependency_policy = next(item.dependency_policy for item in compilation.obligations.obligations if item.dependency_policy)
        oracle_plan = (OraclePlanCompiler().compile_notes(compilation.obligations, dependency_policy) if notes
                       else OraclePlanCompiler().compile_csv(compilation.obligations, dependency_policy))
        interface_contracts = (InterfaceContractCompiler().compile_notes(compilation.obligations) if notes
                               else InterfaceContractCompiler().compile_csv(compilation.obligations))
        units = (compile_notes_work_units(compilation) if notes
                 else tuple(item for item in compile_csv_work_units(compilation) if item.work_unit_id != "WU-TESTS"))
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
                    "interface_manifest": {"required": list(unit.required_interfaces), "preserved": list(unit.preserved_interfaces)},
                    "executable_interface_contracts": [interface_contracts.by_id(identifier).as_dict() for identifier in unit.interface_contract_refs],
                    "dependency_interface_contracts": ([interface_contracts.by_id(identifier).as_dict() for identifier in (
                        "INTERFACE-NOTES-ADD-001", "INTERFACE-NOTES-LIST-001", "INTERFACE-NOTES-SHOW-001", "INTERFACE-NOTES-DELETE-001"
                    )] if notes and unit.work_unit_id == "WU-CLI" else []),
                    "interface_contract_set_hash": interface_contracts.interface_contract_set_hash,
                },
            ))
        worker_ids = tuple(item.work_unit_id for item in units)
        nodes.extend((
            CapabilityNode("contract-tests", capability_ref="project.contract-test-plan@1", depends_on=worker_ids, config={"executor_ref": "project.contract-test-compiler@1", "goal": "compile canonical contract tests", "obligation_set": compilation.obligations.as_dict(), "oracle_plan": oracle_plan.as_dict(), "dependency_policies": [dependency_policy.as_dict()]}),
            CapabilityNode("compile", capability_ref="project.python.compile@1", depends_on=("contract-tests",), config={"executor_ref": "local.command@1", "goal": "compile", "command": [sys.executable, "-m", "compileall", "-q", "."], "timeout_seconds": 60}),
            CapabilityNode("pytest", capability_ref="project.python.pytest@1", depends_on=("compile",), config={"executor_ref": "local.python-test@1", "goal": "public pytest", "pytest_args": ["-q"], "timeout_seconds": 60}),
            CapabilityNode("runtime", capability_ref="project.command.smoke@1", depends_on=("compile",), config={"executor_ref": "local.command@1", "goal": "runtime", "command": [sys.executable, "-m", entrypoint, "--help"], "timeout_seconds": 60}),
            CapabilityNode("oracle", capability_ref="project.obligation-oracle-plan@1", depends_on=("compile",), config={"executor_ref": "project.obligation-oracle@1", "goal": "deterministic obligation verification", "oracle_plan": oracle_plan.as_dict(), "dependency_policies": [dependency_policy.as_dict()]}),
            CapabilityNode("snapshot", capability_ref="project.snapshot@1", depends_on=("pytest", "runtime", "oracle"), config={"executor_ref": "project.snapshot@1", "goal": "snapshot", "entrypoints": [entrypoint_path], "test_commands": [f"{sys.executable} -m pytest -q"], "runtime_commands": [f"{sys.executable} -m {entrypoint} --help"]}),
            CapabilityNode("accept", capability_ref="project.acceptance.external@1", depends_on=("snapshot",), config={"executor_ref": "project.acceptance@1", "goal": "hidden acceptance", "case_id": project_id, "dependency_policy": next(item.dependency_policy.as_dict() for item in compilation.obligations.obligations if item.dependency_policy), "timeout_seconds": 60}),
        ))
        tree = CapabilityTree(f"execute compiled {variant} obligations", tuple(nodes))
        registry = ExecutorRegistry()
        registry.register(ObligationWorkUnitExecutor(workspace, self.client, self.worker))
        registry.register(ContractTestCompilerExecutor(workspace))
        registry.register(CommandExecutor(workspace)); registry.register(PythonTestExecutor(workspace))
        registry.register(ObligationOracleExecutorAdapter(workspace))
        registry.register(ProjectSnapshotExecutor(workspace)); registry.register(ExternalAcceptanceExecutor(workspace, self.root / "benchmarks" / "real_project_generation" / "acceptance"))
        run_id = f"{variant}-obligation-{uuid.uuid4().hex[:10]}"
        store = FileRunStore(run_root)
        summary = DAGRunner(registry, store).run(
            project_id=project_id, run_id=run_id, tree=tree, dag=compile_tree(tree),
            constraints=("compiled obligations are authoritative", "no hidden acceptance access", "no outbound network"),
        )
        repair_rounds = 0
        repair_owners: list[str] = []
        reused_work_units: set[str] = set()
        while summary.status != "SUCCEEDED" and repair_rounds < 2:
            failed = summary.failed_nodes[0] if summary.failed_nodes else ""
            owner = failed if failed in {item.work_unit_id for item in units} else ""
            failure: Mapping[str, Any]
            if failed in {"pytest", "oracle"} or ({"pytest", "oracle"} & set(summary.failed_nodes)):
                try:
                    oracle_result = store.load_result(project_id, run_id, "oracle")
                    oracle_rows = tuple(OracleEvidence.from_dict(item) for item in oracle_result.outputs.get("evidence", ()))
                except Exception:
                    oracle_rows = ()
                try:
                    pytest_result = store.load_result(project_id, run_id, "pytest")
                    pytest_pass = pytest_result.status.value == "SUCCEEDED"
                    pytest_stdout = str(pytest_result.outputs.get("stdout", ""))
                    pytest_stderr = str(pytest_result.outputs.get("stderr", ""))
                except Exception:
                    pytest_pass, pytest_stdout, pytest_stderr = False, "", "pytest evidence unavailable"
                test_asset_obligations = ({"OBL-NOTES-TEST-PYTEST"} if notes else {"OBL-CSV-PUBLIC-TESTS", "OBL-CSV-TEST-PYTEST"})
                selected = next((
                    item for item in oracle_rows
                    if item.status is not OracleStatus.PASS and not set(item.obligation_ids) <= test_asset_obligations
                ), None)
                if selected is None and pytest_pass:
                    selected = next((item for item in oracle_rows if item.status is not OracleStatus.PASS), None)
                if selected is None:
                    selected = next((item for item in oracle_rows if not set(item.obligation_ids) <= test_asset_obligations), None)
                if selected is not None:
                    setup_failed = "ERROR collecting" in pytest_stdout or "fixture" in (pytest_stdout + pytest_stderr).lower()
                    public = PublicTestEvidence(
                        "EVIDENCE-PUBLIC-PYTEST", PublicTestStatus.PASS if pytest_pass else PublicTestStatus.FAIL,
                        tuple(item.obligation_id for item in compilation.obligations.obligations), ("PUBLIC-PYTEST",),
                        return_code=0 if pytest_pass else 1, stdout_summary=pytest_stdout[-2000:], stderr_summary=pytest_stderr[-2000:],
                        setup_status="FAIL" if setup_failed else "PASS",
                        evidence_authority="CANONICAL_CONTRACT",
                    )
                    attributed = EvidenceComparator().compare(selected, public, dependency_policy=dependency_policy)
                    if notes and selected.oracle_id == "ORACLE-NOTES-STATEFUL":
                        assertion_errors = tuple(str(item) for item in selected.observed.get("assertion_errors", ()))
                        if "step 0: stdout exact mismatch" in assertion_errors:
                            attributed = attributed.with_owner_override("WU-CLI", "the first add command succeeded but violated the frozen CLI stdout contract")
                    owner = attributed.effective_owner or ""
                    failure = attributed.as_dict() | {"failed_node": failed}
                else:
                    failure = {"failed_node": failed, "failure_class": "HARNESS_FAILURE", "allowed_repair_scope": []}
            else:
                result = store.load_result(project_id, run_id, failed)
                failure = {
                    "failed_node": failed,
                    "owner_work_unit": owner,
                    "error": result.error.message if result.error else "validation failed",
                    "stdout": str(result.outputs.get("stdout", ""))[-8000:],
                    "stderr": str(result.outputs.get("stderr", ""))[-8000:],
                    "allowed_repair_scope": list(next(item.target_paths for item in units if item.work_unit_id == owner)) if owner else [],
                }
            if not owner:
                break
            repair_owners.append(owner)
            reused_work_units.add("CONTRACT-TESTS")
            reused_work_units.update(item.work_unit_id for item in units if item.work_unit_id != owner)
            tree = apply_tree_edits(tree, (
                TreeEdit(f"repair-config-{repair_rounds}", "update_config", owner, {"config": {"failure_evidence": failure}}, {"authority": "obligation-dag", "reason": "affected-only repair"}),
                TreeEdit(f"repair-retry-{repair_rounds}", "retry_node", owner, {}, {"authority": "obligation-dag", "reason": "affected-only repair"}),
            ), known_capabilities={node.capability_ref for node in tree.nodes if node.capability_ref})
            summary = DAGRunner(registry, store).run(
                project_id=project_id, run_id=run_id, tree=tree, dag=compile_tree(tree), resume=True,
                retry_node=owner, constraints=("compiled obligations are authoritative", "no hidden acceptance access", "no outbound network"),
            )
            repair_rounds += 1
        hidden = "FAIL"
        public_pytest = "FAIL"
        oracle_status = "NOT_EVALUATED"
        oracle_evidence: tuple[Mapping[str, Any], ...] = ()
        contract_test_status = "NOT_EVALUATED"
        contract_test_reused = False
        try:
            hidden = str(store.load_result(project_id, run_id, "accept").outputs.get("status", "FAIL"))
        except Exception:
            pass
        try:
            public_pytest = "PASS" if store.load_result(project_id, run_id, "pytest").status.value == "SUCCEEDED" else "FAIL"
        except Exception:
            pass
        try:
            oracle_result = store.load_result(project_id, run_id, "oracle")
            oracle_status = str(oracle_result.outputs.get("status", "FAIL"))
            oracle_evidence = tuple(dict(item) for item in oracle_result.outputs.get("evidence", ()))
        except Exception:
            pass
        try:
            contract_test_result = store.load_result(project_id, run_id, "contract-tests")
            contract_test_status = str(contract_test_result.outputs.get("status", "FAIL"))
            contract_test_reused = bool(contract_test_result.outputs.get("reused", False))
        except Exception:
            pass
        status = "PASS" if summary.status == "SUCCEEDED" and hidden == "PASS" and public_pytest == "PASS" and oracle_status == "PASS" else "FAIL"
        calls = len(getattr(self.client, "calls", ()))
        tokens = 0
        for unit in units:
            try:
                tokens += int(store.load_result(project_id, run_id, unit.work_unit_id).usage.get("total_tokens", 0))
            except Exception:
                pass
        return ObligationDAGResult(
            status, project_id, run_id, workspace, summary.as_dict(), calls, tokens,
            int((time.perf_counter() - started) * 1000), repair_rounds, hidden,
            public_pytest=public_pytest, oracle_status=oracle_status, oracle_evidence=oracle_evidence,
            repair_owners=tuple(repair_owners), reused_work_units=tuple(sorted(reused_work_units)),
            contract_test_status=contract_test_status,
            contract_test_reused=contract_test_reused,
        )
