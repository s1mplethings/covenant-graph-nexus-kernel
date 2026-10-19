from __future__ import annotations

import json
import pathlib
import re
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from cgkn.application.learning import GenerationRequest, ProductionGenerationClient, canonical_hash, default_production_client
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
from cgkn.providers import CompletionClient, GatewayCompletionError, ModelRoleConfig, parse_json_object
from cgkn.runtime import DAGRunner, RunSummary
from cgkn.state import FileRunStore

from .project_blueprint import (
    BlueprintCheck,
    BlueprintStatus,
    BlueprintUnit,
    FailureAction,
    FailureReport,
    FailureStage,
    FileBundle,
    MINIMAL_BLUEPRINT_DESIGN_SCHEMA,
    MinimalBlueprintDesignPayload,
    ObservedInterfaceManifest,
    PatchBundle,
    ProjectBlueprint,
    UnitKind,
    UnitResult,
    assemble_project_blueprint,
    extract_python_interface,
    interface_breaks,
)


BLUEPRINT_EDIT_SCHEMA = MINIMAL_BLUEPRINT_DESIGN_SCHEMA

_FILE_ITEM = {"type": "object", "additionalProperties": False, "required": ["path", "content"], "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}
_PATCH_EDIT = {"type": "object", "additionalProperties": False, "required": ["find", "replace"], "properties": {"find": {"type": "string", "minLength": 1}, "replace": {"type": "string"}}}
_PATCH_FILE = {"type": "object", "additionalProperties": False, "required": ["path", "edits"], "properties": {"path": {"type": "string", "minLength": 1}, "edits": {"type": "array", "minItems": 1, "items": _PATCH_EDIT}}}
_ESCALATION_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["schema_version", "kind", "unit_id", "reason"], "properties": {"schema_version": {"const": "2.0"}, "kind": {"const": "escalation"}, "unit_id": {"type": "string"}, "reason": {"type": "string", "minLength": 1}}}
FILE_BUNDLE_SCHEMA: dict[str, Any] = {"oneOf": [
    {"type": "object", "additionalProperties": False, "required": ["schema_version", "kind", "unit_id", "files"], "properties": {"schema_version": {"const": "2.0"}, "kind": {"const": "file_bundle"}, "unit_id": {"type": "string"}, "files": {"type": "array", "minItems": 1, "maxItems": 5, "items": _FILE_ITEM}}},
    _ESCALATION_SCHEMA,
]}
PATCH_BUNDLE_SCHEMA: dict[str, Any] = {"oneOf": [
    {"type": "object", "additionalProperties": False, "required": ["schema_version", "kind", "unit_id", "files"], "properties": {"schema_version": {"const": "2.0"}, "kind": {"const": "patch_bundle"}, "unit_id": {"type": "string"}, "files": {"type": "array", "minItems": 1, "maxItems": 5, "items": _PATCH_FILE}}},
    _ESCALATION_SCHEMA,
]}
UNIT_PAYLOAD_SCHEMA = {"oneOf": [FILE_BUNDLE_SCHEMA["oneOf"][0], PATCH_BUNDLE_SCHEMA["oneOf"][0]]}


class UnitOutputValidationError(ValueError):
    def __init__(self, failure_type: str, message: str):
        super().__init__(message)
        self.failure_type = failure_type


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
            "timeout_seconds": unit.timeout_seconds,
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
    def design(self, blueprint: ProjectBlueprint, public_contract: Mapping[str, Any]) -> MinimalBlueprintDesignPayload: ...


class ProviderBlueprintDesigner:
    def __init__(self, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig):
        if config.role != "agent": raise ValueError("designer requires agent role")
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.config = config
        self.calls: list[dict[str, Any]] = []

    def design(self, blueprint: ProjectBlueprint, public_contract: Mapping[str, Any]) -> MinimalBlueprintDesignPayload:
        started = time.perf_counter()
        prompt = {
            "public_goal": public_contract.get("public_goal"),
            "constraints": list(public_contract.get("constraints", ())),
            "public_acceptance": list(public_contract.get("public_acceptance", ())),
            "required_entrypoint": public_contract.get("entrypoint"),
        }
        generated = self.generation.generate(GenerationRequest(
            task_class="project.blueprint", operation="BLUEPRINT_DESIGN", project_id=blueprint.project_id,
            capability_ref="project.blueprint.design@1", provider_id=self.config.model,
            system=(
                "You are the project coordinator in DESIGN mode. Return only one "
                "MinimalBlueprintDesignPayload. Do not write source code or commands. Do not "
                "generate checks, executor metadata, runtime limits, status, or governance fields. "
                "Use 2-4 cohesive implementation/tests/documentation units; each unit may own at "
                "most 5 tightly related files. Tests depend on their implementation. Documentation "
                "may be independent or depend on implementation. Set finish_design to true."
            ),
            goal=prompt, contract={}, state={}, failure_evidence={},
            schema_name="cgkn_minimal_blueprint_design", schema=MINIMAL_BLUEPRINT_DESIGN_SCHEMA,
            model_config=self.config,
            allowed_actions=("design_units",),
            forbidden_actions=("source_write", "shell", "checks", "executor_metadata", "candidate_metadata"),
            projected_prompt=prompt,
        ))
        self.calls.append({
            "request_id": generated.completion.request_id,
            "model": generated.completion.model,
            "usage": dict(generated.completion.usage),
            "usage_status": "REPORTED" if generated.completion.usage else "UNREPORTED",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "role": "coordinator",
            "logical_calls": 1,
            "transport_attempts": generated.completion.attempts,
            "selection_receipt": dict(generated.completion.selection_receipt),
            "transport_metadata": dict(generated.completion.transport_metadata),
        })
        value = parse_json_object(generated.completion.text)
        return MinimalBlueprintDesignPayload.from_dict(value)


class BlueprintUnitExecutor:
    descriptor = ExecutorDescriptor("llm.cheap@1", "blueprint_unit_worker", ("project.unit.implementation@1", "project.unit.tests@1", "project.unit.documentation@1"), ("filesystem.read", "filesystem.write"), supports_cost_reporting=True)

    def __init__(self, root: pathlib.Path | str, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig, repair_config: ModelRoleConfig | None = None):
        if config.role != "worker": raise ValueError("unit executor requires worker role")
        if repair_config is not None and repair_config.role != "worker": raise ValueError("repair executor requires worker role")
        self.root = pathlib.Path(root).resolve()
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.config = config
        self.repair_config = repair_config or config
        self.failure_reports: dict[str, FailureReport] = {}
        self.generation_failure_reports: dict[str, FailureReport] = {}
        self.materialized_units: dict[str, tuple[tuple[str, ...], str]] = {}
        self.calls: list[dict[str, Any]] = []

    def register_materialized_baseline(self, unit: BlueprintUnit) -> None:
        sources = _read_sources(self.root, unit.owns)
        if not unit.owns or set(sources) != set(unit.owns):
            raise ValueError("REPAIR_WITHOUT_BASELINE")
        self.materialized_units[unit.unit_id] = (unit.owns, canonical_hash({"unit_id": unit.unit_id, "files": sources}))

    def has_materialized_baseline(self, unit_id: str) -> bool:
        baseline = self.materialized_units.get(unit_id)
        if baseline is None:
            return False
        paths, expected = baseline
        sources = _read_sources(self.root, paths)
        return set(sources) == set(paths) and canonical_hash({"unit_id": unit_id, "files": sources}) == expected

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter(); usage: dict[str, Any] = {}
        unit: BlueprintUnit | None = None; mode = "UNKNOWN"; provider_recorded = False
        try:
            unit = BlueprintUnit.from_dict(request.task_context.node_config["unit"])
            visible = tuple(dict.fromkeys((*unit.owns, *unit.reads)))
            sources = _read_sources(self.root, visible)
            manifests = _manifests(sources)
            stored_failure = self.failure_reports.get(unit.unit_id)
            generation_failure = self.generation_failure_reports.get(unit.unit_id)
            has_patchable_baseline = self.has_materialized_baseline(unit.unit_id) and bool(unit.owns) and all(path in sources for path in unit.owns)
            failure = stored_failure if has_patchable_baseline else None
            mode = "REPAIR" if failure else "EXECUTE"
            effective_config = self.repair_config if failure else self.config
            prompt = {
                "mode": mode, "project_goal": request.task_context.node_goal, "public_constraints": list(request.task_context.project_constraints),
                "unit": unit.as_dict(), "current_files": sources,
                "observed_interfaces": {path: item.as_dict() for path, item in manifests.items()},
                "direct_dependency_results": materialize_json(request.task_context.dependency_results), "acceptance": list(unit.acceptance),
                "failure_report": (failure or generation_failure).as_dict() if (failure or generation_failure) else None,
                "output_contract": "PatchBundle only in REPAIR; compact FileBundle v2 only in EXECUTE",
            }
            schema = PATCH_BUNDLE_SCHEMA if failure else FILE_BUNDLE_SCHEMA
            system = (
                "You are a bounded unit worker. Return exactly one compact FileBundle v2. "
                "Emit each owned file exactly once as strict JSON, with no summary, metadata, schema echo, "
                "Markdown fence, or natural-language explanation. Touch only unit.owns; never invent paths."
                + (" The previous generation was rejected. Use its failure report and return the complete exact owned file set again." if generation_failure else "")
                if not failure else
                "You are a bounded unit repair worker. Return exactly one PatchBundle. Touch only unit.owns; "
                "never change the blueprint, run commands, access hidden acceptance, create evidence, or invent paths. "
                "Use PatchBundle v2 with one unique files[] object per modified file and one or more ordered edits. "
                "Modify only the smallest non-empty subset needed. Preserve every required and observed public interface."
            )
            generated = self.generation.generate(GenerationRequest(
                task_class="project.codegen", operation=mode, project_id=request.project_id,
                capability_ref=request.component_ref, provider_id=self.config.model,
                system=system,
                goal=prompt, contract={"unit": unit.as_dict(), "required_interfaces": list(unit.required_interfaces)}, state={"files": sources, "interfaces": {key: value.as_dict() for key, value in manifests.items()}},
                failure_evidence=(failure or generation_failure).as_dict() if (failure or generation_failure) else {}, schema_name="cgkn_unit_bundle", schema=schema,
                model_config=effective_config, allowed_actions=("file_bundle",) if not failure else ("patch_bundle",), forbidden_actions=("shell", "network", "blueprint_change", "hidden_acceptance"), run_id=request.run_id,
            ))
            completion = generated.completion; usage = dict(completion.usage)
            self.calls.append(self._call_record(request, unit, mode, clock, config=effective_config, completion=completion))
            provider_recorded = True
            value = parse_json_object(completion.text)
            if str(value.get("unit_id", "")) != unit.unit_id: raise UnitOutputValidationError("UNIT_OUTPUT_INVALID", "bundle unit_id mismatch")
            if value.get("kind") == "escalation": raise RuntimeError(str(value.get("reason") or "worker escalation"))
            if failure:
                bundle = PatchBundle.from_dict(value)
                if bundle.needs_escalation: raise RuntimeError(bundle.escalation_reason or "worker escalation")
                actions = [{"action": "patch_file", "path": path, "edits": [{"find": find, "replace": replacement} for find, replacement in edits]} for path, edits in bundle.files]
                summary = bundle.summary
            else:
                bundle = FileBundle.from_dict(value)
                if bundle.needs_escalation: raise RuntimeError(bundle.escalation_reason or "worker escalation")
                actions = [{"action": "write_file", "path": path, "content": content} for path, content in bundle.files]
                summary = bundle.summary
            changed = tuple(item["path"] for item in actions)
            if failure:
                if not changed or not set(changed) <= set(unit.owns):
                    raise UnitOutputValidationError("UNIT_OUTPUT_SCOPE_VIOLATION", "repair bundle must modify a non-empty subset of unit.owns")
            else:
                missing = tuple(path for path in unit.owns if path not in changed)
                extra = tuple(path for path in changed if path not in unit.owns)
                if missing:
                    raise UnitOutputValidationError("UNIT_OUTPUT_INCOMPLETE", "FileBundle incomplete; missing owned paths: " + ", ".join(missing))
                if extra or len(changed) != len(unit.owns):
                    raise UnitOutputValidationError("UNIT_OUTPUT_SCOPE_VIOLATION", "FileBundle must write exactly unit.owns")
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
            self.register_materialized_baseline(unit)
            self.generation_failure_reports.pop(unit.unit_id, None)
            unit_result = UnitResult(unit.unit_id, "SUCCEEDED", changed, observed_interfaces=tuple(item.manifest_hash for item in new_manifests.values()), provider_usage=tuple((str(key), str(value)) for key, value in sorted(usage.items())), duration=int((time.perf_counter() - clock) * 1000), materialized_baseline=True)
            if self.calls:
                self.calls[-1]["unit_result"] = "SUCCEEDED"
            outputs = {"unit_result": unit_result.as_dict(), "summary": summary, "modified_files": list(changed), "observed_interfaces": {path: item.as_dict() for path, item in new_manifests.items()}, "context_chars": len(json.dumps(prompt, ensure_ascii=False, sort_keys=True)), "included_files": list(sources), "included_interfaces": list(manifests), "included_dependencies": list(request.task_context.dependency_results), "action_results": results}
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=outputs, started_at=started, ended_at=utc_now(), duration_ms=unit_result.duration, usage=usage)
        except Exception as exc:
            if isinstance(exc, GatewayCompletionError) and unit is not None and not provider_recorded:
                effective_config = self.repair_config if mode == "REPAIR" else self.config
                self.calls.append(self._call_record(request, unit, mode, clock, config=effective_config, error=exc))
            policy = isinstance(exc, PermissionError)
            code = ExecutionErrorCode.POLICY_BLOCKED if policy else ExecutionErrorCode.INVALID_OUTPUT if isinstance(exc, ValueError) else ExecutionErrorCode.EXECUTION_ERROR
            failure_stage = FailureStage.UNIT_OUTPUT_VALIDATION.value
            failure_type = getattr(exc, "failure_type", "UNIT_OUTPUT_INVALID")
            if isinstance(exc, GatewayCompletionError):
                category = str(getattr(exc, "category", ""))
                failure_stage = FailureStage.PROVIDER_OUTPUT.value if category.startswith("PROVIDER_OUTPUT") or "SCHEMA" in category else FailureStage.PROVIDER_TRANSPORT.value
                failure_type = "PROVIDER_FAILURE"
            elif isinstance(exc, PermissionError) and "interface guard" in str(exc):
                failure_stage = FailureStage.INTERFACE_VALIDATION.value
                failure_type = "INTERFACE_MISMATCH"
            elif isinstance(exc, PermissionError):
                failure_stage = FailureStage.MATERIALIZATION.value
                failure_type = "SCOPE_VIOLATION"
            elif "syntax validation" in str(exc):
                failure_stage = FailureStage.SYNTAX_VALIDATION.value
                failure_type = "SYNTAX_ERROR"
            details = {
                "failure_stage": failure_stage,
                "failure_type": failure_type,
                "origin_unit_id": unit.unit_id if unit is not None else request.node_id,
                "operation": mode,
                "materialized_baseline": bool(unit is not None and self.has_materialized_baseline(unit.unit_id)),
            }
            if provider_recorded and self.calls:
                self.calls[-1].update({"unit_result": "FAILED", "failure_stage": failure_stage, "failure_type": failure_type})
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(code, str(exc), details), started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage, retryable=not policy)

    def _call_record(
        self, request: BlockExecutionRequest, unit: BlueprintUnit, mode: str, clock: float, *,
        config: ModelRoleConfig, completion: Any | None = None, error: GatewayCompletionError | None = None,
    ) -> dict[str, Any]:
        receipt = dict(completion.selection_receipt) if completion is not None else dict(error.evidence if error else {})
        metadata = dict(completion.transport_metadata) if completion is not None else {}
        reported_usage = dict(completion.usage) if completion is not None else dict(receipt.get("usage") or {})
        usage_status = "REPORTED" if reported_usage else "UNKNOWN_AFTER_FAILURE" if error else "UNREPORTED"
        def token(*names: str) -> int | None:
            for source in (reported_usage, receipt):
                for name in names:
                    if source.get(name) is not None:
                        return int(source[name])
            return None
        attempts_detail = metadata.get("transport_attempts") or receipt.get("transport_attempts_detail") or []
        attempt_count = completion.attempts if completion is not None else receipt.get("transport_attempts")
        prior_generation_attempts = sum(call.get("unit_id") == unit.unit_id and call.get("operation") == "EXECUTE" for call in self.calls)
        call_class = "GENERATION_RETRY" if mode == "EXECUTE" and prior_generation_attempts else "GENERATION" if mode == "EXECUTE" else "REPAIR"
        return {
            "logical_call_id": f"{request.run_id}:{unit.unit_id}:{mode.lower()}:{len(self.calls) + 1}",
            "project_id": request.project_id, "run_id": request.run_id,
            "role": "worker", "operation": mode, "unit_id": unit.unit_id,
            "call_class": call_class,
            "provider": config.model,
            "model": completion.model if completion is not None else str(receipt.get("model") or config.model),
            "request_id": completion.request_id if completion is not None else str(receipt.get("request_id") or ""),
            "transport_attempts": attempts_detail if attempts_detail else attempt_count,
            "transport_attempt_count": int(attempt_count or (len(attempts_detail) if isinstance(attempts_detail, list) else 0)),
            "thinking_mode_requested": config.thinking_mode,
            "thinking_mode_forwarded": metadata.get("thinking_mode_forwarded", receipt.get("thinking_mode_forwarded")),
            "reasoning_effort": config.reasoning_effort,
            "prompt_tokens": token("prompt_tokens", "input_tokens"),
            "completion_tokens": token("completion_tokens", "output_tokens"),
            "reasoning_tokens": token("reasoning_tokens"),
            "cached_tokens": token("cached_tokens"),
            "total_tokens": token("total_tokens"), "usage_status": usage_status,
            "finish_reason": receipt.get("finish_reason"),
            "configured_timeout": config.timeout_seconds,
            "effective_timeout": receipt.get("effective_request_timeout_seconds"),
            "elapsed_ms": int((time.perf_counter() - clock) * 1000),
            "schema_hash": receipt.get("schema_hash"), "prompt_hash": receipt.get("prompt_hash"),
            "selection_receipt_hash": canonical_hash(receipt) if receipt else None,
            "selection_receipt": receipt, "transport_metadata": metadata,
            "result": "FAILED" if error else "SUCCEEDED",
            "failure_type": error.category if error else None,
        }


@dataclass(frozen=True)
class ProjectLoopOutcome:
    project_id: str
    run_id: str
    blueprint: ProjectBlueprint
    tree: CapabilityTree
    summary: RunSummary
    provider_calls: int
    agent_decisions: int
    generation_attempts: int
    generation_retries: int
    repair_calls: int
    repair_rounds: int
    failure_reports: tuple[FailureReport, ...]
    workspace: pathlib.Path
    run_root: pathlib.Path

    @property
    def status(self) -> str: return self.summary.status

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "run_id": self.run_id, "status": self.status, "blueprint": self.blueprint.as_dict(), "capability_tree": self.tree.as_dict(), "summary": self.summary.as_dict(), "provider_calls": self.provider_calls, "agent_decisions": self.agent_decisions, "generation_attempts": self.generation_attempts, "generation_retries": self.generation_retries, "generation_retry_calls": self.generation_retries, "repair_calls": self.repair_calls, "repair_rounds": self.repair_rounds, "failure_reports": [item.as_dict() for item in self.failure_reports], "workspace": str(self.workspace), "run_root": str(self.run_root)}


class MinimalProjectLoop:
    """L6 adapter: one frozen blueprint compiled to the canonical tree/DAG/runtime."""

    def __init__(self, repository_root: pathlib.Path | str, run_root: pathlib.Path | str, client: CompletionClient | ProductionGenerationClient, agent_config: ModelRoleConfig, worker_config: ModelRoleConfig, worker_repair_config: ModelRoleConfig | None = None):
        if agent_config.role != "agent" or worker_config.role != "worker": raise ValueError("coordinator and worker role contracts are required")
        self.repository_root = pathlib.Path(repository_root).resolve(); self.run_root = pathlib.Path(run_root).resolve()
        self.client = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        if self.client.max_provider_calls is None:
            self.client.max_provider_calls = 8
        self.agent_config = agent_config; self.worker_config = worker_config
        self.worker_repair_config = worker_repair_config or worker_config
        self.coordinator_calls: list[dict[str, Any]] = []

    def design(self, project_id: str, public_contract: Mapping[str, Any], designer: DesignClient | None = None) -> tuple[ProjectBlueprint, int]:
        draft = ProjectBlueprint("1.0", project_id, 1, str(public_contract["public_goal"]), tuple(str(item) for item in public_contract.get("constraints", ())), (), ())
        effective = designer or ProviderBlueprintDesigner(self.client, self.agent_config)
        payload = effective.design(draft, public_contract)
        frozen = assemble_project_blueprint(project_id, payload, public_contract)
        calls = getattr(effective, "calls", ())
        self.coordinator_calls = [dict(item) for item in calls]
        if self.coordinator_calls:
            receipt = dict(self.coordinator_calls[-1].get("selection_receipt") or {})
            receipt["blueprint_hash"] = frozen.blueprint_hash
            self.coordinator_calls[-1]["selection_receipt"] = receipt
            self.coordinator_calls[-1]["blueprint_hash"] = frozen.blueprint_hash
            self.coordinator_calls[-1]["unit_count"] = len(frozen.units)
            self.coordinator_calls[-1]["check_count"] = len(frozen.checks)
        if frozen.status != BlueprintStatus.FROZEN.value: raise ValueError("Coordinator did not finish design")
        return frozen, 1

    def run(self, blueprint: ProjectBlueprint, workspace: pathlib.Path | str, *, case_id: str, max_repairs: int = 2, max_generation_retries: int = 2, failure_owner_hint: str = "", initial_failure: FailureReport | None = None) -> ProjectLoopOutcome:
        workspace = pathlib.Path(workspace).resolve(); workspace.mkdir(parents=True, exist_ok=True)
        run_id = f"blueprint-{blueprint.project_id}-{uuid.uuid4().hex[:10]}"; tree = compile_blueprint(blueprint, case_id=case_id); dag = compile_tree(tree)
        state_root = self.run_root / run_id; store = FileRunStore(state_root)
        registry = ExecutorRegistry(); worker = BlueprintUnitExecutor(workspace, self.client, self.worker_config, self.worker_repair_config)
        if initial_failure is not None:
            owner = initial_failure.owner_unit_id
            if initial_failure.recovery_action != FailureAction.REPAIR_EXISTING.value or not owner or owner not in blueprint.by_id:
                raise ValueError("initial failure must request REPAIR_EXISTING for a known owner")
            worker.register_materialized_baseline(blueprint.by_id[owner])
            worker.failure_reports[owner] = initial_failure
        registry.register(worker); registry.register(CommandExecutor(workspace)); registry.register(PythonTestExecutor(workspace)); registry.register(ExternalAcceptanceExecutor(workspace, self.repository_root / "benchmarks" / "real_project_generation" / "acceptance"))
        runner = DAGRunner(registry, store)
        _write_json(state_root / "project_blueprint.json", blueprint.as_dict())
        summary = runner.run(project_id=blueprint.project_id, run_id=run_id, tree=tree, dag=dag, constraints=blueprint.constraints)
        reports: list[FailureReport] = [initial_failure] if initial_failure is not None else []
        repairs = 1 if initial_failure is not None else 0
        generation_retries = 0
        if initial_failure is not None:
            _write_json(state_root / "failure_reports" / "repair-1.json", initial_failure.as_dict())
        while summary.status != "SUCCEEDED":
            failed_check = next(iter(summary.failed_nodes), "")
            if not failed_check: break
            failed_result = store.load_result(blueprint.project_id, run_id, failed_check)
            report = self._failure_report(blueprint, failed_check, failed_result, dag, worker, failure_owner_hint)
            reports.append(report)
            owner = report.owner_unit_id
            if report.recovery_action == FailureAction.RETRY_GENERATION.value:
                if generation_retries >= max_generation_retries or not owner:
                    break
                worker.failure_reports.pop(owner, None)
                worker.generation_failure_reports[owner] = report
                generation_retries += 1
                _write_json(state_root / "failure_reports" / f"generation-retry-{generation_retries}.json", report.as_dict())
            elif report.recovery_action == FailureAction.REPAIR_EXISTING.value:
                if repairs >= max_repairs or not owner or not worker.has_materialized_baseline(owner):
                    break
                worker.generation_failure_reports.pop(owner, None)
                worker.failure_reports[owner] = report
                repairs += 1
                _write_json(state_root / "failure_reports" / f"repair-{repairs}.json", report.as_dict())
            else:
                _write_json(state_root / "failure_reports" / f"stopped-{len(reports)}.json", report.as_dict())
                break
            summary = runner.run(project_id=blueprint.project_id, run_id=run_id, tree=tree, dag=dag, resume=True, retry_node=owner, constraints=blueprint.constraints)
        final_status = BlueprintStatus.DONE.value if summary.status == "SUCCEEDED" else BlueprintStatus.FAILED.value
        final_blueprint = replace(blueprint, status=final_status, blueprint_hash="")
        _write_json(state_root / "project_blueprint_final.json", final_blueprint.as_dict())
        generation_attempts = sum(call.get("operation") == "EXECUTE" for call in worker.calls)
        repair_calls = sum(call.get("operation") == "REPAIR" for call in worker.calls)
        outcome = ProjectLoopOutcome(blueprint.project_id, run_id, final_blueprint, tree, summary, len(worker.calls), 0, generation_attempts, generation_retries, repair_calls, repairs, tuple(reports), workspace, state_root)
        _write_json(state_root / "project_outcome.json", outcome.as_dict())
        _write_json(state_root / "provider_calls.json", {"calls": worker.calls})
        return outcome

    @staticmethod
    def _owner_from_failure(blueprint: ProjectBlueprint, result: BlockExecutionResult) -> str:
        text = json.dumps(result.as_dict(), ensure_ascii=False).replace("\\\\", "/").replace("\\", "/")
        matches: list[tuple[int, str]] = []
        for unit in blueprint.units:
            for path in unit.owns:
                positions = [position for candidate in (path, pathlib.PurePosixPath(path).name) if (position := text.find(candidate)) >= 0]
                if positions:
                    matches.append((min(positions), unit.unit_id))
        return min(matches)[1] if matches else ""

    @classmethod
    def _failure_report(cls, blueprint: ProjectBlueprint, failed_check: str, result: BlockExecutionResult, dag: Any, worker: BlueprintUnitExecutor, owner_hint: str = "") -> FailureReport:
        observed = (str(result.outputs.get("stderr", "")) + "\n" + str(result.outputs.get("stdout", "")))[:4000]
        message = result.error.message if result.error else observed
        details = dict(result.error.details) if result.error else {}
        stage_by_check = {"compile": FailureStage.COMPILE.value, "pytest": FailureStage.TEST.value, "runtime_smoke": FailureStage.RUNTIME.value, "external_acceptance": FailureStage.ACCEPTANCE.value}
        stage = str(details.get("failure_stage") or stage_by_check.get(failed_check, FailureStage.UNKNOWN.value))
        origin = str(details.get("origin_unit_id") or failed_check)
        local_stages = {
            FailureStage.PROVIDER_TRANSPORT.value, FailureStage.PROVIDER_OUTPUT.value,
            FailureStage.UNIT_OUTPUT_VALIDATION.value, FailureStage.MATERIALIZATION.value,
            FailureStage.SYNTAX_VALIDATION.value, FailureStage.INTERFACE_VALIDATION.value,
        }
        if failed_check in blueprint.by_id and stage in local_stages:
            owner = failed_check
        else:
            owner = owner_hint or cls._owner_from_failure(blueprint, result)
        baseline = bool(owner and worker.has_materialized_baseline(owner))
        if not owner:
            failure_type = "ATTRIBUTION_UNRESOLVED"
            action = FailureAction.STOP.value
        elif failed_check in blueprint.by_id and not baseline:
            failure_type = str(details.get("failure_type") or "UNIT_OUTPUT_INVALID")
            action = FailureAction.RETRY_GENERATION.value
        elif baseline:
            failure_type = str(details.get("failure_type") or ("TEST_FAILURE" if stage == FailureStage.TEST.value else "RUNTIME_FAILURE"))
            action = FailureAction.REPAIR_EXISTING.value
        else:
            failure_type = "REPAIR_WITHOUT_BASELINE"
            action = FailureAction.STOP.value
        if failure_type == "RUNTIME_FAILURE":
            failure_type = "SYNTAX_ERROR" if "SyntaxError" in message else "IMPORT_ERROR" if "ImportError" in message or "ModuleNotFoundError" in message else "NAME_ERROR" if "NameError" in message else failure_type
        match = re.search(r'([^\s"\']+\.py):(\d+)', message + "\n" + observed)
        frame = match.group(0) if match else ""
        owner_file = frame.rsplit(":", 1)[0] if frame else ""
        affected = downstream_closure(dag, {owner}) if owner else ()
        suggestion = "retry generation for the same unit with failure context" if action == FailureAction.RETRY_GENERATION.value else "patch the owner unit while preserving observed interfaces" if action == FailureAction.REPAIR_EXISTING.value else "stop fail-closed; attribution is unresolved"
        return FailureReport(origin, failure_type, failure_stage=stage, owner_unit_id=owner, recovery_action=action, materialized_baseline=baseline, owner_file=owner_file, first_project_frame=frame, failed_check=failed_check, expected="check exit code 0", observed=message[:2000], affected_units=affected, suggested_action=suggestion, evidence_refs=(f"node_results/{failed_check}.json",))
