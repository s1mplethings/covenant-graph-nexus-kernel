from __future__ import annotations

import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.application.software_project.snapshot import ProjectSnapshotExecutor, snapshot_project
from cgkn.executors import CommandExecutor, ExecutorRegistry, PythonTestExecutor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.orchestration.tree_edits import TreeEdit, apply_tree_edits
from cgkn.providers import CompletionClient, ModelRoleConfig, OpenAICompatibleClient, parse_json_object
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .canonical import canonical_hash
from .case import WorkUnit, case_and_units, project_contract, structure_payload
from .designs import get_design
from .executor import SemanticWorkUnitExecutor
from .failure import FailureAttributor
from .interface import PythonInterfaceExtractor


PLAN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["decision_id", "accepted", "unit_order", "rationale"], "properties": {
    "decision_id": {"type": "string"}, "accepted": {"type": "boolean"}, "unit_order": {"type": "array", "items": {"type": "string"}}, "rationale": {"type": "string"}}}
REPAIR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["decision_id", "target_unit", "reason"], "properties": {
    "decision_id": {"type": "string"}, "target_unit": {"type": "string"}, "reason": {"type": "string"}}}


@dataclass(frozen=True)
class ExperimentResult:
    design: str
    case_id: str
    run_id: str
    status: str
    receipt: Mapping[str, Any]
    run_dir: pathlib.Path


class SemanticExperimentRunner:
    def __init__(self, repository_root: pathlib.Path | str, artifact_root: pathlib.Path | str, *, client: CompletionClient | None = None, config: Mapping[str, Any] | None = None):
        self.root = pathlib.Path(repository_root).resolve()
        self.artifact_root = pathlib.Path(artifact_root).resolve()
        self.client = client or OpenAICompatibleClient()
        base = json.loads((self.root / "config/software_project_generation.json").read_text(encoding="utf-8"))
        self.config = base | dict(config or {})
        self.acceptance_root = self.root / "benchmarks/real_project_generation/acceptance"

    def run(self, design_id: str, case_id: str, *, profile: str = "unspecified") -> ExperimentResult:
        started = time.perf_counter()
        design = get_design(design_id)
        case, units = case_and_units(case_id)
        run_id = f"{case_id}-{design_id.lower()}-{uuid.uuid4().hex[:12]}"
        run_dir = self.artifact_root / f"design_{design_id.lower()}" / run_id
        workspace = run_dir / "workspace"
        run_dir.mkdir(parents=True, exist_ok=False)
        if case.seeded_fixture: shutil.copytree(self.root / case.seeded_fixture, workspace)
        else: workspace.mkdir()
        high = self._role("agent", self.config["high_capability_agent"])
        worker = self._role("worker", self.config["cheap_worker"])
        project = design.create("project.contract@1", case.case_id, project_contract(case), producer_ref="public-case")
        structure = design.create("project.structure@1", case.case_id, structure_payload(units), producer_ref="experiment", inputs=(project.artifact_id,))
        unit_artifacts = {unit.unit_id: design.create("work_unit.contract@1", f"{case.case_id}:{unit.unit_id}", unit.as_payload(), inputs=(project.artifact_id, structure.artifact_id)) for unit in units}
        test_contract_payload = {"test_paths": [path for unit in units if unit.role == "tests" for path in unit.paths] or ["test_math_utils.py"], "requirements": list(case.public_acceptance)}
        test_contract = design.create("test.contract@1", case.case_id, test_contract_payload, inputs=(project.artifact_id,))
        design.validate_graph((project, structure, *unit_artifacts.values(), test_contract))
        artifacts = {"project": design.as_dict(project), "structure": design.as_dict(structure), "units": {key: design.as_dict(value) for key, value in unit_artifacts.items()}, "test_contract": design.as_dict(test_contract)}
        self._write(run_dir / "semantic_inputs.json", artifacts)
        initial = self._pytest(workspace) if case.seeded_fixture else None
        failure_artifact = None
        agent_usage: list[dict[str, Any]] = []
        agent_calls = 0
        if initial and initial["status"] == "FAIL":
            tree = self._build_tree(case, units, artifacts, workspace, design_id, worker)
            initial_tree_hash = canonical_hash(tree.as_dict())
            failure = FailureAttributor().attribute(stdout=initial["stdout"], stderr=initial["stderr"], returncode=initial["returncode"], manifests=PythonInterfaceExtractor().extract_path(workspace), project_contract=project_contract(case), test_contract=test_contract_payload, units={unit.unit_id: unit.paths for unit in units})
            failure_artifact = design.create("failure.evidence@1", case.case_id, failure, producer_ref="pytest", inputs=(test_contract.artifact_id,))
            directive, usage = self._repair_decision(design_id, failure_artifact, units, high)
            agent_calls += 1; agent_usage.append(usage)
            repair_artifact = design.create("repair.directive@1", case.case_id, {"target_unit": directive["target_unit"], "reason": directive["reason"], "allowed_paths": list(next(item.paths for item in units if item.unit_id == directive["target_unit"]))}, producer_ref="agent", inputs=(failure_artifact.artifact_id,))
            tree = self._attach_repair(tree, directive["target_unit"], design.as_dict(failure_artifact), design.as_dict(repair_artifact))
            repair_rounds = 1
        else:
            plan, usage = self._plan(design_id, artifacts, units, high)
            agent_calls += 1; agent_usage.append(usage)
            ordered = tuple(next(item for item in units if item.unit_id == unit_id) for unit_id in plan["unit_order"])
            tree = self._build_tree(case, ordered, artifacts, workspace, design_id, worker)
            initial_tree_hash = canonical_hash(tree.as_dict())
            repair_rounds = 0
        store = FileRunStore(run_dir)
        registry = ExecutorRegistry()
        registry.register(SemanticWorkUnitExecutor(workspace, self.client, worker))
        registry.register(CommandExecutor(workspace)); registry.register(PythonTestExecutor(workspace))
        registry.register(ProjectSnapshotExecutor(workspace)); registry.register(ExternalAcceptanceExecutor(workspace, self.acceptance_root))
        runner = DAGRunner(registry, store)
        summary = runner.run(project_id=case.case_id, run_id=run_id, tree=tree, dag=compile_tree(tree), constraints=tuple(project_contract(case)["constraints"]))
        whole_replans = 0
        while summary.status != "SUCCEEDED" and repair_rounds < 2:
            failed = summary.failed_nodes[0] if summary.failed_nodes else summary.blocked_nodes[0]
            result = store.load_result(case.case_id, run_id, failed)
            output = dict(result.outputs)
            manifests = PythonInterfaceExtractor().extract_path(workspace)
            failure = FailureAttributor().attribute(stdout=str(output.get("stdout", "")), stderr=str(output.get("stderr", result.error.message if result.error else "")), returncode=int(output.get("returncode", 1)), manifests=manifests, project_contract=project_contract(case), test_contract=test_contract_payload, units={unit.unit_id: unit.paths for unit in units}, phase="runtime" if failed == "runtime-smoke" else "pytest")
            if failed in unit_artifacts: failure["allowed_repair_units"] = [failed]
            failure_artifact = design.create("failure.evidence@1", case.case_id, failure, producer_ref=failed, inputs=(test_contract.artifact_id,), revision=repair_rounds + 1)
            directive, usage = self._repair_decision(design_id, failure_artifact, units, high)
            agent_calls += 1; agent_usage.append(usage)
            repair_artifact = design.create("repair.directive@1", case.case_id, {"target_unit": directive["target_unit"], "reason": directive["reason"], "allowed_paths": list(next(item.paths for item in units if item.unit_id == directive["target_unit"]))}, producer_ref="agent", inputs=(failure_artifact.artifact_id,), revision=repair_rounds + 1)
            tree = self._attach_repair(tree, directive["target_unit"], design.as_dict(failure_artifact), design.as_dict(repair_artifact))
            summary = runner.run(project_id=case.case_id, run_id=run_id, tree=tree, dag=compile_tree(tree), resume=True, retry_node=directive["target_unit"], constraints=tuple(project_contract(case)["constraints"]))
            repair_rounds += 1
        receipt = self._receipt(design_id, case_id, run_id, run_dir, workspace, tree, initial_tree_hash, summary, store, initial, agent_calls, agent_usage, repair_rounds, whole_replans, started) | {"profile": profile}
        unhashed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        receipt = unhashed | {"receipt_hash": canonical_hash(unhashed)}
        self._write(run_dir / "experiment_receipt.json", receipt)
        return ExperimentResult(design_id, case_id, run_id, receipt["final_status"], receipt, run_dir)

    def _plan(self, design_id: str, artifacts: Mapping[str, Any], units: tuple[WorkUnit, ...], config: ModelRoleConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        prompt = {"design": design_id, "semantic_artifacts": artifacts, "allowed_unit_ids": [item.unit_id for item in units], "rule": "choose every cohesive unit exactly once; do not output source"}
        completion = self.client.complete(system="You are the project composition Agent. Confirm and order the declared cohesive interface units using semantic artifacts. Do not write source or invent units.", user=json.dumps(prompt, ensure_ascii=False, sort_keys=True), schema_name="semantic_experiment_plan", schema=PLAN_SCHEMA, config=config)
        value = parse_json_object(completion.text)
        if not value.get("accepted") or set(value.get("unit_order", [])) != {item.unit_id for item in units} or len(value["unit_order"]) != len(units): raise ValueError("Agent plan violated cohesive unit contract")
        return value, {"request_id": completion.request_id, "usage": dict(completion.usage), "attempts": completion.attempts}

    def _repair_decision(self, design_id: str, failure_artifact: Any, units: tuple[WorkUnit, ...], config: ModelRoleConfig) -> tuple[dict[str, Any], dict[str, Any]]:
        rendered = get_design(design_id).as_dict(failure_artifact)
        allowed = list(failure_artifact.payload["allowed_repair_units"])
        prompt = {"design": design_id, "failure_evidence": rendered, "allowed_repair_units": allowed, "existing_unit_ids": [item.unit_id for item in units], "rule": "select one existing affected unit; never replan the tree"}
        completion = self.client.complete(system="You are the repair Agent. Select exactly one existing affected cohesive unit from structured FailureEvidence. Do not write code or create a new plan.", user=json.dumps(prompt, ensure_ascii=False, sort_keys=True), schema_name="semantic_experiment_repair", schema=REPAIR_SCHEMA, config=config)
        value = parse_json_object(completion.text)
        if value.get("target_unit") not in allowed: raise ValueError("repair Agent selected an unattributed unit")
        return value, {"request_id": completion.request_id, "usage": dict(completion.usage), "attempts": completion.attempts}

    def _build_tree(self, case: Any, units: tuple[WorkUnit, ...], artifacts: Mapping[str, Any], workspace: pathlib.Path, design_id: str, worker: ModelRoleConfig) -> CapabilityTree:
        nodes = []
        by_unit = {item.unit_id: item for item in units}
        for unit in units:
            dep_paths = [path for dep in unit.dependencies for path in by_unit[dep].paths]
            config = {"executor_ref": "experiment.semantic-worker@1", "goal": "; ".join(unit.responsibilities), "design_id": design_id,
                      "project_contract": artifacts["project"], "work_unit_contract": artifacts["units"][unit.unit_id],
                      "target_paths": list(unit.paths), "allowed_paths": list(dict.fromkeys((*unit.paths, *dep_paths))),
                      "protected_paths": [".git", ".github", ".cgkn", "benchmarks", "artifacts", "governance", "cgkn"],
                      "max_actions": 7, "max_write_files": 5, "max_total_output_bytes": 64000,
                      "allow_create": not bool(case.seeded_fixture), "allow_patch": True, "allow_delete": False,
                      "acceptance": list(case.public_acceptance), "timeout_seconds": worker.timeout_seconds}
            nodes.append(CapabilityNode(unit.unit_id, capability_ref="semantic.work-unit@1", depends_on=unit.dependencies, config=config))
        worker_ids = tuple(item.unit_id for item in units)
        compile_node = CapabilityNode("compile", capability_ref="project.python.compile@1", depends_on=worker_ids, config={"executor_ref": "local.command@1", "goal": "compile", "command": [sys.executable, "-m", "compileall", "-q", "."], "timeout_seconds": 60})
        pytest_node = CapabilityNode("pytest", capability_ref="project.python.pytest@1", depends_on=("compile",), config={"executor_ref": "local.python-test@1", "goal": "public pytest", "pytest_args": ["-q"], "timeout_seconds": 60})
        command = ([sys.executable, "-c", "from math_utils import add; assert add(2, 3) == 5"]
                   if case.case_id == "seeded_repair" else [sys.executable, *case.runtime_command[1:]])
        smoke = CapabilityNode("runtime-smoke", capability_ref="project.command.smoke@1", depends_on=("compile",), config={"executor_ref": "local.command@1", "goal": "runtime smoke", "command": command, "timeout_seconds": 60})
        snapshot = CapabilityNode("snapshot", capability_ref="project.snapshot@1", depends_on=("pytest", "runtime-smoke"), config={"executor_ref": "project.snapshot@1", "goal": "snapshot", "entrypoints": [case.entrypoint], "test_commands": [f"{sys.executable} -m pytest -q"], "runtime_commands": [" ".join(command)]})
        acceptance = CapabilityNode("accept", capability_ref="project.acceptance.external@1", depends_on=("snapshot",), config={"executor_ref": "project.acceptance@1", "goal": "external acceptance", "case_id": case.case_id, "timeout_seconds": 60})
        return CapabilityTree(case.public_goal, tuple(nodes + [compile_node, pytest_node, smoke, snapshot, acceptance]))

    @staticmethod
    def _attach_repair(tree: CapabilityTree, target: str, failure: Mapping[str, Any], directive: Mapping[str, Any]) -> CapabilityTree:
        edits = (TreeEdit(f"repair-config-{uuid.uuid4().hex[:8]}", "update_config", target, {"config": {"failure_evidence": dict(failure), "repair_directive": dict(directive), "allow_create": False, "allow_patch": True}}, {"authority": "semantic-experiment-agent"}),
                 TreeEdit(f"repair-retry-{uuid.uuid4().hex[:8]}", "retry_node", target, {}, {"authority": "semantic-experiment-agent"}))
        known = {node.capability_ref for node in tree.nodes if node.capability_ref}
        return apply_tree_edits(tree, edits, known_capabilities=known)

    def _receipt(self, design: str, case_id: str, run_id: str, run_dir: pathlib.Path, workspace: pathlib.Path, tree: CapabilityTree, initial_tree_hash: str, summary: Any, store: FileRunStore, initial: Any, agent_calls: int, agent_usage: list[dict[str, Any]], repair_rounds: int, whole_replans: int, started: float) -> dict[str, Any]:
        worker_usage, interface_violations, scope_violations, context_chars = [], 0, 0, 0
        for node in tree.nodes:
            try:
                value = store.load_result(case_id, run_id, node.id).as_dict()
            except Exception:
                continue
            usage = value.get("usage", {})
            if node.config.get("executor_ref") == "experiment.semantic-worker@1": worker_usage.append(usage)
            message = str((value.get("error") or {}).get("message", ""))
            interface_violations += int("breaking interface" in message)
            scope_violations += int("scope" in message or "path" in message and value.get("status") == "FAILED")
            context_chars += int(usage.get("context_chars", 0))
        hidden = "FAIL"; snapshot_hash = ""
        try:
            hidden = str(store.load_result(case_id, run_id, "accept").outputs.get("status", "FAIL"))
            snapshot_hash = str(store.load_result(case_id, run_id, "snapshot").outputs.get("snapshot_hash", ""))
        except Exception:
            pass
        agent_tokens = sum(int(item["usage"].get("total_tokens", 0)) for item in agent_usage)
        worker_tokens = sum(int(item.get("total_tokens", 0)) for item in worker_usage)
        provider_calls = agent_calls + sum(int(item.get("proposal_attempts", 0)) for item in worker_usage)
        final = "PASS" if summary.status == "SUCCEEDED" and hidden == "PASS" else "FAIL"
        receipt = {"kind": "CGKNSemanticArtifactExperimentRun", "schema_version": "1.0", "design": design, "case_id": case_id, "run_id": run_id,
                   "final_status": final, "agent_model": self.config["high_capability_agent"]["model"], "worker_model": self.config["cheap_worker"]["model"],
                   "agent_calls": agent_calls, "worker_calls": len(worker_usage), "provider_calls": provider_calls, "tokens": agent_tokens + worker_tokens,
                   "wall_time_ms": int((time.perf_counter() - started) * 1000), "tree_nodes": len(tree.nodes), "dag_nodes": len(compile_tree(tree).nodes),
                   "initial_tree_hash": initial_tree_hash, "final_tree_structure_hash": canonical_hash({"nodes": [{"id": n.id, "capability_ref": n.capability_ref, "depends_on": list(n.depends_on)} for n in tree.nodes]}),
                   "repair_rounds": repair_rounds, "whole_replans": whole_replans, "reused_nodes": list(summary.reused_nodes), "rerun_nodes": list(summary.actual_executions),
                   "interface_violations": interface_violations, "accepted_breaking_changes": 0, "scope_violations": scope_violations, "context_chars": context_chars,
                   "internal_pytest": "PASS" if "pytest" not in summary.failed_nodes and not summary.blocked_nodes else "FAIL", "runtime": "PASS" if "runtime-smoke" not in summary.failed_nodes and "runtime-smoke" not in summary.blocked_nodes else "FAIL",
                   "hidden_acceptance": hidden, "snapshot_hash": snapshot_hash, "initial_test": initial or {}, "manual_edits": 0, "hidden_source_exposed": False,
                   "source_commit": self._git("rev-parse", "HEAD"), "source_tree": self._git("rev-parse", "HEAD^{tree}")}
        return receipt | {"receipt_hash": canonical_hash(receipt)}

    def _role(self, role: str, value: Mapping[str, Any]) -> ModelRoleConfig:
        return ModelRoleConfig(role, str(value["model"]), int(value.get("timeout_seconds", 90)), int(value.get("max_output_tokens", 6000)), float(value.get("temperature", 0.0)), str(value.get("reasoning_effort", "none")))

    @staticmethod
    def _pytest(workspace: pathlib.Path) -> dict[str, Any]:
        env = os.environ.copy(); env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=workspace, text=True, capture_output=True, timeout=60, env=env)
        return {"status": "PASS" if completed.returncode == 0 else "FAIL", "returncode": completed.returncode, "stdout": completed.stdout[-8000:], "stderr": completed.stderr[-8000:]}

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.root, text=True).strip()

    @staticmethod
    def _write(path: pathlib.Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
