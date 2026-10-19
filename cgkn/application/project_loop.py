from __future__ import annotations

import json
import pathlib
import re
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from cgkn.application.learning import GenerationRequest, ProductionGenerationClient, default_production_client
from cgkn.application.materialization import materialize_json
from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import ScopedFileTransaction
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors import CommandExecutor, ExecutorRegistry, PythonTestExecutor
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.orchestration.invalidation import downstream_closure
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object
from cgkn.runtime import DAGRunner, RunSummary
from cgkn.state import FileRunStore

from .project_blueprint import (
    BlueprintCheck,
    BlueprintStatus,
    BlueprintUnit,
    FailureReport,
    FileBundle,
    ObservedInterfaceManifest,
    PatchBundle,
    ProjectBlueprint,
    UnitKind,
    UnitResult,
    apply_blueprint_edits,
    extract_python_interface,
    interface_breaks,
)


BLUEPRINT_EDIT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["edits"],
    "properties": {"edits": {"type": "array", "minItems": 1, "items": {
        "type": "object", "additionalProperties": False, "required": ["operation", "payload"],
        "properties": {"operation": {"type": "string", "enum": ["set_goal", "add_constraint", "add_unit", "update_unit", "remove_unit", "add_check", "remove_check", "finish_design"]}, "payload": {"type": "object"}},
    }}},
}

_FILE_ITEM = {"type": "object", "additionalProperties": False, "required": ["path", "content"], "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}
_PATCH_ITEM = {"type": "object", "additionalProperties": False, "required": ["path", "find", "replace"], "properties": {"path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}}}
UNIT_PAYLOAD_SCHEMA: dict[str, Any] = {"oneOf": [
    {"type": "object", "additionalProperties": False, "required": ["schema_version", "kind", "unit_id", "files", "summary", "needs_escalation", "escalation_reason"], "properties": {"schema_version": {"const": "1.0"}, "kind": {"const": "file_bundle"}, "unit_id": {"type": "string"}, "files": {"type": "array", "minItems": 1, "maxItems": 5, "items": _FILE_ITEM}, "summary": {"type": "string"}, "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"}}},
    {"type": "object", "additionalProperties": False, "required": ["schema_version", "kind", "unit_id", "patches", "summary", "needs_escalation", "escalation_reason"], "properties": {"schema_version": {"const": "1.0"}, "kind": {"const": "patch_bundle"}, "unit_id": {"type": "string"}, "patches": {"type": "array", "minItems": 1, "maxItems": 5, "items": _PATCH_ITEM}, "summary": {"type": "string"}, "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"}}},
]}


def _write_json(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_sources(root: pathlib.Path, paths: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in paths:
        target = root / pathlib.PurePosixPath(relative)
        if target.is_file(): result[relative] = target.read_text(encoding="utf-8")
    return result


def _manifests(sources: Mapping[str, str]) -> dict[str, ObservedInterfaceManifest]:
    result: dict[str, ObservedInterfaceManifest] = {}
    for relative, source in sources.items():
        if relative.endswith(".py"):
            module = relative[:-3].replace("/", ".").removesuffix(".__init__")
            result[relative] = extract_python_interface(source, module)
    return result


def compile_blueprint(blueprint: ProjectBlueprint, *, case_id: str = "") -> CapabilityTree:
    if blueprint.status not in {BlueprintStatus.FROZEN.value, BlueprintStatus.EXECUTING.value, BlueprintStatus.REPAIRING.value, BlueprintStatus.DONE.value, BlueprintStatus.FAILED.value}:
        raise ValueError("compile_blueprint requires a frozen blueprint")
    nodes: list[CapabilityNode] = []
    for unit in blueprint.units:
        capability = {
            UnitKind.IMPLEMENTATION.value: "project.unit.implementation@1",
            UnitKind.TESTS.value: "project.unit.tests@1",
            UnitKind.DOCUMENTATION.value: "project.unit.documentation@1",
            UnitKind.VERIFICATION.value: "project.unit.verify@1",
            UnitKind.ACCEPTANCE.value: "project.acceptance.external@1",
        }[unit.kind]
        config: dict[str, Any] = {
            "executor_ref": unit.executor_ref, "goal": unit.instruction or unit.purpose,
            "unit": unit.as_dict(), "acceptance": list(unit.acceptance), "effects": list(unit.allowed_effects),
            "timeout_seconds": 120,
        }
        if unit.kind == UnitKind.VERIFICATION.value:
            config["command"] = list(unit.acceptance)
        elif unit.kind == UnitKind.ACCEPTANCE.value:
            config["case_id"] = case_id
        nodes.append(CapabilityNode(unit.unit_id, capability_ref=capability, depends_on=unit.depends_on, config=config))
    for check in blueprint.checks:
        if check.kind == UnitKind.ACCEPTANCE.value:
            nodes.append(CapabilityNode(check.check_id, capability_ref="project.acceptance.external@1", depends_on=check.depends_on, config={"executor_ref": "project.acceptance@1", "case_id": case_id, "goal": "Run external acceptance", "acceptance": list(check.acceptance), "timeout_seconds": 120}))
        else:
            is_pytest = any("pytest" in item for item in check.command)
            nodes.append(CapabilityNode(check.check_id, capability_ref="project.python.pytest@1" if is_pytest else "project.command.verify@1", depends_on=check.depends_on, config={"executor_ref": "local.python-test@1" if is_pytest else "local.command@1", "pytest_args": list(check.command[3:] if len(check.command) >= 3 else ("-q",)) if is_pytest else None, "command": list(check.command), "goal": f"Run {check.check_id}", "acceptance": list(check.acceptance), "timeout_seconds": 120}))
    return CapabilityTree(blueprint.goal, tuple(nodes))


class DesignClient(Protocol):
    def design(self, blueprint: ProjectBlueprint, public_contract: Mapping[str, Any]) -> list[Mapping[str, Any]]: ...


class ProviderBlueprintDesigner:
    def __init__(self, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig):
        if config.role != "agent": raise ValueError("designer requires agent role")
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.config = config
        self.calls: list[dict[str, Any]] = []

    def design(self, blueprint: ProjectBlueprint, public_contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        prompt = {"mode": "DESIGN", "draft": blueprint.as_dict(), "public_contract": dict(public_contract), "rules": {"cohesive_units_not_files": True, "max_provider_units": 3, "max_owned_files_per_unit": 5, "provider_unit_executor": "llm.cheap@1", "deterministic_checks": True, "finish_required": True}}
        generated = self.generation.generate(GenerationRequest(
            task_class="project.compose", operation="COMPOSITION", project_id=blueprint.project_id,
            capability_ref="project.blueprint.design@1", provider_id=self.config.model,
            system="You are the sole project coordinator in DESIGN mode. Return only atomic BlueprintEdit objects. Do not output source code, shell actions, execution state, Candidate metadata, or test claims. Create no more than three cohesive implementation/tests/documentation units, then deterministic compile, pytest, smoke, and external acceptance checks. Every unit field required by the contract must be explicit.",
            goal=prompt, contract={"blueprint": blueprint.as_dict()}, state={}, failure_evidence={},
            schema_name="cgkn_blueprint_edits", schema=BLUEPRINT_EDIT_SCHEMA, model_config=self.config,
            allowed_actions=("set_goal", "add_constraint", "add_unit", "update_unit", "remove_unit", "add_check", "remove_check", "finish_design"),
            forbidden_actions=("source_write", "shell", "test_pass", "candidate_metadata"),
        ))
        self.calls.append({"request_id": generated.completion.request_id, "model": generated.completion.model, "usage": dict(generated.completion.usage), "duration": 0, "role": "coordinator"})
        value = parse_json_object(generated.completion.text)
        edits = value.get("edits")
        if not isinstance(edits, list): raise ValueError("Coordinator omitted BlueprintEdit list")
        return edits


class BlueprintUnitExecutor:
    descriptor = ExecutorDescriptor("llm.cheap@1", "blueprint_unit_worker", ("project.unit.implementation@1", "project.unit.tests@1", "project.unit.documentation@1"), ("filesystem.read", "filesystem.write"), supports_cost_reporting=True)

    def __init__(self, root: pathlib.Path | str, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig):
        if config.role != "worker": raise ValueError("unit executor requires worker role")
        self.root = pathlib.Path(root).resolve()
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.config = config
        self.failure_reports: dict[str, FailureReport] = {}
        self.calls: list[dict[str, Any]] = []

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter(); usage: dict[str, Any] = {}
        try:
            unit = BlueprintUnit.from_dict(request.task_context.node_config["unit"])
            visible = tuple(dict.fromkeys((*unit.owns, *unit.reads)))
            sources = _read_sources(self.root, visible)
            manifests = _manifests(sources)
            failure = self.failure_reports.get(unit.unit_id)
            mode = "REPAIR" if failure else "EXECUTE"
            prompt = {
                "mode": mode, "project_goal": request.task_context.node_goal, "public_constraints": list(request.task_context.project_constraints),
                "unit": unit.as_dict(), "current_files": sources,
                "observed_interfaces": {path: item.as_dict() for path, item in manifests.items()},
                "direct_dependency_results": materialize_json(request.task_context.dependency_results), "acceptance": list(unit.acceptance),
                "failure_report": failure.as_dict() if failure else None,
                "output_contract": "PatchBundle only in REPAIR; FileBundle only in EXECUTE",
            }
            generated = self.generation.generate(GenerationRequest(
                task_class="project.codegen", operation=mode, project_id=request.project_id,
                capability_ref=request.component_ref, provider_id=self.config.model,
                system="You are a bounded unit worker. Return exactly one FileBundle in EXECUTE or PatchBundle in REPAIR. Touch only unit.owns; never change the blueprint, run commands, access hidden acceptance, create evidence, or invent paths. Preserve every required and observed public interface during repair. Complete all tightly coupled owned files in one response.",
                goal=prompt, contract={"unit": unit.as_dict(), "required_interfaces": list(unit.required_interfaces)}, state={"files": sources, "interfaces": {key: value.as_dict() for key, value in manifests.items()}},
                failure_evidence=failure.as_dict() if failure else {}, schema_name="cgkn_unit_bundle", schema=UNIT_PAYLOAD_SCHEMA,
                model_config=self.config, allowed_actions=("file_bundle",) if not failure else ("patch_bundle",), forbidden_actions=("shell", "network", "blueprint_change", "hidden_acceptance"), run_id=request.run_id,
            ))
            completion = generated.completion; usage = dict(completion.usage)
            self.calls.append({"request_id": completion.request_id, "model": completion.model, "usage": usage, "role": "worker", "unit_id": unit.unit_id, "duration": int((time.perf_counter() - clock) * 1000), "attempt_count": completion.attempts})
            value = parse_json_object(completion.text)
            if str(value.get("unit_id", "")) != unit.unit_id: raise ValueError("bundle unit_id mismatch")
            if failure:
                bundle = PatchBundle.from_dict(value)
                if bundle.needs_escalation: raise RuntimeError(bundle.escalation_reason or "worker escalation")
                actions = [{"action": "patch_file", "path": path, "find": find, "replace": replacement} for path, find, replacement in bundle.patches]
                summary = bundle.summary
            else:
                bundle = FileBundle.from_dict(value)
                if bundle.needs_escalation: raise RuntimeError(bundle.escalation_reason or "worker escalation")
                actions = [{"action": "write_file", "path": path, "content": content} for path, content in bundle.files]
                summary = bundle.summary
            changed = tuple(item["path"] for item in actions)
            if not set(changed) <= set(unit.owns) or set(changed) != set(unit.owns): raise PermissionError("bundle must write exactly unit.owns")
            scope = WorkerScope(unit.owns + unit.reads, unit.owns, max_actions=unit.max_actions, max_write_files=unit.max_files, max_total_output_bytes=unit.max_output_bytes, allow_create=not failure, allow_patch=True, allow_delete=False)
            transaction = ScopedFileTransaction(self.root, scope)
            _, planned = transaction.validate(actions)
            new_sources = dict(sources)
            for item in planned: new_sources[item.relative] = item.content.decode("utf-8")
            new_manifests = _manifests({path: new_sources[path] for path in unit.owns if path in new_sources})
            for path, before in manifests.items():
                if path in unit.owns and path in new_manifests:
                    breaks = interface_breaks(before, new_manifests[path], unit.required_interfaces)
                    if breaks: raise PermissionError("interface guard: " + "; ".join(breaks))
            results = transaction.apply(actions)
            unit_result = UnitResult(unit.unit_id, "SUCCEEDED", changed, observed_interfaces=tuple(item.manifest_hash for item in new_manifests.values()), provider_usage=tuple((str(key), str(value)) for key, value in sorted(usage.items())), duration=int((time.perf_counter() - clock) * 1000))
            outputs = {"unit_result": unit_result.as_dict(), "summary": summary, "modified_files": list(changed), "observed_interfaces": {path: item.as_dict() for path, item in new_manifests.items()}, "context_chars": len(json.dumps(prompt, ensure_ascii=False, sort_keys=True)), "included_files": list(sources), "included_interfaces": list(manifests), "included_dependencies": list(request.task_context.dependency_results), "action_results": results}
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=outputs, started_at=started, ended_at=utc_now(), duration_ms=unit_result.duration, usage=usage)
        except Exception as exc:
            policy = isinstance(exc, PermissionError)
            code = ExecutionErrorCode.POLICY_BLOCKED if policy else ExecutionErrorCode.INVALID_OUTPUT if isinstance(exc, ValueError) else ExecutionErrorCode.EXECUTION_ERROR
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(code, str(exc)), started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage, retryable=not policy)


@dataclass(frozen=True)
class ProjectLoopOutcome:
    project_id: str
    run_id: str
    blueprint: ProjectBlueprint
    tree: CapabilityTree
    summary: RunSummary
    provider_calls: int
    agent_decisions: int
    repair_rounds: int
    failure_reports: tuple[FailureReport, ...]
    workspace: pathlib.Path
    run_root: pathlib.Path

    @property
    def status(self) -> str: return self.summary.status

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "run_id": self.run_id, "status": self.status, "blueprint": self.blueprint.as_dict(), "capability_tree": self.tree.as_dict(), "summary": self.summary.as_dict(), "provider_calls": self.provider_calls, "agent_decisions": self.agent_decisions, "repair_rounds": self.repair_rounds, "failure_reports": [item.as_dict() for item in self.failure_reports], "workspace": str(self.workspace), "run_root": str(self.run_root)}


class MinimalProjectLoop:
    """L6 adapter: one frozen blueprint compiled to the canonical tree/DAG/runtime."""

    def __init__(self, repository_root: pathlib.Path | str, run_root: pathlib.Path | str, client: CompletionClient | ProductionGenerationClient, agent_config: ModelRoleConfig, worker_config: ModelRoleConfig):
        if agent_config.role != "agent" or worker_config.role != "worker": raise ValueError("coordinator and worker role contracts are required")
        self.repository_root = pathlib.Path(repository_root).resolve(); self.run_root = pathlib.Path(run_root).resolve()
        self.client = client; self.agent_config = agent_config; self.worker_config = worker_config

    def design(self, project_id: str, public_contract: Mapping[str, Any], designer: DesignClient | None = None) -> tuple[ProjectBlueprint, int]:
        draft = ProjectBlueprint("1.0", project_id, 1, str(public_contract["public_goal"]), tuple(str(item) for item in public_contract.get("constraints", ())), (), ())
        effective = designer or ProviderBlueprintDesigner(self.client, self.agent_config)
        frozen = apply_blueprint_edits(draft, effective.design(draft, public_contract))
        if frozen.status != BlueprintStatus.FROZEN.value: raise ValueError("Coordinator did not finish design")
        return frozen, 1

    def run(self, blueprint: ProjectBlueprint, workspace: pathlib.Path | str, *, case_id: str, max_repairs: int = 2, failure_owner_hint: str = "", initial_failure: FailureReport | None = None) -> ProjectLoopOutcome:
        workspace = pathlib.Path(workspace).resolve(); workspace.mkdir(parents=True, exist_ok=True)
        run_id = f"blueprint-{blueprint.project_id}-{uuid.uuid4().hex[:10]}"; tree = compile_blueprint(blueprint, case_id=case_id); dag = compile_tree(tree)
        state_root = self.run_root / run_id; store = FileRunStore(state_root)
        registry = ExecutorRegistry(); worker = BlueprintUnitExecutor(workspace, self.client, self.worker_config)
        if initial_failure is not None:
            worker.failure_reports[initial_failure.unit_id] = initial_failure
        registry.register(worker); registry.register(CommandExecutor(workspace)); registry.register(PythonTestExecutor(workspace)); registry.register(ExternalAcceptanceExecutor(workspace, self.repository_root / "benchmarks" / "real_project_generation" / "acceptance"))
        runner = DAGRunner(registry, store)
        _write_json(state_root / "project_blueprint.json", blueprint.as_dict())
        summary = runner.run(project_id=blueprint.project_id, run_id=run_id, tree=tree, dag=dag, constraints=blueprint.constraints)
        reports: list[FailureReport] = [initial_failure] if initial_failure is not None else []
        repairs = 1 if initial_failure is not None else 0
        if initial_failure is not None:
            _write_json(state_root / "failure_reports" / "repair-1.json", initial_failure.as_dict())
        while summary.status != "SUCCEEDED" and repairs < max_repairs:
            failed_check = next(iter(summary.failed_nodes), "")
            if not failed_check: break
            failed_result = store.load_result(blueprint.project_id, run_id, failed_check)
            owner = failure_owner_hint or self._owner_from_failure(blueprint, failed_result)
            if not owner or owner not in blueprint.by_id: break
            affected = downstream_closure(dag, {owner})
            report = self._failure_report(owner, failed_check, failed_result, affected)
            reports.append(report); worker.failure_reports[owner] = report
            _write_json(state_root / "failure_reports" / f"repair-{repairs + 1}.json", report.as_dict())
            summary = runner.run(project_id=blueprint.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node=owner, constraints=blueprint.constraints)
            repairs += 1
        final_status = BlueprintStatus.DONE.value if summary.status == "SUCCEEDED" else BlueprintStatus.FAILED.value
        final_blueprint = replace(blueprint, status=final_status, blueprint_hash="")
        _write_json(state_root / "project_blueprint_final.json", final_blueprint.as_dict())
        outcome = ProjectLoopOutcome(blueprint.project_id, run_id, final_blueprint, tree, summary, len(worker.calls), 0, repairs, tuple(reports), workspace, state_root)
        _write_json(state_root / "project_outcome.json", outcome.as_dict())
        _write_json(state_root / "provider_calls.json", {"calls": worker.calls})
        return outcome

    @staticmethod
    def _owner_from_failure(blueprint: ProjectBlueprint, result: BlockExecutionResult) -> str:
        text = json.dumps(result.as_dict(), ensure_ascii=False)
        for unit in blueprint.units:
            for path in unit.owns:
                if path in text or pathlib.PurePosixPath(path).name in text: return unit.unit_id
        implementations = [item.unit_id for item in blueprint.units if item.kind == UnitKind.IMPLEMENTATION.value]
        return implementations[0] if len(implementations) == 1 else ""

    @staticmethod
    def _failure_report(owner: str, failed_check: str, result: BlockExecutionResult, affected: tuple[str, ...]) -> FailureReport:
        observed = (str(result.outputs.get("stderr", "")) + "\n" + str(result.outputs.get("stdout", "")))[:4000]
        message = result.error.message if result.error else observed
        failure_type = "TEST_FAILURE" if "pytest" in failed_check.lower() else "SYNTAX_ERROR" if "SyntaxError" in message else "IMPORT_ERROR" if "ImportError" in message or "ModuleNotFoundError" in message else "NAME_ERROR" if "NameError" in message else "RUNTIME_FAILURE"
        match = re.search(r'([^\s"\']+\.py):(\d+)', message + "\n" + observed)
        frame = match.group(0) if match else ""
        return FailureReport(owner, failure_type, first_project_frame=frame, failed_check=failed_check, expected="check exit code 0", observed=message[:2000], affected_units=affected, suggested_action="patch the owner unit while preserving observed interfaces", evidence_refs=(f"node_results/{failed_check}.json",))
