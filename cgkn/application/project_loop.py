from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol

from cgkn.application.learning import GenerationRequest, ProductionGenerationClient, canonical_hash, default_production_client
from cgkn.application.materialization import materialize_json
from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.application.software_project.catalog import get_case
from cgkn.application.software_project.contracts import WorkerScope
from cgkn.application.software_project.scope import CommitFailure, ScopeViolation, ScopedFileTransaction
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors import CommandExecutor, ExecutorRegistry, PythonTestExecutor
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.orchestration.invalidation import downstream_closure
from cgkn.providers import CompletionClient, GatewayCompletionError, ModelRoleConfig, parse_json_object
from cgkn.runtime import DAGRunner, RunSummary
from cgkn.state import FileRunStore

from .test_authority import AssertionAuthority, PublicContractProjection, TestAuthorityFirewall, TestAuthorityReceipt
from .repair_convergence import (
    CanonicalRepairTargetValidator,
    RepairAttemptEvidence,
    RepairCandidateState,
    RepairCandidateStatus,
    RepairEvidencePacket,
    RepairProgress,
    RepairTargetSpec,
    build_public_test_repair_target,
    capture_public_failure_context,
    classify_repair_progress,
    localize_repair_sources,
    patch_modified_symbols,
    repair_evidence_metrics,
    run_targeted_regression,
    summarize_patch_diff,
)

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
    minimal_blueprint_design_schema,
    public_requirement_catalog,
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
MAX_UNIT_MATERIALIZATION_CALLS = 3
REPAIR_EVIDENCE_MODES = frozenset({
    "CURRENT",
    "FAILURE_SLICE_CONTRASTIVE",
    "FAILURE_SLICE_TRANSPORT_CONTRASTIVE",
})
REPAIR_SCOPE_MODES = frozenset({"NORMAL", "LOCALIZED"})
DEFAULT_REPAIR_EVIDENCE_MODE = "FAILURE_SLICE_TRANSPORT_CONTRASTIVE"
DEFAULT_REPAIR_SCOPE_MODE = "NORMAL"


def _dependency_prompt_projection(
    dependency_results: Mapping[str, Any],
) -> dict[str, Any]:
    """Expose only stable, execution-relevant dependency facts to a worker.

    A completed dependency result also contains receipt and timing metadata.
    Those fields are useful in the run ledger but are neither semantic input to
    a downstream Unit nor stable across equivalent executions.  Keeping them
    out of the prompt makes the bounded context reproducible and avoids paying
    for hashes, usage counters, and wall-clock durations that the worker cannot
    act on.
    """

    projected: dict[str, Any] = {}
    stable_output_fields = (
        "summary",
        "modified_files",
        "observed_interfaces",
        "test_authority_receipt",
    )
    stable_result_fields = (
        "unit_id",
        "status",
        "changed_files",
        "observed_interfaces",
        "produced_artifact_refs",
        "materialized_baseline",
        "error",
    )
    for node_id, raw_value in sorted(dependency_results.items()):
        value = materialize_json(raw_value)
        if not isinstance(value, Mapping):
            projected[str(node_id)] = value
            continue
        item = {
            field: value[field]
            for field in stable_output_fields
            if field in value
        }
        unit_result = value.get("unit_result")
        if isinstance(unit_result, Mapping):
            item["unit_result"] = {
                field: unit_result[field]
                for field in stable_result_fields
                if field in unit_result
            }
        projected[str(node_id)] = item
    return projected


def file_bundle_schema(requested_paths: tuple[str, ...]) -> dict[str, Any]:
    """Bind a generation response to the current materialization slice."""
    if not requested_paths:
        raise ValueError("requested_paths must be non-empty")
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "content"],
        "properties": {
            "path": {"enum": list(requested_paths)},
            "content": {"type": "string"},
        },
    }
    return {"oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "kind", "unit_id", "files"],
            "properties": {
                "schema_version": {"const": "2.0"},
                "kind": {"const": "file_bundle"},
                "unit_id": {"type": "string"},
                "files": {
                    "type": "array", "minItems": 1,
                    "maxItems": len(requested_paths), "items": item,
                },
            },
        },
        _ESCALATION_SCHEMA,
    ]}


def patch_bundle_schema(allowed_paths: tuple[str, ...]) -> dict[str, Any]:
    """Bind a repair response to the deterministic repair file scope."""
    if not allowed_paths:
        raise ValueError("allowed_paths must be non-empty")
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "edits"],
        "properties": {
            "path": {"enum": list(allowed_paths)},
            "edits": {"type": "array", "minItems": 1, "items": _PATCH_EDIT},
        },
    }
    return {"oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["schema_version", "kind", "unit_id", "files"],
            "properties": {
                "schema_version": {"const": "2.0"},
                "kind": {"const": "patch_bundle"},
                "unit_id": {"type": "string"},
                "files": {
                    "type": "array", "minItems": 1,
                    "maxItems": len(allowed_paths), "items": item,
                },
            },
        },
        _ESCALATION_SCHEMA,
    ]}


@dataclass
class UnitMaterializationState:
    unit_id: str
    expected_paths: tuple[str, ...]
    requested_paths: tuple[str, ...] = ()
    staged_files: dict[str, str] = field(default_factory=dict)
    materialization_calls: int = 0
    generation_calls: int = 0
    continuation_calls: int = 0
    generation_retry_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_output_bytes: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    status: str = "EMPTY"
    last_new_coverage: tuple[str, ...] = ()
    failure_reason: str = ""
    no_progress_attempts: int = 0
    last_unresolved_paths: tuple[str, ...] = ()
    transitions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def missing_paths(self) -> tuple[str, ...]:
        return tuple(path for path in self.expected_paths if path not in self.staged_files)

    def record(
        self, status: str, *, returned_paths: tuple[str, ...] = (),
        call_class: str = "", reason: str = "",
    ) -> None:
        self.status = status
        self.last_new_coverage = returned_paths
        if reason:
            self.failure_reason = reason
        self.transitions.append({
            "status": status,
            "materialization_call": self.materialization_calls,
            "call_class": call_class,
            "requested_paths": list(self.requested_paths),
            "returned_paths": list(returned_paths),
            "staged_paths": [path for path in self.expected_paths if path in self.staged_files],
            "missing_paths": list(self.missing_paths),
            "total_output_bytes": self.total_output_bytes,
            "reason": reason,
        })

    def begin_call(self, call_class: str, requested_paths: tuple[str, ...]) -> None:
        self.requested_paths = requested_paths
        self.materialization_calls += 1
        if call_class == "GENERATION":
            self.generation_calls += 1
        elif call_class == "GENERATION_CONTINUATION":
            self.continuation_calls += 1
        elif call_class == "GENERATION_RETRY":
            self.generation_retry_calls += 1
        else:
            raise ValueError("invalid materialization call class")

    def add_usage(self, usage: Mapping[str, Any]) -> None:
        self.total_input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        self.total_output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    def record_no_progress(self, call_class: str, reason: str) -> bool:
        unresolved = self.missing_paths
        if unresolved == self.last_unresolved_paths:
            self.no_progress_attempts += 1
        else:
            self.no_progress_attempts = 1
            self.last_unresolved_paths = unresolved
        self.record("PARTIAL" if self.staged_files else "EMPTY", call_class=call_class, reason=reason)
        return self.no_progress_attempts >= 2

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "expected_paths": list(self.expected_paths),
            "requested_paths": list(self.requested_paths),
            "staged_paths": [path for path in self.expected_paths if path in self.staged_files],
            "missing_paths": list(self.missing_paths),
            "materialization_calls": self.materialization_calls,
            "generation_calls": self.generation_calls,
            "continuation_calls": self.continuation_calls,
            "generation_retry_calls": self.generation_retry_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_output_bytes": self.total_output_bytes,
            "status": self.status,
            "last_new_coverage": list(self.last_new_coverage),
            "failure_reason": self.failure_reason,
            "duration_ms": max(0, int((time.perf_counter() - self.started_at) * 1000)),
            "transitions": list(self.transitions),
        }
ACCEPTANCE_ATTRIBUTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "decisions"],
    "properties": {
        "schema_version": {"const": "1.0"},
        "decisions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["requirement_id", "owner_unit_id", "action"],
                "properties": {
                    "requirement_id": {"type": "string", "minLength": 1},
                    "owner_unit_id": {"type": "string"},
                    "action": {"enum": ["REPAIR_EXISTING", "STOP"]},
                },
            },
        },
    },
}


class UnitOutputValidationError(ValueError):
    def __init__(
        self,
        failure_type: str,
        message: str,
        *,
        retryable: bool = False,
        failure_stage: str = "",
        owner_unit_id: str = "",
        details: Mapping[str, Any] | None = None,
    ):
        super().__init__(message)
        self.failure_type = failure_type
        self.retryable = retryable
        self.failure_stage = failure_stage
        self.owner_unit_id = owner_unit_id
        self.details = dict(details or {})


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


def _required_interface_failures(
    manifests: Mapping[str, ObservedInterfaceManifest], required: tuple[str, ...],
) -> tuple[str, ...]:
    available: set[str] = set()
    for manifest in manifests.values():
        symbols = {
            *manifest.exports,
            *(item.name for item in manifest.functions),
            *(item.name for item in manifest.classes),
        }
        available.update(symbols)
        available.update(f"{manifest.module}.{name}" for name in symbols)
        available.update(manifest.cli_options)
    return tuple(f"required interface missing: {item}" for item in required if item not in available)


def _cross_file_consistency_failures(sources: Mapping[str, str]) -> tuple[str, ...]:
    """Detect unresolved project-relative imports before a Unit reaches the workspace."""
    known = {pathlib.PurePosixPath(path).as_posix() for path in sources}
    failures: list[str] = []
    for relative, content in sources.items():
        path = pathlib.PurePosixPath(relative)
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level < 1 or not node.module:
                continue
            base = path.parent
            for _ in range(node.level - 1):
                base = base.parent
            module = pathlib.PurePosixPath(*node.module.split("."))
            stem = (base / module).as_posix()
            candidates = {f"{stem}.py", f"{stem}/__init__.py"}
            if not candidates & known:
                failures.append(f"{relative}: unresolved relative import {'.' * node.level}{node.module}")
    return tuple(sorted(set(failures)))


def compile_blueprint(blueprint: ProjectBlueprint, *, case_id: str = "") -> CapabilityTree:
    if blueprint.status not in {BlueprintStatus.FROZEN.value, BlueprintStatus.EXECUTING.value, BlueprintStatus.REPAIRING.value, BlueprintStatus.DONE.value, BlueprintStatus.FAILED.value}:
        raise ValueError("compile_blueprint requires a frozen blueprint")
    nodes: list[CapabilityNode] = []
    projection = PublicContractProjection.for_case(case_id).as_dict() if case_id else None
    case = get_case(case_id) if case_id else None
    public_ids = tuple(f"REQ-{index:03d}" for index, _ in enumerate(case.public_acceptance, 1)) if case else ()
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
            "project_goal": blueprint.goal,
            "unit": unit.as_dict(), "acceptance": list(unit.acceptance), "effects": list(unit.allowed_effects),
            "timeout_seconds": unit.timeout_seconds,
        }
        if projection is not None and unit.kind in {UnitKind.IMPLEMENTATION.value, UnitKind.TESTS.value}:
            config["public_contract_projection"] = projection
            config["owned_public_requirement_ids"] = list(public_ids if unit.kind == UnitKind.TESTS.value else ())
        if unit.kind == UnitKind.VERIFICATION.value:
            config["command"] = list(unit.acceptance)
        elif unit.kind == UnitKind.ACCEPTANCE.value:
            config["case_id"] = case_id
            config["dependency_policy"] = {
                "runtime": {"allowed_packages": []},
                "test": {"allowed_packages": ["pytest"]},
            }
        nodes.append(CapabilityNode(unit.unit_id, capability_ref=capability, depends_on=unit.depends_on, config=config))
    for check in blueprint.checks:
        if check.kind == UnitKind.ACCEPTANCE.value:
            nodes.append(CapabilityNode(check.check_id, capability_ref="project.acceptance.external@1", depends_on=check.depends_on, config={"executor_ref": "project.acceptance@1", "case_id": case_id, "goal": "Run external acceptance", "acceptance": list(check.acceptance), "dependency_policy": {"runtime": {"allowed_packages": []}, "test": {"allowed_packages": ["pytest"]}}, "timeout_seconds": 120}))
        else:
            is_pytest = any("pytest" in item for item in check.command)
            nodes.append(CapabilityNode(check.check_id, capability_ref="project.python.pytest@1" if is_pytest else "project.command.verify@1", depends_on=check.depends_on, config={"executor_ref": "local.python-test@1" if is_pytest else "local.command@1", "pytest_args": list(check.command[3:] if len(check.command) >= 3 else ("-q",)) if is_pytest else None, "command": list(check.command), "goal": f"Run {check.check_id}", "acceptance": list(check.acceptance), "timeout_seconds": 120}))
    return CapabilityTree(blueprint.goal, tuple(nodes))


class DesignClient(Protocol):
    def design(self, blueprint: ProjectBlueprint, public_contract: Mapping[str, Any]) -> MinimalBlueprintDesignPayload: ...


def coordinator_design_request(public_contract: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded public-only Coordinator request used by probes and production."""

    requirements = {
        requirement_id: summary
        for requirement_id, summary in public_requirement_catalog(public_contract)
    }
    prompt = {
        "public_goal": public_contract.get("public_goal"),
        "constraints": list(public_contract.get("constraints", ())),
        "public_requirements": requirements,
        "required_entrypoint": public_contract.get("entrypoint"),
    }
    system = (
        "Return only the schema object for 2-4 cohesive project units. Choose each unit's kind, short "
        "purpose, owned project-relative paths, and primary public requirement IDs. Assign every "
        "requirement ID exactly once. Include implementation, tests, and README documentation when "
        "required. Minimize owned paths: prefer one main file plus an optional package marker per "
        "responsibility, and do not split tests into separate files by requirement. Emit no source, "
        "commands, dependencies, interfaces, runtime fields, or explanation."
    )
    return {
        "contract_version": "minimal-blueprint-design-v2",
        "schema_name": "cgnk_minimal_blueprint_design_v2",
        "schema": minimal_blueprint_design_schema(public_contract),
        "system": system,
        "prompt": prompt,
    }


class ProviderBlueprintDesigner:
    def __init__(self, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig):
        if config.role != "agent": raise ValueError("designer requires agent role")
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.config = config
        self.calls: list[dict[str, Any]] = []

    def design(self, blueprint: ProjectBlueprint, public_contract: Mapping[str, Any]) -> MinimalBlueprintDesignPayload:
        started = time.perf_counter()
        request_contract = coordinator_design_request(public_contract)
        prompt = request_contract["prompt"]
        schema = request_contract["schema"]
        system = request_contract["system"]
        generated = self.generation.generate(GenerationRequest(
            task_class="project.blueprint", operation="BLUEPRINT_DESIGN", project_id=blueprint.project_id,
            capability_ref="project.blueprint.design@1", provider_id=self.config.model,
            system=system,
            goal=prompt, contract={}, state={}, failure_evidence={},
            schema_name=request_contract["schema_name"], schema=schema,
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
            "contract_version": request_contract["contract_version"],
            "schema_chars": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))),
            "system_prompt_chars": len(system),
            "projected_prompt_chars": len(json.dumps(prompt, ensure_ascii=False, separators=(",", ":"))),
        })
        value = parse_json_object(generated.completion.text)
        return MinimalBlueprintDesignPayload.from_dict(value)


@dataclass(frozen=True)
class AcceptanceAttributionDecision:
    requirement_id: str
    owner_unit_id: str
    action: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AcceptanceAttributionDecision":
        if set(value) != {"requirement_id", "owner_unit_id", "action"}:
            raise ValueError("invalid acceptance attribution decision")
        decision = cls(str(value["requirement_id"]), str(value["owner_unit_id"]), str(value["action"]))
        if not decision.requirement_id or decision.action not in {FailureAction.REPAIR_EXISTING.value, FailureAction.STOP.value}:
            raise ValueError("invalid acceptance attribution decision")
        if decision.action == FailureAction.REPAIR_EXISTING.value and not decision.owner_unit_id:
            raise ValueError("repair attribution requires an owner")
        if decision.action == FailureAction.STOP.value and decision.owner_unit_id:
            raise ValueError("STOP attribution cannot name an owner")
        return decision


class AcceptanceAttributor(Protocol):
    calls: list[dict[str, Any]]

    def attribute(
        self, *, project_id: str, public_goal: str,
        failed_requirement_ids: tuple[str, ...], public_requirement_summaries: Mapping[str, str],
        blueprint: ProjectBlueprint, candidate_owner_unit_ids: tuple[str, ...],
        observed_public_interfaces: Mapping[str, Any], run_id: str,
    ) -> tuple[AcceptanceAttributionDecision, ...]: ...


class ProviderAcceptanceAttributor:
    """Bounded project-level decision over public contract facts only."""

    def __init__(self, client: ProductionGenerationClient, config: ModelRoleConfig):
        if config.role != "agent":
            raise ValueError("acceptance attributor requires agent role")
        self.generation = client
        self.config = replace(
            config, task_class="project.attribution", operation="ACCEPTANCE_ATTRIBUTION",
            max_output_tokens=min(config.max_output_tokens, 1200), reasoning_effort="none",
            thinking_mode="disabled",
        )
        self.calls: list[dict[str, Any]] = []

    def attribute(
        self, *, project_id: str, public_goal: str,
        failed_requirement_ids: tuple[str, ...], public_requirement_summaries: Mapping[str, str],
        blueprint: ProjectBlueprint, candidate_owner_unit_ids: tuple[str, ...],
        observed_public_interfaces: Mapping[str, Any], run_id: str,
    ) -> tuple[AcceptanceAttributionDecision, ...]:
        prompt = {
            "public_goal": public_goal,
            "failed_requirements": [
                {"requirement_id": requirement_id, "summary": public_requirement_summaries[requirement_id]}
                for requirement_id in failed_requirement_ids
            ],
            "units": [
                {
                    "unit_id": unit.unit_id, "kind": unit.kind, "purpose": unit.purpose,
                    "owns": list(unit.owns), "required_interfaces": list(unit.required_interfaces),
                    "acceptance": list(unit.acceptance),
                }
                for unit in blueprint.units
            ],
            "deterministic_candidate_owner_unit_ids": list(candidate_owner_unit_ids),
            "observed_public_interfaces": dict(observed_public_interfaces),
        }
        started = time.perf_counter()
        try:
            generated = self.generation.generate(GenerationRequest(
                task_class="project.attribution", operation="ACCEPTANCE_ATTRIBUTION",
                project_id=project_id, capability_ref="project.acceptance.attribution@1",
                provider_id=self.config.model,
                system=(
                    "You are the existing project coordinator in bounded ATTRIBUTION mode. "
                    "Return only the requested attribution object. For every failed public requirement, "
                    "choose REPAIR_EXISTING with one existing Unit ID only when that Unit owns the public "
                    "contract responsibility; otherwise choose STOP with an empty owner. Do not modify the "
                    "Blueprint, write source code, run commands, or infer any hidden test detail."
                ),
                goal=prompt, contract={"existing_unit_ids": [unit.unit_id for unit in blueprint.units]},
                state={"observed_public_interfaces": dict(observed_public_interfaces)},
                failure_evidence={"failed_requirements": prompt["failed_requirements"]},
                schema_name="cgkn_acceptance_attribution", schema=ACCEPTANCE_ATTRIBUTION_SCHEMA,
                model_config=self.config, lesson_policy="DISABLED_BY_POLICY",
                allowed_actions=(FailureAction.REPAIR_EXISTING.value, FailureAction.STOP.value),
                forbidden_actions=("blueprint_change", "source_write", "shell", "hidden_acceptance"),
                run_id=run_id, projected_prompt=prompt,
            ))
        except GatewayCompletionError as exc:
            receipt = dict(exc.evidence or {})
            self.calls.append(self._call_record(started, receipt, None, failed=True))
            raise
        completion = generated.completion
        receipt = dict(completion.selection_receipt)
        self.calls.append(self._call_record(started, receipt, completion, failed=False))
        try:
            value = parse_json_object(completion.text)
            if set(value) != {"schema_version", "decisions"} or value.get("schema_version") != "1.0":
                raise ValueError("invalid acceptance attribution envelope")
            decisions = tuple(AcceptanceAttributionDecision.from_dict(item) for item in value.get("decisions", ()))
            if not decisions:
                raise ValueError("acceptance attribution requires decisions")
            return decisions
        except (TypeError, ValueError):
            self.calls[-1].update({"result": "FAILED", "failure_type": "INVALID_ATTRIBUTION_OUTPUT"})
            raise

    def _call_record(self, started: float, receipt: Mapping[str, Any], completion: Any | None, *, failed: bool) -> dict[str, Any]:
        usage = dict(completion.usage) if completion is not None else dict(receipt.get("usage") or {})
        metadata = dict(completion.transport_metadata) if completion is not None else {}
        def token(primary: str, alternate: str = "") -> int | None:
            value = usage.get(primary, receipt.get(primary))
            if value is None and alternate:
                value = usage.get(alternate, receipt.get(alternate))
            return int(value) if value is not None else None
        attempts = completion.attempts if completion is not None else receipt.get("transport_attempts")
        return {
            "role": "coordinator_attribution", "operation": "ACCEPTANCE_ATTRIBUTION",
            "model": completion.model if completion is not None else str(receipt.get("model") or self.config.model),
            "request_id": completion.request_id if completion is not None else str(receipt.get("request_id") or ""),
            "logical_calls": 1, "transport_attempts": attempts,
            "prompt_tokens": token("prompt_tokens", "input_tokens"),
            "completion_tokens": token("completion_tokens", "output_tokens"),
            "cached_tokens": token("cached_tokens"), "reasoning_tokens": token("reasoning_tokens"),
            "total_tokens": token("total_tokens"),
            "usage_status": "REPORTED" if usage else "UNKNOWN_AFTER_FAILURE" if failed else "UNREPORTED",
            "finish_reason": receipt.get("finish_reason"),
            "thinking_mode": self.config.thinking_mode, "reasoning_effort": self.config.reasoning_effort,
            "schema_hash": receipt.get("schema_hash"), "prompt_hash": receipt.get("prompt_hash"),
            "selection_receipt_hash": canonical_hash(receipt) if receipt else None,
            "selection_receipt": dict(receipt), "transport_metadata": metadata,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "result": "FAILED" if failed else "SUCCEEDED",
        }


class BlueprintUnitExecutor:
    descriptor = ExecutorDescriptor("llm.cheap@1", "blueprint_unit_worker", ("project.unit.implementation@1", "project.unit.tests@1", "project.unit.documentation@1"), ("filesystem.read", "filesystem.write"), supports_cost_reporting=True)

    def __init__(
        self,
        root: pathlib.Path | str,
        client: CompletionClient | ProductionGenerationClient,
        config: ModelRoleConfig,
        repair_config: ModelRoleConfig | None = None,
        *,
        materialization_policy: str = "INCREMENTAL",
        repair_evidence_mode: str = DEFAULT_REPAIR_EVIDENCE_MODE,
        repair_scope_mode: str = DEFAULT_REPAIR_SCOPE_MODE,
    ):
        if config.role != "worker": raise ValueError("unit executor requires worker role")
        if repair_config is not None and repair_config.role != "worker": raise ValueError("repair executor requires worker role")
        if materialization_policy not in {"INCREMENTAL", "FULL_RETRY"}: raise ValueError("invalid materialization policy")
        if repair_evidence_mode not in REPAIR_EVIDENCE_MODES: raise ValueError("invalid repair evidence mode")
        if repair_scope_mode not in REPAIR_SCOPE_MODES: raise ValueError("invalid repair scope mode")
        self.root = pathlib.Path(root).resolve()
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.config = config
        self.repair_config = repair_config or config
        self.materialization_policy = materialization_policy
        self.repair_evidence_mode = repair_evidence_mode
        self.repair_scope_mode = repair_scope_mode
        self.failure_reports: dict[str, FailureReport] = {}
        self.generation_failure_reports: dict[str, FailureReport] = {}
        self.materialized_units: dict[str, tuple[tuple[str, ...], str]] = {}
        self.materialization_call_counts: dict[str, int] = {}
        self.test_authority_receipts: dict[str, TestAuthorityReceipt] = {}
        self.repair_targets: dict[str, RepairTargetSpec] = {}
        self.repair_attempt_history: dict[str, list[RepairAttemptEvidence]] = {}
        self.calls: list[dict[str, Any]] = []

    def _test_authority_receipt(
        self, unit: BlueprintUnit, sources: Mapping[str, str], node_config: Mapping[str, Any],
    ) -> TestAuthorityReceipt | None:
        if unit.kind != UnitKind.TESTS.value:
            return None
        raw_projection = node_config.get("public_contract_projection")
        if not isinstance(raw_projection, Mapping):
            # Direct executor protocol tests and compatibility callers may not
            # carry project-level case identity.  The canonical project loop
            # always injects a projection through ``compile_blueprint``.
            return None
        projection = PublicContractProjection.from_dict(raw_projection)
        receipt = TestAuthorityFirewall().validate(
            {path: sources[path] for path in unit.owns if path in sources},
            projection,
            required_requirement_ids=tuple(str(item) for item in node_config.get("owned_public_requirement_ids", ())),
        )
        self.test_authority_receipts[unit.unit_id] = receipt
        return receipt

    @staticmethod
    def _raise_for_test_authority(receipt: TestAuthorityReceipt, *, retryable: bool) -> None:
        if receipt.status == "PASS":
            return
        priority = (
            "TEST_CONTRACT_CONFLICT", "TEST_CONTRACT_UNMAPPED_ASSERTION",
            "TEST_CONTRACT_UNPROVEN", "TEST_NON_NORMATIVE_ASSERTION",
            "PUBLIC_REQUIREMENT_UNCOVERED",
        )
        failure_type = next((item for item in priority if item in receipt.classifications), "TEST_CONTRACT_UNPROVEN")
        findings = "; ".join(
            f"{item.file}:{item.line} {item.authority.value}: {item.reason}"
            for item in receipt.findings[:8]
            if item.authority.value != "TEST_INTERNAL_ASSERTION"
        )
        raise UnitOutputValidationError(failure_type, findings or "Test Authority Firewall rejected generated tests", retryable=retryable)

    def _validate_staged_tests(
        self,
        unit: BlueprintUnit,
        candidate_files: Mapping[str, str],
        authority_receipt: TestAuthorityReceipt | None = None,
        node_config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if unit.kind != UnitKind.TESTS.value:
            return None
        with tempfile.TemporaryDirectory(prefix="cgkn-tests-stage-") as temporary:
            staged_root = pathlib.Path(temporary) / "workspace"
            shutil.copytree(
                self.root,
                staged_root,
                ignore=shutil.ignore_patterns(".git", ".cgkn", ".pytest_cache", "__pycache__", "*.pyc"),
            )
            for relative, content in candidate_files.items():
                target = staged_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            environment = os.environ.copy()
            # Generated-project tests must not inherit arbitrary workstation
            # pytest plugins.  The same isolation is used by the other CGKN
            # verification executors; without it an unrelated broken plugin
            # can turn valid staged source into UNIT_OUTPUT_INVALID.
            environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q"],
                cwd=staged_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=max(1, unit.timeout_seconds),
                check=False,
            )
        receipt = {
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-2000:],
        }
        if completed.returncode != 0:
            detail = (completed.stdout or completed.stderr or "staged pytest failed")[-3500:]
            failed_tests = tuple(re.findall(r"(?m)^FAILED\s+[^\s:]+::([A-Za-z_]\w*)", completed.stdout))
            valid_external_tests = {
                item.test_id for item in (authority_receipt.findings if authority_receipt else ())
                if item.authority is AssertionAuthority.TEST_CONTRACT_VALID
            }
            assertion_failure = "AssertionError" in completed.stdout or bool(re.search(r"(?m)^E\s+assert\b", completed.stdout))
            implementation_owners = tuple(unit.depends_on)
            if (
                authority_receipt is not None
                and authority_receipt.status == "PASS"
                and failed_tests
                and set(failed_tests) <= valid_external_tests
                and assertion_failure
                and len(implementation_owners) == 1
            ):
                owner_unit_id = implementation_owners[0]
                target: RepairTargetSpec | None = None
                raw_projection = (node_config or {}).get("public_contract_projection")
                baseline = self.materialized_units.get(owner_unit_id)
                if isinstance(raw_projection, Mapping) and baseline is not None:
                    target = build_public_test_repair_target(
                        findings=authority_receipt.findings,
                        failed_test_ids=failed_tests,
                        projection=PublicContractProjection.from_dict(raw_projection),
                        public_failure_output=completed.stdout,
                        owner_unit_id=owner_unit_id,
                        baseline_hash=baseline[1],
                    )
                    if target is not None:
                        baseline_validation = CanonicalRepairTargetValidator().validate(target, self.root)
                        if baseline_validation.status == "FAIL" and baseline_validation.fingerprint is not None:
                            target = RepairTargetSpec(
                                baseline_validation.fingerprint,
                                target.operation,
                                target.setup,
                                target.expected,
                            )
                        else:
                            target = None
                    if target is not None:
                        owner_sources = _read_sources(self.root, baseline[0])
                        _, _, locator = localize_repair_sources(owner_sources, target.fingerprint)
                        fingerprint = replace(target.fingerprint, relevant_source_locator=locator, fingerprint_hash="")
                        target = RepairTargetSpec(fingerprint, target.operation, target.setup, target.expected)
                        self.repair_targets[owner_unit_id] = target
                public_lines = []
                for raw in completed.stdout.splitlines():
                    line = raw.strip()
                    if line.startswith("FAILED ") or line.startswith("E "):
                        public_lines.append(line[:500])
                    if len(public_lines) >= 8:
                        break
                raise UnitOutputValidationError(
                    "PUBLIC_CONTRACT_FAILURE",
                    "Canonical generated public test rejected the implementation:\n" + "\n".join(public_lines),
                    failure_stage=FailureStage.TEST.value,
                    owner_unit_id=owner_unit_id,
                    details={"repair_target": target.as_dict() if target else None},
                )
            raise UnitOutputValidationError("TEST_FAILURE", detail, retryable=True)
        return receipt

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
        materialization: UnitMaterializationState | None = None
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
            project_goal = str(request.task_context.node_config.get("project_goal") or request.task_context.node_goal)
            if has_patchable_baseline and stored_failure is None and generation_failure is None:
                authority_receipt = self._test_authority_receipt(unit, sources, request.task_context.node_config)
                if authority_receipt is not None:
                    self._raise_for_test_authority(authority_receipt, retryable=False)
                reused_manifests = _manifests({path: sources[path] for path in unit.owns})
                duration = max(0, int((time.perf_counter() - clock) * 1000))
                unit_result = UnitResult(
                    unit.unit_id, "SUCCEEDED", unit.owns,
                    observed_interfaces=tuple(item.manifest_hash for item in reused_manifests.values()),
                    duration=duration, materialized_baseline=True,
                )
                return BlockExecutionResult(
                    request.project_id, request.run_id, request.attempt_id, request.node_id,
                    request.executor_ref, BlockStatus.SUCCEEDED,
                    outputs={
                        "unit_result": unit_result.as_dict(),
                        "summary": "reused unchanged committed Unit baseline",
                        "modified_files": [],
                        "observed_interfaces": {path: item.as_dict() for path, item in reused_manifests.items()},
                        "reused_materialized_baseline": True,
                        "test_authority_receipt": authority_receipt.as_dict() if authority_receipt else None,
                    },
                    started_at=started, ended_at=utc_now(), duration_ms=duration,
                )
            if failure:
                repair_attempt_number = 1 + sum(
                    call.get("unit_id") == unit.unit_id and call.get("call_class") == "REPAIR"
                    for call in self.calls
                )
                target = self.repair_targets.get(unit.unit_id)
                if failure.failure_type == "PUBLIC_CONTRACT_FAILURE" and target is None:
                    raise UnitOutputValidationError(
                        "REPAIR_TARGET_UNAVAILABLE",
                        "public-contract repair requires an exact deterministic validation target",
                        retryable=False,
                        failure_stage=FailureStage.TEST.value,
                        owner_unit_id=unit.unit_id,
                    )
                previous_attempts = self.repair_attempt_history.get(unit.unit_id, [])
                relevant_sources = dict(sources)
                relevant_functions: tuple[str, ...] = ()
                evidence_packet: dict[str, Any] | None = None
                failure_execution_slice: dict[str, Any] | None = None
                contrastive_public_evidence: dict[str, Any] | None = None
                if target is not None:
                    relevant_sources, relevant_functions, locator = localize_repair_sources(sources, target.fingerprint)
                    if locator != target.fingerprint.relevant_source_locator:
                        target = RepairTargetSpec(
                            replace(target.fingerprint, relevant_source_locator=locator, fingerprint_hash=""),
                            target.operation, target.setup, target.expected,
                        )
                        self.repair_targets[unit.unit_id] = target
                    if self.repair_evidence_mode in {
                        "FAILURE_SLICE_CONTRASTIVE",
                        "FAILURE_SLICE_TRANSPORT_CONTRASTIVE",
                    }:
                        execution_slice, contrastive_public_evidence = capture_public_failure_context(
                            target,
                            self.root,
                            sources,
                            include_transport_details=(
                                self.repair_evidence_mode == "FAILURE_SLICE_TRANSPORT_CONTRASTIVE"
                            ),
                        )
                        failure_execution_slice = execution_slice.as_dict()
                    packet = RepairEvidencePacket(
                        project_goal=project_goal,
                        unit_purpose=unit.purpose,
                        canonical_public_requirement="; ".join(unit.acceptance),
                        fingerprint=target.fingerprint,
                        exact_reproduction={
                            "setup": json.loads(target.setup),
                            "operation": json.loads(target.operation),
                            "expected": json.loads(target.expected),
                        },
                        relevant_files=relevant_sources,
                        relevant_functions=relevant_functions,
                        public_interfaces=tuple(
                            f"{path}:{name}"
                            for path, manifest in manifests.items()
                            for name in (
                                *(item.name for item in manifest.functions),
                                *(item.name for item in manifest.classes),
                            )
                        ),
                        previous_attempt=previous_attempts[-1] if previous_attempts else None,
                        failure_execution_slice=failure_execution_slice,
                        contrastive_public_evidence=contrastive_public_evidence,
                    )
                    evidence_packet = packet.as_dict()
                allowed_repair_paths = (
                    tuple(path for path in unit.owns if path in relevant_sources)
                    if self.repair_scope_mode == "LOCALIZED" and relevant_sources
                    else unit.owns
                )
                prompt = {
                    "mode": mode,
                    "repair_attempt_number": repair_attempt_number,
                    "unit": {
                        "unit_id": unit.unit_id,
                        "purpose": unit.purpose,
                        "owns": list(unit.owns),
                        "required_interfaces": list(unit.required_interfaces),
                    },
                    "public_constraints": list(request.task_context.project_constraints),
                    "repair_evidence_packet": evidence_packet,
                    "repair_evidence_mode": self.repair_evidence_mode,
                    "repair_scope": {
                        "mode": self.repair_scope_mode,
                        "allowed_files": list(allowed_repair_paths),
                        "target_symbol_hints": list(relevant_functions),
                    },
                    "direct_dependency_results": _dependency_prompt_projection(request.task_context.dependency_results),
                    "output_contract": "PatchBundle v2 only in REPAIR",
                }
                if evidence_packet is None:
                    # Repairs without a deterministic public target retain the
                    # broader compatibility projection.  Exact-target repairs
                    # already carry these facts once in RepairEvidencePacket.
                    prompt.update({
                        "project_goal": project_goal,
                        "normative_public_contract": project_goal,
                        "failure_report": failure.as_dict(),
                        "fallback_failure_report": failure.as_dict(),
                        "public_contract_projection": materialize_json(
                            request.task_context.node_config.get("public_contract_projection")
                        ),
                        "current_relevant_files": relevant_sources,
                        "current_files": relevant_sources,
                    })
                system = (
                    "You are a bounded unit repair worker. Return exactly one PatchBundle. Touch only unit.owns; "
                    "never change the blueprint, run commands, access hidden acceptance, create evidence, or invent paths. "
                    "Use PatchBundle v2 with one unique files[] object per modified file and one or more ordered edits. "
                    "Modify only the smallest non-empty subset needed. Preserve every required and observed public interface. "
                    "The repair_evidence_packet is the canonical public target: reproduce its exact input, explain internally "
                    "why the actual result differs from the expected result, and patch the localized implementation rather "
                    "than masking the symptom. Treat generated tests as non-authoritative examples and the canonical public "
                    "target as authoritative. On a repeated attempt, inspect previous_failed_attempt and choose a materially "
                    "different fix. Never weaken tests or alter the expected public result."
                )
                if target is None and unit.kind == UnitKind.TESTS.value:
                    system += (
                        " For a Tests Unit with a demonstrated contract conflict, modify, weaken, replace, or remove "
                        "conflicting assertions only as required to restore canonical public-contract alignment."
                    )
                generated = self.generation.generate(GenerationRequest(
                    task_class="project.codegen", operation=mode, project_id=request.project_id,
                    capability_ref=request.component_ref, provider_id=self.config.model,
                    system=system, goal=prompt,
                    contract={"unit": unit.as_dict(), "required_interfaces": list(unit.required_interfaces)},
                    state={
                        "files": relevant_sources,
                        "interfaces": {
                            key: value.as_dict() for key, value in manifests.items() if key in relevant_sources
                        },
                    },
                    failure_evidence=failure.as_dict(), schema_name="cgnk_unit_bundle", schema=patch_bundle_schema(allowed_repair_paths),
                    model_config=effective_config, allowed_actions=("patch_bundle",),
                    forbidden_actions=("shell", "network", "blueprint_change", "hidden_acceptance"), run_id=request.run_id,
                    projected_prompt=prompt, prompt_projection_hash=canonical_hash(prompt),
                ))
                completion = generated.completion; usage = dict(completion.usage)
                self.calls.append(self._call_record(
                    request, unit, mode, clock, config=effective_config, completion=completion,
                    call_class="REPAIR", prompt=prompt,
                ))
                self.calls[-1].update({
                    "repair_evidence_mode": self.repair_evidence_mode,
                    "repair_scope_mode": self.repair_scope_mode,
                    "allowed_repair_paths": list(allowed_repair_paths),
                    "repair_evidence_metrics": repair_evidence_metrics(evidence_packet) if evidence_packet else None,
                    "failure_execution_slice_hash": (
                        failure_execution_slice.get("slice_hash") if failure_execution_slice else None
                    ),
                    "contrastive_public_evidence_hash": (
                        contrastive_public_evidence.get("contrast_hash") if contrastive_public_evidence else None
                    ),
                })
                provider_recorded = True
                value = parse_json_object(completion.text)
                if str(value.get("unit_id", "")) != unit.unit_id:
                    raise UnitOutputValidationError("UNIT_OUTPUT_INVALID", "bundle unit_id mismatch")
                if value.get("kind") == "escalation":
                    raise RuntimeError(str(value.get("reason") or "worker escalation"))
                bundle = PatchBundle.from_dict(value)
                if bundle.needs_escalation: raise RuntimeError(bundle.escalation_reason or "worker escalation")
                actions = [{"action": "patch_file", "path": path, "edits": [{"find": find, "replace": replacement} for find, replacement in edits]} for path, edits in bundle.files]
                summary = bundle.summary
                changed = tuple(item["path"] for item in actions)
                if not changed or not set(changed) <= set(allowed_repair_paths):
                    raise UnitOutputValidationError("UNIT_OUTPUT_SCOPE_VIOLATION", "repair bundle must modify a non-empty subset of the allowed repair paths")
                modified_symbols = patch_modified_symbols(sources, bundle.files)
                target_symbol_entries = {
                    f"{path}:{symbol}" for path in relevant_sources for symbol in relevant_functions
                }
                target_symbol_hit = bool(set(modified_symbols).intersection(target_symbol_entries))
                self.calls[-1].update({
                    "modified_files": list(changed),
                    "modified_symbols": list(modified_symbols),
                    "target_symbols": sorted(target_symbol_entries),
                    "target_symbol_hit": target_symbol_hit,
                    "execution_path_overlap": bool(
                        failure_execution_slice
                        and set(modified_symbols).intersection(failure_execution_slice.get("executed_functions", ()))
                    ),
                })
                if self.repair_scope_mode == "LOCALIZED" and target_symbol_entries and not target_symbol_hit:
                    raise UnitOutputValidationError(
                        "UNIT_OUTPUT_SCOPE_VIOLATION",
                        "localized repair must overlap at least one deterministic target symbol",
                    )
                scope = WorkerScope(unit.owns + unit.reads, unit.owns, max_actions=unit.max_actions, max_write_files=unit.max_files, max_total_output_bytes=unit.max_output_bytes, allow_create=False, allow_patch=True, allow_delete=False)
                transaction = ScopedFileTransaction(self.root, scope)
                _, planned = transaction.validate(actions)
                new_sources = dict(sources)
                for item in planned: new_sources[item.relative] = item.content.decode("utf-8")
                authority_receipt = self._test_authority_receipt(unit, new_sources, request.task_context.node_config)
                if authority_receipt is not None:
                    self.calls[-1]["test_authority_receipt"] = authority_receipt.as_dict()
                    self._raise_for_test_authority(authority_receipt, retryable=False)
                staged_test_validation = self._validate_staged_tests(
                    unit, new_sources, authority_receipt, request.task_context.node_config,
                )
                if staged_test_validation is not None:
                    self.calls[-1]["staged_test_validation"] = staged_test_validation
                new_manifests = _manifests({path: new_sources[path] for path in unit.owns if path in new_sources})
                for path, before in manifests.items():
                    if path in unit.owns and path in new_manifests:
                        breaks = interface_breaks(before, new_manifests[path], unit.required_interfaces)
                        if breaks: raise PermissionError("interface guard: " + "; ".join(breaks))

                baseline_hash = self.materialized_units[unit.unit_id][1]
                candidate_state = RepairCandidateState(unit.unit_id, baseline_hash)
                candidate_state.transition(RepairCandidateStatus.PATCH_VALID)
                validation_receipt = None
                progress = RepairProgress.INCOMPARABLE
                regression: dict[str, Any] = {"status": "NOT_RUN"}
                with tempfile.TemporaryDirectory(prefix="cgkn-repair-candidate-") as temporary:
                    staged_root = pathlib.Path(temporary) / "workspace"
                    shutil.copytree(
                        self.root,
                        staged_root,
                        ignore=shutil.ignore_patterns(".git", ".cgkn", ".pytest_cache", "__pycache__", "*.pyc"),
                    )
                    for item in planned:
                        staged = staged_root / pathlib.PurePosixPath(item.relative)
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        staged.write_bytes(item.content)
                    candidate_state.transition(RepairCandidateStatus.STAGED)
                    candidate_state.transition(RepairCandidateStatus.TARGET_VALIDATING)
                    if target is not None:
                        validation_receipt = CanonicalRepairTargetValidator().validate(target, staged_root)
                        progress = classify_repair_progress(target.fingerprint, validation_receipt.fingerprint)
                        if validation_receipt.status != "PASS":
                            candidate_state.transition(RepairCandidateStatus.TARGET_FAIL)
                            candidate_state.transition(RepairCandidateStatus.DISCARDED)
                            evidence = RepairAttemptEvidence(
                                repair_attempt_number,
                                progress,
                                changed,
                                summarize_patch_diff(sources, new_sources, changed),
                                validation_receipt,
                            )
                            history = self.repair_attempt_history.setdefault(unit.unit_id, [])
                            history.append(evidence)
                            self.calls[-1].update({
                                "repair_candidate_state": candidate_state.as_dict(),
                                "repair_target": target.as_dict(),
                                "repair_progress": progress.value,
                                "repair_validation": validation_receipt.as_dict(),
                                "candidate_committed": False,
                                "candidate_diff": evidence.diff,
                                "relevant_files": list(relevant_sources),
                                "relevant_functions": list(relevant_functions),
                                "baseline_hash": baseline_hash,
                                "repair_target_rerun_count": 1,
                                "repair_no_progress": progress is RepairProgress.NO_PROGRESS,
                                "repair_exact_target_fixed": False,
                                "repair_candidate_rejected": True,
                                "repair_evidence_packet_hash": canonical_hash(evidence_packet) if evidence_packet else None,
                            })
                            same_no_progress = (
                                len(history) >= 2
                                and history[-1].progress is RepairProgress.NO_PROGRESS
                                and history[-2].progress is RepairProgress.NO_PROGRESS
                                and history[-1].validation.fingerprint is not None
                                and history[-2].validation.fingerprint is not None
                                and history[-1].validation.fingerprint.fingerprint_hash
                                == history[-2].validation.fingerprint.fingerprint_hash
                            )
                            failure_type = "REPAIR_STALLED" if same_no_progress else (
                                "REPAIR_NO_PROGRESS" if progress is RepairProgress.NO_PROGRESS else "REPAIR_TARGET_FAILURE"
                            )
                            raise UnitOutputValidationError(
                                failure_type,
                                f"repair candidate discarded: canonical target remains {validation_receipt.fingerprint.normalized_actual if validation_receipt.fingerprint else 'unresolved'}",
                                retryable=not same_no_progress,
                                failure_stage=FailureStage.UNIT_OUTPUT_VALIDATION.value,
                                owner_unit_id=unit.unit_id,
                                details={
                                    "repair_progress": progress.value,
                                    "repair_candidate_state": candidate_state.as_dict(),
                                    "repair_validation": validation_receipt.as_dict(),
                                },
                            )
                    candidate_state.transition(RepairCandidateStatus.TARGET_PASS)
                    regression = run_targeted_regression(staged_root)
                    if regression["status"] != "PASS":
                        candidate_state.transition(RepairCandidateStatus.DISCARDED)
                        self.calls[-1].update({
                            "repair_candidate_state": candidate_state.as_dict(),
                            "repair_progress": RepairProgress.REGRESSED.value,
                            "targeted_regression": regression,
                            "candidate_committed": False,
                            "baseline_hash": baseline_hash,
                            "repair_target_rerun_count": 1 if target is not None else 0,
                            "repair_no_progress": False,
                            "repair_exact_target_fixed": bool(target is not None),
                            "repair_candidate_rejected": True,
                            "repair_evidence_packet_hash": canonical_hash(evidence_packet) if evidence_packet else None,
                        })
                        raise UnitOutputValidationError(
                            "REPAIR_REGRESSION",
                            f"repair candidate discarded after {regression.get('stage')} regression failure",
                            retryable=True,
                            failure_stage=FailureStage.UNIT_OUTPUT_VALIDATION.value,
                            owner_unit_id=unit.unit_id,
                            details={"repair_candidate_state": candidate_state.as_dict(), "targeted_regression": regression},
                        )
                    candidate_state.transition(RepairCandidateStatus.REGRESSION_PASS)
                results = transaction.apply(actions)
                candidate_state.transition(RepairCandidateStatus.COMMITTED)
                self.register_materialized_baseline(unit)
                self.generation_failure_reports.pop(unit.unit_id, None)
                self.repair_targets.pop(unit.unit_id, None)
                self.repair_attempt_history.pop(unit.unit_id, None)
                unit_result = UnitResult(unit.unit_id, "SUCCEEDED", changed, observed_interfaces=tuple(item.manifest_hash for item in new_manifests.values()), provider_usage=tuple((str(key), str(value)) for key, value in sorted(usage.items())), duration=int((time.perf_counter() - clock) * 1000), materialized_baseline=True)
                self.calls[-1].update({
                    "unit_result": "SUCCEEDED",
                    "repair_candidate_state": candidate_state.as_dict(),
                    "repair_target": target.as_dict() if target else None,
                    "repair_progress": RepairProgress.FIXED.value if target else RepairProgress.INCOMPARABLE.value,
                    "repair_validation": validation_receipt.as_dict() if validation_receipt else None,
                    "targeted_regression": regression,
                    "candidate_committed": True,
                    "relevant_files": list(relevant_sources),
                    "relevant_functions": list(relevant_functions),
                    "baseline_hash": baseline_hash,
                    "repair_target_rerun_count": 1 if target is not None else 0,
                    "repair_no_progress": False,
                    "repair_exact_target_fixed": bool(target is not None),
                    "repair_candidate_rejected": False,
                    "repair_evidence_packet_hash": canonical_hash(evidence_packet) if evidence_packet else None,
                })
                outputs = {"unit_result": unit_result.as_dict(), "summary": summary, "modified_files": list(changed), "observed_interfaces": {path: item.as_dict() for path, item in new_manifests.items()}, "context_chars": len(json.dumps(prompt, ensure_ascii=False, sort_keys=True)), "included_files": list(sources), "included_interfaces": list(manifests), "included_dependencies": list(request.task_context.dependency_results), "action_results": results, "test_authority_receipt": authority_receipt.as_dict() if authority_receipt else None}
                return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=outputs, started_at=started, ended_at=utc_now(), duration_ms=unit_result.duration, usage=usage)

            materialization = UnitMaterializationState(unit.unit_id, unit.owns)
            materialization.record("EMPTY")
            prior_calls = self.materialization_call_counts.get(unit.unit_id, 0)
            next_call_class = "GENERATION_RETRY" if prior_calls else "GENERATION"
            last_summary = ""
            last_validation_feedback = ""
            while materialization.missing_paths:
                if self.materialization_call_counts.get(unit.unit_id, 0) >= MAX_UNIT_MATERIALIZATION_CALLS:
                    raise UnitOutputValidationError(
                        "UNIT_MATERIALIZATION_INCOMPLETE",
                        "Unit materialization call limit reached; missing owned paths: " + ", ".join(materialization.missing_paths),
                    )
                requested_paths = materialization.missing_paths
                staged_paths = tuple(path for path in unit.owns if path in materialization.staged_files)
                call_class = next_call_class
                staged_interfaces = _manifests(materialization.staged_files)
                staged_sibling_context = {path: materialization.staged_files[path] for path in staged_paths}
                prompt = {
                    "mode": "EXECUTE", "project_goal": project_goal,
                    "public_constraints": list(request.task_context.project_constraints),
                    "unit": {
                        "unit_id": unit.unit_id, "kind": unit.kind,
                        "purpose": unit.purpose, "instruction": unit.instruction,
                    },
                    "requested_paths": list(requested_paths),
                    "already_staged_paths": list(staged_paths),
                    "staged_sibling_context": staged_sibling_context,
                    "current_files": sources,
                    "observed_interfaces": {
                        **{path: item.as_dict() for path, item in manifests.items()},
                        **{path: item.as_dict() for path, item in staged_interfaces.items()},
                    },
                    "direct_dependency_results": _dependency_prompt_projection(request.task_context.dependency_results),
                    "acceptance": list(unit.acceptance),
                    "public_contract_projection": materialize_json(request.task_context.node_config.get("public_contract_projection")),
                    "owned_public_requirement_ids": list(request.task_context.node_config.get("owned_public_requirement_ids", ())),
                    "test_authority_findings": self.test_authority_receipts.get(unit.unit_id).as_dict() if unit.unit_id in self.test_authority_receipts else None,
                    "failure_report": generation_failure.as_dict() if generation_failure else None,
                    "generation_validation_feedback": last_validation_feedback,
                    "missing_path_reason": "complete the cohesive Unit without regenerating staged siblings",
                    "materialization_policy": self.materialization_policy,
                    "output_contract": "compact FileBundle v2 containing a non-empty subset of requested_paths only",
                }
                system = (
                    "You are a bounded CGNK cohesive-Unit materialization worker. Return exactly one compact FileBundle v2. "
                    "Return only a non-empty subset of requested_paths and prefer completing every requested path in this call. "
                    "Every returned Python file must contain non-whitespace source text; use a short module docstring for marker files. "
                    "Never return already_staged_paths, any path outside requested_paths, Blueprint edits, shell actions, hidden acceptance, "
                    "schema echoes, Markdown fences, summaries, or natural-language explanation. Staged sibling context is read-only."
                )
                if unit.kind == UnitKind.TESTS.value:
                    system += (
                        " Generated tests are derivative validators, never a behavioral authority. Every externally observable "
                        "assertion must map to public_contract_projection and owned_public_requirement_ids. Do not invent exact "
                        "spacing, newline, ordering, wording, or formatting when the public contract leaves it unspecified. "
                        "Observe external CSV output losslessly: never filter, drop, strip, or normalize parsed rows before "
                        "comparison. Use an identity parser such as list(csv.reader(io.StringIO(result.stdout))); an extra "
                        "blank row must remain observable so the test can expose newline defects. "
                        "For subprocess CLI tests, keep the project workspace importable: run from the project root or preserve "
                        "the project root on PYTHONPATH; never switch only to a temporary-data directory for python -m package."
                    )
                materialization.begin_call(call_class, requested_paths)
                self.materialization_call_counts[unit.unit_id] = self.materialization_call_counts.get(unit.unit_id, 0) + 1
                try:
                    generated = self.generation.generate(GenerationRequest(
                        task_class="project.codegen", operation="EXECUTE", project_id=request.project_id,
                        capability_ref=request.component_ref, provider_id=self.config.model,
                        system=system, goal=prompt,
                        contract={
                            "unit_id": unit.unit_id, "requested_paths": list(requested_paths),
                            "required_interfaces": list(unit.required_interfaces),
                        },
                        state={
                            "formal_files": sources, "staged_paths": list(staged_paths),
                            "interfaces": prompt["observed_interfaces"],
                        },
                        failure_evidence=generation_failure.as_dict() if generation_failure else {},
                        schema_name="cgnk_unit_bundle", schema=file_bundle_schema(requested_paths),
                        model_config=effective_config, allowed_actions=("file_bundle",),
                        forbidden_actions=("shell", "network", "blueprint_change", "hidden_acceptance"), run_id=request.run_id,
                        projected_prompt=prompt, prompt_projection_hash=canonical_hash(prompt),
                    ))
                except GatewayCompletionError as exc:
                    self.calls.append(self._call_record(
                        request, unit, mode, clock, config=effective_config, error=exc,
                        call_class=call_class, prompt=prompt, requested_paths=requested_paths,
                        staged_paths=staged_paths,
                    ))
                    provider_recorded = True
                    evidence = dict(getattr(exc, "evidence", {}) or {})
                    materialization.add_usage(dict(evidence.get("usage", {}) or {}))
                    self.calls[-1].update({
                        "unit_result": "RETRYABLE_RESPONSE_FAILURE",
                        "materialization_status": materialization.status,
                        "missing_paths_after_call": list(materialization.missing_paths),
                    })
                    materialization.record(
                        "PARTIAL" if materialization.staged_files else "EMPTY",
                        call_class=call_class, reason=str(getattr(exc, "category", "PROVIDER_FAILURE")),
                    )
                    if self.materialization_call_counts.get(unit.unit_id, 0) >= MAX_UNIT_MATERIALIZATION_CALLS:
                        raise UnitOutputValidationError(
                            "PROVIDER_FAILURE", "Provider failure exhausted Unit materialization calls",
                        ) from exc
                    next_call_class = "GENERATION_RETRY"
                    continue
                completion = generated.completion
                usage = self._merge_usage(usage, dict(completion.usage))
                materialization.add_usage(dict(completion.usage))
                self.calls.append(self._call_record(
                    request, unit, mode, clock, config=effective_config, completion=completion,
                    call_class=call_class, prompt=prompt, requested_paths=requested_paths,
                    staged_paths=staged_paths,
                ))
                provider_recorded = True
                response_error: UnitOutputValidationError | None = None
                bundle: FileBundle | None = None
                returned_paths: tuple[str, ...] = ()
                candidate_files: dict[str, str] = dict(materialization.staged_files)
                candidate_bytes = materialization.total_output_bytes
                try:
                    value = parse_json_object(completion.text)
                    if str(value.get("unit_id", "")) != unit.unit_id:
                        raise UnitOutputValidationError("UNIT_OUTPUT_INVALID", "bundle unit_id mismatch", retryable=True)
                    if value.get("kind") == "escalation":
                        raise UnitOutputValidationError("PROVIDER_FAILURE", str(value.get("reason") or "worker escalation"))
                    raw_files = value.get("files")
                    if not isinstance(raw_files, list) or not raw_files:
                        raise UnitOutputValidationError("UNIT_OUTPUT_INVALID", "FileBundle files must be non-empty", retryable=True)
                    raw_paths = tuple(str(item.get("path", "")) for item in raw_files if isinstance(item, Mapping))
                    if len(raw_paths) != len(raw_files) or len(set(raw_paths)) != len(raw_paths):
                        raise UnitOutputValidationError("UNIT_OUTPUT_INVALID", "FileBundle contains duplicate or malformed paths")
                    bundle = FileBundle.from_dict(value)
                    if bundle.needs_escalation:
                        raise UnitOutputValidationError("PROVIDER_FAILURE", bundle.escalation_reason or "worker escalation")
                    returned_paths = tuple(path for path, _ in bundle.files)
                    empty_python_paths = tuple(
                        path for path, content in bundle.files
                        if path.endswith(".py") and not content.strip()
                    )
                    if empty_python_paths:
                        raise UnitOutputValidationError(
                            "UNIT_OUTPUT_INVALID",
                            "Python source files must contain source text: " + ", ".join(empty_python_paths),
                            retryable=True,
                        )
                    staged_repeats = tuple(path for path in returned_paths if path in materialization.staged_files)
                    outside_unit = tuple(path for path in returned_paths if path not in unit.owns)
                    outside_request = tuple(path for path in returned_paths if path not in requested_paths)
                    if staged_repeats or outside_unit or outside_request:
                        raise UnitOutputValidationError(
                            "UNIT_OUTPUT_SCOPE_VIOLATION",
                            "FileBundle returned paths outside requested_paths",
                        )
                    slice_actions = [{"action": "write_file", "path": path, "content": content} for path, content in bundle.files]
                    candidate_files.update(dict(bundle.files))
                    candidate_bytes = sum(len(content.encode("utf-8")) for content in candidate_files.values())
                    if candidate_bytes > unit.max_output_bytes:
                        raise UnitOutputValidationError("UNIT_OUTPUT_BUDGET_EXCEEDED", "Unit staged output exceeds max_output_bytes")
                    scope = WorkerScope(unit.owns + unit.reads, unit.owns, max_actions=unit.max_actions, max_write_files=unit.max_files, max_total_output_bytes=unit.max_output_bytes, allow_create=True, allow_patch=True, allow_delete=False)
                    try:
                        ScopedFileTransaction(self.root, scope).validate(slice_actions)
                    except ScopeViolation as exc:
                        if "syntax validation" in str(exc):
                            raise UnitOutputValidationError("SYNTAX_ERROR", str(exc), retryable=True) from exc
                        raise UnitOutputValidationError("UNIT_OUTPUT_SCOPE_VIOLATION", str(exc)) from exc
                    if set(candidate_files) == set(unit.owns):
                        authority_receipt = self._test_authority_receipt(unit, candidate_files, request.task_context.node_config)
                        if authority_receipt is not None:
                            self.calls[-1]["test_authority_receipt"] = authority_receipt.as_dict()
                            if authority_receipt.status != "PASS":
                                materialization.staged_files.clear()
                                materialization.total_output_bytes = 0
                                self._raise_for_test_authority(authority_receipt, retryable=True)
                        staged_test_validation = self._validate_staged_tests(
                            unit, candidate_files, authority_receipt, request.task_context.node_config,
                        )
                        if staged_test_validation is not None:
                            self.calls[-1]["staged_test_validation"] = staged_test_validation
                except UnitOutputValidationError as exc:
                    response_error = exc
                except (ValueError, TypeError) as exc:
                    response_error = UnitOutputValidationError("UNIT_OUTPUT_INVALID", str(exc), retryable=True)

                if response_error is not None:
                    last_validation_feedback = f"{response_error.failure_type}: {response_error}"
                    self.calls[-1].update({
                        "unit_result": "RETRYABLE_RESPONSE_FAILURE" if response_error.retryable else "FAILED",
                        "failure_type": response_error.failure_type,
                        "materialization_status": materialization.status,
                        "missing_paths_after_call": list(materialization.missing_paths),
                        "returned_paths": list(returned_paths),
                    })
                    if not response_error.retryable:
                        raise response_error
                    stalled = materialization.record_no_progress(call_class, response_error.failure_type)
                    if stalled:
                        raise UnitOutputValidationError(
                            "UNIT_MATERIALIZATION_STALLED",
                            "two consecutive attempts added no acceptable coverage for: "
                            + ", ".join(materialization.missing_paths),
                        ) from response_error
                    if self.materialization_call_counts.get(unit.unit_id, 0) >= MAX_UNIT_MATERIALIZATION_CALLS:
                        raise UnitOutputValidationError(
                            "UNIT_MATERIALIZATION_INCOMPLETE",
                            "Unit materialization call limit reached after invalid response; missing owned paths: "
                            + ", ".join(materialization.missing_paths),
                        ) from response_error
                    next_call_class = "GENERATION_RETRY"
                    continue

                assert bundle is not None
                if self.materialization_policy == "FULL_RETRY" and set(returned_paths) != set(requested_paths):
                    raise UnitOutputValidationError(
                        "UNIT_OUTPUT_INCOMPLETE",
                        "FULL_RETRY policy discards partial output; missing owned paths: "
                        + ", ".join(path for path in requested_paths if path not in returned_paths),
                    )
                materialization.staged_files.update(dict(bundle.files))
                materialization.no_progress_attempts = 0
                materialization.last_unresolved_paths = ()
                materialization.total_output_bytes = candidate_bytes
                last_summary = bundle.summary
                self.calls[-1].update({
                    "returned_paths": list(returned_paths), "newly_materialized_paths": list(returned_paths),
                    "returned_bytes_by_path": {path: len(content.encode("utf-8")) for path, content in bundle.files},
                    "missing_paths_after_call": list(materialization.missing_paths),
                    "materialization_status": "PARTIAL" if materialization.missing_paths else "COMPLETE",
                    "staged_sibling_chars": sum(len(value) for value in staged_sibling_context.values()),
                })
                if materialization.missing_paths:
                    materialization.record("PARTIAL", returned_paths=returned_paths, call_class=call_class)
                    self.calls[-1]["unit_result"] = "PARTIAL_VALID_OUTPUT"
                    next_call_class = "GENERATION_CONTINUATION"
                    continue
                materialization.record("COMPLETE", returned_paths=returned_paths, call_class=call_class)

            aggregate_actions = [
                {"action": "write_file", "path": path, "content": materialization.staged_files[path]}
                for path in unit.owns
            ]
            materialization.record("VALIDATING")
            scope = WorkerScope(unit.owns + unit.reads, unit.owns, max_actions=unit.max_actions, max_write_files=unit.max_files, max_total_output_bytes=unit.max_output_bytes, allow_create=True, allow_patch=True, allow_delete=False)
            transaction = ScopedFileTransaction(self.root, scope)
            _, planned = transaction.validate(aggregate_actions)
            new_sources = dict(sources)
            for item in planned: new_sources[item.relative] = item.content.decode("utf-8")
            if set(materialization.staged_files) != set(unit.owns):
                raise UnitOutputValidationError("UNIT_MATERIALIZATION_INCOMPLETE", "Unit staging does not cover exact owned paths")
            consistency_failures = _cross_file_consistency_failures(new_sources)
            if consistency_failures:
                raise PermissionError("interface guard: " + "; ".join(consistency_failures))
            new_manifests = _manifests({path: new_sources[path] for path in unit.owns})
            # Implementation Units must provide their declared interfaces. Tests and
            # documentation consume interfaces from their bounded read dependencies,
            # so validate those declarations against the complete visible Unit scope.
            required_interface_paths = unit.owns if unit.kind == "implementation" else tuple(
                dict.fromkeys((*unit.owns, *unit.reads))
            )
            required_manifests = _manifests({
                path: new_sources[path] for path in required_interface_paths if path in new_sources
            })
            required_failures = _required_interface_failures(required_manifests, unit.required_interfaces)
            if required_failures:
                raise PermissionError("interface guard: " + "; ".join(required_failures))
            for path, before in manifests.items():
                if path in unit.owns and path in new_manifests:
                    breaks = interface_breaks(before, new_manifests[path], unit.required_interfaces)
                    if breaks: raise PermissionError("interface guard: " + "; ".join(breaks))
            materialization.record("VALIDATED")
            materialization.record("COMMITTING")
            try:
                results = transaction.apply(aggregate_actions)
            except CommitFailure as exc:
                raise UnitOutputValidationError("COMMIT_FAILURE", str(exc)) from exc
            self.register_materialized_baseline(unit)
            self.generation_failure_reports.pop(unit.unit_id, None)
            materialization.record("COMMITTED")
            changed = unit.owns
            unit_result = UnitResult(unit.unit_id, "SUCCEEDED", changed, observed_interfaces=tuple(item.manifest_hash for item in new_manifests.values()), provider_usage=tuple((str(key), str(value)) for key, value in sorted(usage.items())), duration=int((time.perf_counter() - clock) * 1000), materialized_baseline=True)
            self.calls[-1]["unit_result"] = "SUCCEEDED"
            self.calls[-1]["materialization_status"] = "COMMITTED"
            outputs = {
                "unit_result": unit_result.as_dict(), "summary": last_summary,
                "modified_files": list(changed),
                "observed_interfaces": {path: item.as_dict() for path, item in new_manifests.items()},
                "context_chars": sum(int(call.get("context_chars") or 0) for call in self.calls if call.get("unit_id") == unit.unit_id),
                "included_files": list(sources), "included_interfaces": list(manifests),
                "included_dependencies": list(request.task_context.dependency_results),
                "action_results": results, "unit_materialization": materialization.as_dict(),
                "test_authority_receipt": self.test_authority_receipts.get(unit.unit_id).as_dict() if unit.unit_id in self.test_authority_receipts else None,
            }
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs=outputs, started_at=started, ended_at=utc_now(), duration_ms=unit_result.duration, usage=usage)
        except Exception as exc:
            if isinstance(exc, GatewayCompletionError) and unit is not None and not provider_recorded:
                effective_config = self.repair_config if mode == "REPAIR" else self.config
                self.calls.append(self._call_record(request, unit, mode, clock, config=effective_config, error=exc))
            if materialization is not None and materialization.status != "COMMITTED":
                materialization.record("FAILED", reason=str(getattr(exc, "failure_type", type(exc).__name__)))
                materialization.staged_files.clear()
                materialization.total_output_bytes = 0
                materialization.record("DISCARDED", reason=str(getattr(exc, "failure_type", type(exc).__name__)))
            policy = isinstance(exc, PermissionError)
            code = ExecutionErrorCode.POLICY_BLOCKED if policy else ExecutionErrorCode.INVALID_OUTPUT if isinstance(exc, ValueError) else ExecutionErrorCode.EXECUTION_ERROR
            failure_stage = str(getattr(exc, "failure_stage", "") or FailureStage.UNIT_OUTPUT_VALIDATION.value)
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
            elif failure_type == "COMMIT_FAILURE":
                failure_stage = FailureStage.MATERIALIZATION.value
            details = {
                "failure_stage": failure_stage,
                "failure_type": failure_type,
                "origin_unit_id": unit.unit_id if unit is not None else request.node_id,
                "operation": mode,
                "materialized_baseline": bool(unit is not None and self.has_materialized_baseline(unit.unit_id)),
            }
            if isinstance(exc, UnitOutputValidationError):
                details.update(exc.details)
            explicit_owner = str(getattr(exc, "owner_unit_id", "") or "")
            if explicit_owner:
                details["owner_unit_id"] = explicit_owner
            if unit is not None and unit.unit_id in self.test_authority_receipts:
                details["test_authority_receipt_hash"] = self.test_authority_receipts[unit.unit_id].receipt_hash
            if provider_recorded and self.calls:
                self.calls[-1]["unit_result"] = "FAILED"
                self.calls[-1]["failure_stage"] = failure_stage
                if not self.calls[-1].get("failure_type"):
                    self.calls[-1]["failure_type"] = failure_type
            outputs = {"unit_materialization": materialization.as_dict()} if materialization is not None else {}
            if unit is not None and unit.unit_id in self.test_authority_receipts:
                outputs["test_authority_receipt"] = self.test_authority_receipts[unit.unit_id].as_dict()
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, outputs=outputs, error=ExecutionError(code, str(exc), details), started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage, retryable=not policy)

    @staticmethod
    def _merge_usage(current: Mapping[str, Any], addition: Mapping[str, Any]) -> dict[str, Any]:
        keys = set(current) | set(addition)
        merged: dict[str, Any] = {}
        for key in keys:
            left, right = current.get(key), addition.get(key)
            if isinstance(left, int) and isinstance(right, int):
                merged[key] = left + right
            elif left is None:
                merged[key] = right
            elif right is None:
                merged[key] = left
            else:
                merged[key] = right
        return merged

    def _call_record(
        self, request: BlockExecutionRequest, unit: BlueprintUnit, mode: str, clock: float, *,
        config: ModelRoleConfig, completion: Any | None = None, error: GatewayCompletionError | None = None,
        call_class: str | None = None, prompt: Mapping[str, Any] | None = None,
        requested_paths: tuple[str, ...] = (), staged_paths: tuple[str, ...] = (),
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
        effective_call_class = call_class or ("GENERATION_RETRY" if mode == "EXECUTE" and prior_generation_attempts else "GENERATION" if mode == "EXECUTE" else "REPAIR")
        context_chars = len(json.dumps(dict(prompt), ensure_ascii=False, sort_keys=True)) if prompt is not None else 0
        staged_sibling_chars = sum(
            len(str(value)) for value in dict(prompt or {}).get("staged_sibling_context", {}).values()
        )
        input_tokens = token("prompt_tokens", "input_tokens")
        actual_model = completion.model if completion is not None else str(receipt.get("model") or config.model)
        model_identity_kind = (
            "SNAPSHOT" if re.search(r"-(?:20\d{6}|\d{4})$", actual_model) else "STABLE_ALIAS"
        )
        return {
            "logical_call_id": f"{request.run_id}:{unit.unit_id}:{mode.lower()}:{len(self.calls) + 1}",
            "project_id": request.project_id, "run_id": request.run_id,
            "role": "worker", "operation": mode, "unit_id": unit.unit_id,
            "call_class": effective_call_class,
            "materialization_policy": self.materialization_policy,
            "provider": config.model,
            "model": actual_model,
            "model_identity_kind": model_identity_kind,
            "request_id": completion.request_id if completion is not None else str(receipt.get("request_id") or ""),
            "transport_attempts": attempts_detail if attempts_detail else attempt_count,
            "transport_attempt_count": int(attempt_count or (len(attempts_detail) if isinstance(attempts_detail, list) else 0)),
            "thinking_mode_requested": config.thinking_mode,
            "thinking_mode_forwarded": metadata.get("thinking_mode_forwarded", receipt.get("thinking_mode_forwarded")),
            "reasoning_effort": config.reasoning_effort,
            "temperature": metadata.get("temperature_requested", config.temperature),
            "temperature_status": "SENT_TO_GATEWAY",
            "top_p": metadata.get("top_p_requested"),
            "top_k": metadata.get("top_k_requested"),
            "seed": metadata.get("seed_requested"),
            "max_output_tokens": config.max_output_tokens,
            "response_format_mode": metadata.get("response_format_mode", "json_schema"),
            "stream_mode": metadata.get("stream_mode", False),
            "provider_request_hash": (
                metadata.get("provider_request_hash")
                or receipt.get("provider_request_hash")
                or reported_usage.get("provider_request_hash")
            ),
            "provider_request_hash_basis": (
                "GATEWAY_HTTP_PAYLOAD"
                if metadata.get("provider_request_hash") or receipt.get("provider_request_hash")
                else reported_usage.get("provider_request_hash_basis")
            ),
            "prompt_tokens": input_tokens,
            "completion_tokens": token("completion_tokens", "output_tokens"),
            "reasoning_tokens": token("reasoning_tokens"),
            "cached_tokens": token("cached_tokens"),
            "total_tokens": token("total_tokens"), "usage_status": usage_status,
            "finish_reason": receipt.get("finish_reason"),
            "configured_timeout": config.timeout_seconds,
            "effective_timeout": receipt.get("effective_request_timeout_seconds"),
            "elapsed_ms": int((time.perf_counter() - clock) * 1000),
            "context_chars": context_chars,
            "context_tokens": input_tokens,
            "staged_sibling_chars": staged_sibling_chars,
            "requested_paths": list(requested_paths),
            "staged_paths_before_call": list(staged_paths),
            "included_dependencies": list(request.task_context.dependency_results),
            "included_interfaces": sorted(dict(prompt or {}).get("observed_interfaces", {})),
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
    generation_calls: int
    generation_continuations: int
    generation_retry_calls: int
    generation_retries: int
    repair_calls: int
    repair_rounds: int
    attribution_calls: int
    failure_reports: tuple[FailureReport, ...]
    workspace: pathlib.Path
    run_root: pathlib.Path

    @property
    def status(self) -> str: return self.summary.status

    def as_dict(self) -> dict[str, Any]:
        return {"project_id": self.project_id, "run_id": self.run_id, "status": self.status, "blueprint": self.blueprint.as_dict(), "capability_tree": self.tree.as_dict(), "summary": self.summary.as_dict(), "provider_calls": self.provider_calls, "agent_decisions": self.agent_decisions, "materialization_calls": self.generation_attempts, "generation_attempts": self.generation_attempts, "generation_calls": self.generation_calls, "generation_continuations": self.generation_continuations, "generation_retry_calls": self.generation_retry_calls, "generation_retry_rounds": self.generation_retries, "generation_retries": self.generation_retries, "repair_calls": self.repair_calls, "repair_rounds": self.repair_rounds, "attribution_calls": self.attribution_calls, "failure_reports": [item.as_dict() for item in self.failure_reports], "workspace": str(self.workspace), "run_root": str(self.run_root)}


class MinimalProjectLoop:
    """L6 adapter: one frozen blueprint compiled to the canonical tree/DAG/runtime."""

    def __init__(self, repository_root: pathlib.Path | str, run_root: pathlib.Path | str, client: CompletionClient | ProductionGenerationClient, agent_config: ModelRoleConfig, worker_config: ModelRoleConfig, worker_repair_config: ModelRoleConfig | None = None, acceptance_attributor: AcceptanceAttributor | None = None):
        if agent_config.role != "agent" or worker_config.role != "worker": raise ValueError("coordinator and worker role contracts are required")
        self.repository_root = pathlib.Path(repository_root).resolve(); self.run_root = pathlib.Path(run_root).resolve()
        self.client = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        if self.client.max_provider_calls is None:
            self.client.max_provider_calls = 8
        self.agent_config = agent_config; self.worker_config = worker_config
        self.worker_repair_config = worker_repair_config or worker_config
        self.coordinator_calls: list[dict[str, Any]] = []
        self.acceptance_attributor = acceptance_attributor or ProviderAcceptanceAttributor(self.client, agent_config)
        self.attribution_calls = self.acceptance_attributor.calls

    def design(self, project_id: str, public_contract: Mapping[str, Any], designer: DesignClient | None = None) -> tuple[ProjectBlueprint, int]:
        draft = ProjectBlueprint("1.0", project_id, 1, str(public_contract["public_goal"]), tuple(str(item) for item in public_contract.get("constraints", ())), (), ())
        effective = designer or ProviderBlueprintDesigner(self.client, self.agent_config)
        try:
            payload = effective.design(draft, public_contract)
            frozen = assemble_project_blueprint(project_id, payload, public_contract)
        finally:
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
            is_acceptance_failure = any(
                check.check_id == failed_check and check.kind == UnitKind.ACCEPTANCE.value
                for check in blueprint.checks
            )
            report = (
                self._acceptance_failure_report(blueprint, failed_result, dag, worker, run_id)
                if is_acceptance_failure
                else self._failure_report(blueprint, failed_check, failed_result, dag, worker, failure_owner_hint)
            )
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
        generation_calls = sum(call.get("call_class") == "GENERATION" for call in worker.calls)
        generation_continuations = sum(call.get("call_class") == "GENERATION_CONTINUATION" for call in worker.calls)
        generation_retry_calls = sum(call.get("call_class") == "GENERATION_RETRY" for call in worker.calls)
        repair_calls = sum(call.get("operation") == "REPAIR" for call in worker.calls)
        outcome = ProjectLoopOutcome(blueprint.project_id, run_id, final_blueprint, tree, summary, len(worker.calls) + len(self.attribution_calls), len(self.attribution_calls), generation_attempts, generation_calls, generation_continuations, generation_retry_calls, generation_retries, repair_calls, repairs, len(self.attribution_calls), tuple(reports), workspace, state_root)
        _write_json(state_root / "project_outcome.json", outcome.as_dict())
        _write_json(state_root / "provider_calls.json", {"calls": worker.calls})
        _write_json(state_root / "attribution_calls.json", {"calls": self.attribution_calls})
        return outcome

    @staticmethod
    def _deterministic_acceptance_candidates(
        blueprint: ProjectBlueprint,
        requirement_summaries: Mapping[str, str],
    ) -> tuple[str, ...]:
        """Return exact public-contract matches only; semantic similarity is never authority."""
        candidates: set[str] = set()
        for summary in requirement_summaries.values():
            normalized = summary.casefold().strip()
            for unit in blueprint.units:
                exact_acceptance = any(normalized == item.casefold().strip() for item in unit.acceptance)
                explicit_path = any(path.casefold() in normalized or pathlib.PurePosixPath(path).name.casefold() in normalized for path in unit.owns)
                explicit_interface = any(
                    re.search(rf"\b{re.escape(interface.split('(', 1)[0].rsplit('.', 1)[-1].casefold())}\b", normalized)
                    for interface in unit.required_interfaces if interface.strip()
                )
                if exact_acceptance or explicit_path or explicit_interface:
                    candidates.add(unit.unit_id)
        return tuple(unit.unit_id for unit in blueprint.units if unit.unit_id in candidates)

    @staticmethod
    def _observed_public_interfaces(blueprint: ProjectBlueprint, worker: BlueprintUnitExecutor) -> dict[str, Any]:
        observed: dict[str, Any] = {}
        for unit in blueprint.units:
            manifests = _manifests(_read_sources(worker.root, unit.owns))
            observed[unit.unit_id] = {path: manifest.as_dict() for path, manifest in manifests.items()}
        return observed

    def _acceptance_failure_report(
        self, blueprint: ProjectBlueprint, result: BlockExecutionResult, dag: Any,
        worker: BlueprintUnitExecutor, run_id: str,
    ) -> FailureReport:
        details = dict(result.error.details) if result.error else {}
        failure_class = str(details.get("failure_class") or result.outputs.get("failure_class") or "")
        manifest_hash = str(details.get("requirement_manifest_hash") or result.outputs.get("requirement_manifest_hash") or "")
        mapping_complete = bool(details.get("mapping_complete", result.outputs.get("mapping_complete", False)))
        failed_requirement_ids = tuple(str(item) for item in details.get("failed_requirement_ids", result.outputs.get("failed_requirement_ids", ())))
        raw_summaries = details.get("public_requirement_summaries", result.outputs.get("public_requirement_summaries", {}))
        summaries = {str(key): str(value) for key, value in dict(raw_summaries or {}).items()}
        if failure_class == "HARNESS_ATTRIBUTION_UNAVAILABLE" or not mapping_complete or not failed_requirement_ids or set(summaries) != set(failed_requirement_ids):
            return FailureReport(
                "external_acceptance", "HARNESS_ATTRIBUTION_UNAVAILABLE",
                failure_stage=FailureStage.ACCEPTANCE.value, failed_check="external_acceptance",
                expected="mapped public acceptance requirements pass",
                observed="external acceptance requirement mapping unavailable",
                suggested_action="stop fail-closed; repair attribution evidence is unavailable",
                evidence_refs=("node_results/external_acceptance.json",),
                failed_requirement_ids=failed_requirement_ids,
                public_requirement_summaries=tuple((key, summaries[key]) for key in failed_requirement_ids if key in summaries),
                requirement_manifest_hash=manifest_hash, mapping_complete=False,
                attribution_status="UNAVAILABLE",
            )

        candidates = self._deterministic_acceptance_candidates(blueprint, summaries)
        owner = ""
        attribution_source = "DETERMINISTIC"
        attribution_status = "UNRESOLVED"
        if len(candidates) == 1 and worker.has_materialized_baseline(candidates[0]):
            owner = candidates[0]
            attribution_status = "RESOLVED"
        else:
            attribution_source = "COORDINATOR"
            try:
                decisions = self.acceptance_attributor.attribute(
                    project_id=blueprint.project_id, public_goal=blueprint.goal,
                    failed_requirement_ids=failed_requirement_ids,
                    public_requirement_summaries=summaries, blueprint=blueprint,
                    candidate_owner_unit_ids=candidates,
                    observed_public_interfaces=self._observed_public_interfaces(blueprint, worker),
                    run_id=run_id,
                )
                if len(decisions) != len(failed_requirement_ids) or {item.requirement_id for item in decisions} != set(failed_requirement_ids):
                    raise ValueError("attribution decisions must cover each failed public requirement exactly once")
                existing = set(blueprint.by_id)
                if any(item.owner_unit_id and item.owner_unit_id not in existing for item in decisions):
                    raise ValueError("attribution invented a Unit")
                if any(item.action == FailureAction.STOP.value for item in decisions):
                    owner = ""
                else:
                    owners = {item.owner_unit_id for item in decisions}
                    if len(owners) != 1:
                        raise ValueError("acceptance attribution must resolve to one repair owner")
                    proposed = next(iter(owners))
                    if not worker.has_materialized_baseline(proposed):
                        raise ValueError("attribution selected a Unit without materialized baseline")
                    owner = proposed
                    attribution_status = "RESOLVED"
            except (GatewayCompletionError, TypeError, ValueError):
                owner = ""
                attribution_status = "UNRESOLVED"

        action = FailureAction.REPAIR_EXISTING.value if owner else FailureAction.STOP.value
        baseline = bool(owner and worker.has_materialized_baseline(owner))
        affected = downstream_closure(dag, {owner}) if owner else ()
        return FailureReport(
            "external_acceptance", "ACCEPTANCE_FAILURE",
            failure_stage=FailureStage.ACCEPTANCE.value, owner_unit_id=owner,
            recovery_action=action, materialized_baseline=baseline,
            failed_check="external_acceptance", expected="public acceptance requirements pass",
            observed="public requirements remain unsatisfied",
            affected_units=affected,
            suggested_action="patch the attributed owner using public requirement evidence" if owner else "stop fail-closed; acceptance owner is unresolved",
            evidence_refs=("node_results/external_acceptance.json",),
            failed_requirement_ids=failed_requirement_ids,
            public_requirement_summaries=tuple((key, summaries[key]) for key in failed_requirement_ids),
            requirement_manifest_hash=manifest_hash, mapping_complete=True,
            candidate_owner_unit_ids=candidates, attribution_source=attribution_source,
            attribution_status=attribution_status,
        )

    @staticmethod
    def _owned_traceback_frames(
        blueprint: ProjectBlueprint, result: BlockExecutionResult,
    ) -> tuple[tuple[int, str, str, str], ...]:
        observed = (str(result.outputs.get("stderr", "")) + "\n" + str(result.outputs.get("stdout", ""))).replace("\\", "/")
        matches: list[tuple[int, str, str, str]] = []
        for frame in re.finditer(r"(?m)([^\r\n]*?\.py):(\d+)", observed):
            path = frame.group(1).strip().lstrip('> ').replace("\\", "/")
            for unit in blueprint.units:
                for owned in unit.owns:
                    if path == owned or path.endswith("/" + owned):
                        matches.append((frame.start(), unit.unit_id, owned, f"{owned}:{frame.group(2)}"))
        return tuple(matches)

    @classmethod
    def _owner_from_failure(cls, blueprint: ProjectBlueprint, result: BlockExecutionResult) -> str:
        frames = cls._owned_traceback_frames(blueprint, result)
        if frames:
            # Pytest renders the calling test frame before the innermost project
            # frame. The final owned traceback frame therefore identifies the
            # narrowest deterministic repair owner.
            return frames[-1][1]
        text = json.dumps(result.as_dict(), ensure_ascii=False).replace("\\\\", "/").replace("\\", "/")
        matches: list[tuple[int, str]] = []
        for unit in blueprint.units:
            for path in unit.owns:
                positions = [position for candidate in (path, pathlib.PurePosixPath(path).name) if (position := text.find(candidate)) >= 0]
                if positions:
                    matches.append((min(positions), unit.unit_id))
        return min(matches)[1] if matches else ""

    @classmethod
    def _pytest_owner_from_failure(cls, blueprint: ProjectBlueprint, result: BlockExecutionResult) -> str:
        frames = cls._owned_traceback_frames(blueprint, result)
        implementation_frames = [
            frame for frame in frames
            if blueprint.by_id.get(frame[1]) is not None
            and blueprint.by_id[frame[1]].kind == UnitKind.IMPLEMENTATION.value
        ]
        if implementation_frames:
            return implementation_frames[-1][1]
        return cls._owner_from_failure(blueprint, result)

    @staticmethod
    def _public_failure_summary(result: BlockExecutionResult) -> str:
        """Project actionable public-check facts without forwarding a traceback."""
        output = (str(result.outputs.get("stderr", "")) + "\n" + str(result.outputs.get("stdout", "")))[:12000]
        summaries: list[str] = []
        for raw in output.splitlines():
            line = raw.strip()
            if line.startswith("FAILED ") or re.match(
                r"^E\s+(?:AssertionError|TypeError|ValueError|SystemExit|SyntaxError|ImportError|ModuleNotFoundError|FileNotFoundError|NameError|OSError|PermissionError)\b",
                line,
            ):
                normalized = re.sub(r"^E\s+", "", line)[:500]
                if normalized not in summaries:
                    summaries.append(normalized)
            if len(summaries) >= 12:
                break
        generic = str(result.error.message if result.error else "").strip()
        if summaries:
            return "Public check failure summary:\n" + "\n".join(summaries)
        return generic or "public check failed without a safe summary"

    @classmethod
    def _failure_report(cls, blueprint: ProjectBlueprint, failed_check: str, result: BlockExecutionResult, dag: Any, worker: BlueprintUnitExecutor, owner_hint: str = "") -> FailureReport:
        observed = (str(result.outputs.get("stderr", "")) + "\n" + str(result.outputs.get("stdout", "")))[:4000]
        message = cls._public_failure_summary(result) if failed_check == "pytest" else result.error.message if result.error else observed
        details = dict(result.error.details) if result.error else {}
        stage_by_check = {"compile": FailureStage.COMPILE.value, "pytest": FailureStage.TEST.value, "runtime_smoke": FailureStage.RUNTIME.value, "external_acceptance": FailureStage.ACCEPTANCE.value}
        stage = str(details.get("failure_stage") or stage_by_check.get(failed_check, FailureStage.UNKNOWN.value))
        origin = str(details.get("origin_unit_id") or failed_check)
        local_stages = {
            FailureStage.PROVIDER_TRANSPORT.value, FailureStage.PROVIDER_OUTPUT.value,
            FailureStage.UNIT_OUTPUT_VALIDATION.value, FailureStage.MATERIALIZATION.value,
            FailureStage.SYNTAX_VALIDATION.value, FailureStage.INTERFACE_VALIDATION.value,
        }
        explicit_owner = str(details.get("owner_unit_id") or "")
        if explicit_owner in blueprint.by_id:
            owner = explicit_owner
        elif failed_check in blueprint.by_id and stage in local_stages:
            owner = failed_check
        else:
            owner = owner_hint or (
                cls._pytest_owner_from_failure(blueprint, result)
                if failed_check == "pytest"
                else cls._owner_from_failure(blueprint, result)
            )
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
        if failure_type == "REPAIR_STALLED":
            action = FailureAction.STOP.value
        owned_frames = cls._owned_traceback_frames(blueprint, result)
        selected_frame = next((item for item in reversed(owned_frames) if item[1] == owner), None)
        frame = selected_frame[3] if selected_frame else ""
        owner_file = selected_frame[2] if selected_frame else ""
        affected = downstream_closure(dag, {owner}) if owner else ()
        suggestion = "retry generation for the same unit with failure context" if action == FailureAction.RETRY_GENERATION.value else "patch the owner unit while preserving observed interfaces" if action == FailureAction.REPAIR_EXISTING.value else "stop fail-closed; attribution is unresolved"
        repair_target = details.get("repair_target") if isinstance(details.get("repair_target"), Mapping) else {}
        repair_validation = details.get("repair_validation") if isinstance(details.get("repair_validation"), Mapping) else {}
        repair_fingerprint = (
            repair_target.get("fingerprint") if isinstance(repair_target.get("fingerprint"), Mapping)
            else repair_validation.get("fingerprint") if isinstance(repair_validation.get("fingerprint"), Mapping)
            else {}
        )
        return FailureReport(
            origin, failure_type, failure_stage=stage, owner_unit_id=owner, recovery_action=action,
            materialized_baseline=baseline,
            owner_file=str(repair_fingerprint.get("relevant_source_locator") or owner_file),
            owner_interface=str(repair_fingerprint.get("relevant_interface_id") or ""),
            first_project_frame=frame,
            failed_check=failed_check,
            expected=str(repair_fingerprint.get("normalized_expected") or "check exit code 0"),
            observed=str(repair_fingerprint.get("normalized_actual") or message[:2000]),
            affected_units=affected, suggested_action=suggestion,
            evidence_refs=(f"node_results/{failed_check}.json",),
            failed_requirement_ids=tuple(str(item) for item in repair_fingerprint.get("requirement_ids", ())),
            mapping_complete=bool(repair_fingerprint.get("requirement_ids")),
            repair_target_hash=str(repair_target.get("target_hash") or repair_validation.get("target_hash") or ""),
            repair_failure_fingerprint_hash=str(repair_fingerprint.get("fingerprint_hash") or ""),
            repair_progress=str(details.get("repair_progress") or ""),
        )
