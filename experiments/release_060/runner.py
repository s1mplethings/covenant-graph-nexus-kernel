"""Resumable, family-isolated ITER-060 project-generation runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import pathlib
import shutil
import tempfile
import time
from typing import Any, Mapping

from cgkn.application.project_blueprint import BlueprintCheck, BlueprintUnit, FileBundle, ProjectBlueprint, UnitKind
from cgkn.application.project_corpus import ProjectCorpusCaptureHook
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.orchestration import CapabilityNode, CapabilityTree, compile_tree
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore

from .contracts import ArchitectureBaseline, EvaluationPolicy, ProjectFamilySpec, canonical_hash
from .evaluator import EvaluationResult, evaluate_family
from .leakage import model_packet


SYSTEM_PROMPT = """You are the bounded implementation executor for one generated-original Python project.
Return exactly one JSON FileBundle v2 matching the supplied schema. Do not use Markdown.
Implement the current public episode and preserve all earlier public behavior. Use only the Python standard library.
Do not use network, shell execution, subprocesses, external services, secrets, or hidden tests.
Keep code compact and deterministic. You may return any non-empty subset of allowed paths, but include every file needed for this episode to pass.
The CLI contract is python -m PACKAGE OP INPUT OUTPUT; stateful operations additionally accept --state FILE.
Invalid JSON or invalid input must write a concise error to stderr, exit 2, and not overwrite the output file.
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_json(path: pathlib.Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _usage_totals(records: list[CallRecord]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for record in records:
        for key, value in record.usage.items():
            if isinstance(value, int):
                totals[key] = totals.get(key, 0) + value
    return totals


def _token_cost_usd(usage: Mapping[str, int]) -> float | None:
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    return round((int(input_tokens) * 0.30 + int(output_tokens) * 1.20) / 1_000_000, 8)


def file_bundle_schema(unit_id: str, allowed_paths: tuple[str, ...]) -> dict[str, Any]:
    if not allowed_paths:
        raise ValueError("allowed_paths cannot be empty")
    return {
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "kind", "unit_id", "files"],
        "properties": {
            "schema_version": {"const": "2.0"}, "kind": {"const": "file_bundle"},
            "unit_id": {"const": unit_id},
            "files": {
                "type": "array", "minItems": 1, "maxItems": len(allowed_paths),
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["path", "content"],
                    "properties": {"path": {"enum": list(allowed_paths)}, "content": {"type": "string", "maxLength": 60_000}},
                },
            },
        },
    }


def _workspace_text(workspace: pathlib.Path, allowed_paths: tuple[str, ...], *, limit: int = 45_000) -> dict[str, str]:
    result: dict[str, str] = {}
    used = 0
    for relative in allowed_paths:
        path = workspace / relative
        if not path.is_file() or path.is_symlink():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if used + len(content) > limit:
            remaining = max(0, limit - used)
            result[relative] = content[:remaining] + "\n# [context truncated]"
            break
        result[relative] = content; used += len(content)
    return result


def _atomic_candidate(workspace: pathlib.Path, bundle: FileBundle) -> None:
    parent = workspace.parent
    stage = pathlib.Path(tempfile.mkdtemp(prefix=f".{workspace.name}-stage-", dir=parent))
    backup = parent / f".{workspace.name}-backup"
    try:
        if workspace.exists():
            shutil.copytree(workspace, stage, dirs_exist_ok=True)
        for relative, content in bundle.files:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        if backup.exists():
            shutil.rmtree(backup)
        if workspace.exists():
            os.replace(workspace, backup)
        os.replace(stage, workspace)
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if not workspace.exists() and backup.exists():
            os.replace(backup, workspace)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


@dataclass
class CallRecord:
    logical_call_id: str
    episode_id: str
    purpose: str
    request_chars: int
    response_chars: int
    request_id: str
    actual_model: str
    transport_attempts: int
    usage: Mapping[str, Any]
    selection_receipt_hash: str
    status: str
    elapsed_ms: int
    error_type: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class RunMemory:
    family: ProjectFamilySpec
    baseline: str
    workspace: pathlib.Path
    run_root: pathlib.Path
    run_id: str
    policy: EvaluationPolicy
    hook: ProjectCorpusCaptureHook
    call_records: list[CallRecord] = field(default_factory=list)
    public_results: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    flat_state: list[str] = field(default_factory=list)
    minimal_evidence: list[dict[str, Any]] = field(default_factory=list)
    architecture_contract: dict[str, Any] = field(default_factory=dict)
    last_failures: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def call_count(self) -> int:
        return len(self.call_records)


class FamilyMaterializer:
    def __init__(self, client: CompletionClient, config: ModelRoleConfig, memory: RunMemory):
        self.client = client; self.config = config; self.memory = memory
        self._store = FileRunStore(memory.run_root / "state")

    def _architecture_context(self, episode_index: int, failure: Mapping[str, Any] | None, dependency_results: Mapping[str, Any]) -> Mapping[str, Any]:
        baseline = ArchitectureBaseline(self.memory.baseline)
        if baseline is ArchitectureBaseline.DIRECT_CHEAP:
            return {"mode": "DIRECT", "state": "workspace_only"}
        if baseline is ArchitectureBaseline.DIRECT_CHEAP_FLAT_STATE:
            return {"mode": "FLAT_STATE", "summary": " | ".join(self.memory.flat_state[-8:]), "last_public_failure": dict(failure or {})}
        structured = {
            "mode": "MINIMAL_CGNK" if baseline is ArchitectureBaseline.MINIMAL_CGNK else "FULL_CGNK",
            "contract_ref": self.memory.family.public_hash,
            "current_episode": self.memory.family.episodes[episode_index].episode_id,
            "materialized_paths": sorted(path.relative_to(self.memory.workspace).as_posix() for path in self.memory.workspace.rglob("*") if path.is_file()),
            "evidence": self.memory.minimal_evidence[-6:],
            "localized_evidence": [item for item in self.memory.minimal_evidence if item.get("episode_id") in set(self.memory.family.episodes[episode_index].state_dependencies)][-4:],
            "version_state": {"current": self.memory.family.episodes[episode_index].version, "supersedes": list(self.memory.family.episodes[episode_index].supersedes)},
            "contradiction_status": "NONE_OBSERVED",
            "raw_evidence_fallback": canonical_hash(self.memory.public_results[-1]) if self.memory.public_results else None,
            "recovery": {"failure": dict(failure or {}), "smallest_affected_episode": self.memory.family.episodes[episode_index].episode_id if failure else None},
        }
        if baseline is ArchitectureBaseline.FULL_CGNK:
            structured["dependency_results"] = dict(dependency_results)
            structured["execution_authority"] = "CapabilityTree->ExecutionDAG->DAGRunner"
            structured["project_blueprint"] = dict(self.memory.architecture_contract)
        else:
            target = self._store.run_dir(self.memory.family.family_id, self.memory.run_id) / "minimal_state.json"
            self._store.atomic_json(target, structured)
        return structured

    def execute_episode(self, episode_index: int, *, dependency_results: Mapping[str, Any] | None = None, single_attempt: bool = False) -> tuple[bool, EvaluationResult]:
        episode = self.memory.family.episodes[episode_index]
        failure: Mapping[str, Any] | None = self.memory.last_failures.get(episode.episode_id)
        result = EvaluationResult("FAIL", "PUBLIC", 0, 0, 0, "NOT_RUN")
        prior_episode_calls = sum(record.episode_id == episode.episode_id for record in self.memory.call_records)
        attempts = 1 if single_attempt else self.memory.policy.max_repairs_per_episode + 1
        for attempt in range(attempts):
            if self.memory.call_count >= self.memory.policy.max_provider_calls_per_family:
                failure = {"failure_class": "FAMILY_CALL_BUDGET_EXHAUSTED"}; break
            purpose = "GENERATION" if prior_episode_calls + attempt == 0 else "PUBLIC_REPAIR"
            architecture = self._architecture_context(episode_index, failure, dependency_results or {})
            public_packet = model_packet(self.memory.family, episode_index)
            packet = {
                "task": public_packet,
                "architecture_context": architecture,
                "existing_files": _workspace_text(self.memory.workspace, episode.required_paths),
                "failure_to_repair": dict(failure or {}),
                "allowed_paths": list(episode.required_paths),
                "output_contract": "FileBundle v2; unit_id must equal current episode_id",
            }
            schema = file_bundle_schema(episode.episode_id, episode.required_paths)
            user = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            call_id = f"{self.memory.run_id}-call-{self.memory.call_count + 1:03d}"
            started = time.perf_counter()
            try:
                bound = self.client.bind_run(call_id, episode.episode_id, budget_purpose="BENCHMARK") if hasattr(self.client, "bind_run") else self.client
                completion = bound.complete(system=SYSTEM_PROMPT, user=user, schema_name="cgnk_iter060_file_bundle", schema=schema, config=self.config)
                parsed = parse_json_object(completion.text)
                bundle = FileBundle.from_dict(parsed)
                returned = {path for path, _ in bundle.files}
                if bundle.unit_id != episode.episode_id or not returned.issubset(set(episode.required_paths)):
                    raise ValueError("FileBundle identity or scope mismatch")
                _atomic_candidate(self.memory.workspace, bundle)
                record = CallRecord(call_id, episode.episode_id, purpose, len(SYSTEM_PROMPT) + len(user), len(completion.text), completion.request_id, completion.model, completion.attempts, dict(completion.usage), canonical_hash(dict(completion.selection_receipt)) if completion.selection_receipt else "", "COMPLETED", int((time.perf_counter() - started) * 1000))
                self.memory.call_records.append(record)
                self.memory.hook.record_event({"event": "PROVIDER_CALL", **record.as_dict()})
                self.memory.hook.observe("INITIAL_GENERATION" if attempt == 0 else "POST_REPAIR", metadata={"episode_id": episode.episode_id, "call_id": call_id, "returned_paths": sorted(returned)})
            except Exception as exc:
                record = CallRecord(call_id, episode.episode_id, purpose, len(SYSTEM_PROMPT) + len(user), 0, "", "", 0, {}, "", "FAILED", int((time.perf_counter() - started) * 1000), type(exc).__name__)
                self.memory.call_records.append(record)
                failure = {"failure_class": "PROVIDER_OR_BUNDLE_FAILURE", "error_type": type(exc).__name__}
                self.memory.last_failures[episode.episode_id] = dict(failure)
                self.memory.failures.append(dict(failure)); self.memory.hook.record_failure(failure)
                if attempt < self.memory.policy.max_repairs_per_episode:
                    self.memory.hook.observe("PRE_REPAIR", metadata={"episode_id": episode.episode_id, "failure_class": failure["failure_class"]})
                continue
            self.memory.hook.observe("PRE_TEST", metadata={"episode_id": episode.episode_id})
            result = evaluate_family(self.memory.workspace, self.memory.family, private=False, through_episode=episode_index + 1)
            self.memory.public_results.append(result.as_dict()); self.memory.hook.record_test(result.as_dict())
            evidence = {"episode_id": episode.episode_id, "status": result.status, "failure_class": result.failure_class, "passed_checks": result.passed_checks, "total_checks": result.total_checks}
            self.memory.minimal_evidence.append(evidence)
            self.memory.flat_state.append(f"{episode.episode_id}:{result.status}:{result.failure_class or 'none'}")
            if result.status == "PASS":
                self.memory.last_failures.pop(episode.episode_id, None)
                return True, result
            failure = dict(result.public_failure or {"failure_class": result.failure_class})
            self.memory.last_failures[episode.episode_id] = dict(failure)
            self.memory.failures.append(failure); self.memory.hook.record_failure(failure)
            self.memory.hook.observe("FAILED_TEST", metadata={"episode_id": episode.episode_id, "failure_class": result.failure_class})
            if attempt < self.memory.policy.max_repairs_per_episode:
                self.memory.hook.record_repair({"episode_id": episode.episode_id, "status": "REQUESTED", "public_failure_hash": canonical_hash(failure)})
                self.memory.hook.observe("PRE_REPAIR", metadata={"episode_id": episode.episode_id})
        return False, result


class _DAGMaterializationExecutor:
    descriptor = ExecutorDescriptor("iter060.materializer@1", "provider", ("project.episode.materialize@1",), effects=("write_project_files",), supports_cost_reporting=True)

    def __init__(self, materializer: FamilyMaterializer):
        self.materializer = materializer

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started = time.perf_counter()
        index = int(request.input_values["episode_index"])
        ok, result = self.materializer.execute_episode(index, dependency_results=request.task_context.dependency_results, single_attempt=True)
        if ok:
            return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.SUCCEEDED, outputs={"episode_id": self.materializer.memory.family.episodes[index].episode_id, "public_status": result.status}, duration_ms=int((time.perf_counter() - started) * 1000))
        return BlockExecutionResult(request.project_id, request.run_id, request.attempt_id, request.node_id, request.executor_ref, BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, result.failure_class or "episode materialization failed"), duration_ms=int((time.perf_counter() - started) * 1000))


def _run_full_cgnk(materializer: FamilyMaterializer) -> dict[str, Any]:
    family = materializer.memory.family
    final_paths = list(family.expected_artifacts)
    source_paths = [path for path in final_paths if path.endswith(".py")]
    support_paths = [path for path in final_paths if not path.endswith(".py")]
    chunks = [source_paths[index:index + 5] for index in range(0, len(source_paths), 5)]
    if support_paths:
        chunks.append(support_paths)
    units = []
    for index, paths in enumerate(chunks, start=1):
        unit_id = f"project-unit-{index:02d}"
        units.append(BlueprintUnit(
            unit_id=unit_id, purpose=f"Own the cohesive project artifact group {index}",
            kind=UnitKind.IMPLEMENTATION.value if all(path.endswith(".py") for path in paths) else UnitKind.DOCUMENTATION.value,
            owns=tuple(paths), depends_on=(f"project-unit-{index-1:02d}",) if index > 1 else (),
            executor_ref="llm.cheap@1", instruction=family.public_goal,
            required_interfaces=family.public_interfaces,
            acceptance=tuple(item for episode in family.episodes for item in episode.public_acceptance),
            allowed_effects=("write_project_files",), max_actions=5, max_files=max(1, len(paths)),
            max_output_bytes=60_000, timeout_seconds=600,
        ))
    blueprint = ProjectBlueprint(
        "1.0", family.family_id, 1, family.public_goal, family.constraints, tuple(units),
        (BlueprintCheck("project-public-acceptance", UnitKind.ACCEPTANCE.value, depends_on=tuple(unit.unit_id for unit in units), acceptance=tuple(item for episode in family.episodes for item in episode.public_acceptance)),),
    ).freeze()
    materializer.memory.architecture_contract = {"blueprint_hash": blueprint.blueprint_hash, "unit_count": len(blueprint.units), "status": blueprint.status}
    nodes = tuple(
        CapabilityNode(
            episode.episode_id, capability_ref="project.episode.materialize@1",
            depends_on=(family.episodes[index - 1].episode_id,) if index else (),
            config={"executor_ref": "iter060.materializer@1", "inputs": {"episode_index": index}, "goal": episode.public_instruction, "acceptance": episode.public_acceptance, "effects": ["write_project_files"], "timeout_seconds": 600},
        )
        for index, episode in enumerate(family.episodes)
    )
    tree = CapabilityTree(family.public_goal, nodes); dag = compile_tree(tree)
    registry = ExecutorRegistry(); registry.register(_DAGMaterializationExecutor(materializer))
    store = FileRunStore(materializer.memory.run_root / "dag-state")
    store.atomic_json(store.run_dir(family.family_id, materializer.memory.run_id) / "agent" / "project_blueprint.json", blueprint.as_dict())
    runner = DAGRunner(registry, store)
    summary = runner.run(project_id=family.family_id, run_id=materializer.memory.run_id, tree=tree, dag=dag, constraints=family.constraints)
    repair_counts: dict[str, int] = {}
    while summary.status != "SUCCEEDED" and summary.failed_nodes:
        failed_node = summary.failed_nodes[0]
        repairs = repair_counts.get(failed_node, 0)
        if repairs >= materializer.memory.policy.max_repairs_per_episode:
            break
        repair_counts[failed_node] = repairs + 1
        summary = runner.run(project_id=family.family_id, run_id=materializer.memory.run_id, tree=tree, dag=dag, retry_node=failed_node, constraints=family.constraints)
    return {"blueprint_hash": blueprint.blueprint_hash, "blueprint_unit_count": len(blueprint.units), "tree_hash": canonical_hash(tree.as_dict()), "dag_hash": canonical_hash(dag.as_dict()), "repair_orchestration": {"retry_counts": repair_counts, "dag_runs": 1 + sum(repair_counts.values())}, "summary": summary.as_dict()}


def run_family(
    family: ProjectFamilySpec,
    baseline: str,
    *,
    destination: pathlib.Path,
    corpus_root: pathlib.Path,
    client: CompletionClient,
    config: ModelRoleConfig,
    policy: EvaluationPolicy,
    source_version: str,
) -> dict[str, Any]:
    ArchitectureBaseline(baseline)
    destination = destination.resolve(); destination.mkdir(parents=True, exist_ok=True)
    run_id = f"iter060-{family.family_id.casefold()}-{baseline[:2].casefold()}"
    receipt_path = destination / "receipts" / f"{run_id}.json"
    if receipt_path.is_file():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing.get("finalized") is True and existing.get("source_version") == source_version:
            return existing | {"resume_action": "REUSED_FINAL_RECEIPT"}
    workspace = destination / "workspaces" / run_id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    previous_corpus = os.environ.get("CGNK_PROJECT_CORPUS_ROOT"); os.environ["CGNK_PROJECT_CORPUS_ROOT"] = str(corpus_root)
    hook = ProjectCorpusCaptureHook(
        workspace=workspace, project_id=family.family_id, run_id=run_id,
        source_version=source_version, generator_version="iter060-project-frontier-v1",
        public_packet=family.public_dict() | {"task_hash": family.public_hash},
        private_evaluator_packet=family.private_evaluator_packet(), split=family.split,
        metadata={"project_type": family.project_type, "baseline": baseline, "provider": policy.provider, "model": policy.model, "manual_intervention_count": 0, "complexity_metrics": family.raw_complexity, "corpus_read_enabled": False},
    )
    memory = RunMemory(family, baseline, workspace, destination / "run-state", run_id, policy, hook)
    materializer = FamilyMaterializer(client, config, memory)
    started = time.perf_counter(); architecture_receipt: dict[str, Any] = {}
    hook.observe("INPUT", metadata={"baseline": baseline, "public_hash": family.public_hash})
    status = "FAIL"; private = EvaluationResult("FAIL", "PRIVATE", 0, 0, 0, "NOT_RUN")
    try:
        if baseline == ArchitectureBaseline.FULL_CGNK.value:
            architecture_receipt = _run_full_cgnk(materializer)
            generation_ok = architecture_receipt["summary"]["status"] == "SUCCEEDED"
        else:
            generation_ok = True
            for index in range(len(family.episodes)):
                ok, _ = materializer.execute_episode(index)
                if not ok:
                    generation_ok = False; break
        if generation_ok:
            private = evaluate_family(workspace, family, private=True)
            hook.record_test({"status": private.status, "phase": "PRIVATE", "private_failure_hash": private.private_failure_hash, "failure_class": private.failure_class})
            status = "PASS" if private.status == "PASS" else "FAIL"
        hook.observe("FINAL" if status == "PASS" else "ABORTED", metadata={"status": status, "private_status": private.status})
        provisional_usage = _usage_totals(memory.call_records)
        hook.metadata.update({
            "logical_provider_calls": len(memory.call_records), "transport_attempts": sum(item.transport_attempts for item in memory.call_records),
            "usage_totals": provisional_usage, "estimated_cost_usd": _token_cost_usd(provisional_usage),
            "latency_ms": sum(item.elapsed_ms for item in memory.call_records),
            "route": "api-lab.raw-defer->CGKN.StructuredAnswerSelector", "repair_rounds": sum(item.purpose == "PUBLIC_REPAIR" for item in memory.call_records),
            "architecture_receipt": architecture_receipt,
        })
        capture = hook.finalize(status)
    except BaseException as exc:
        hook.record_failure({"failure_class": "RUNNER_EXCEPTION", "error_type": type(exc).__name__})
        hook.observe("ABORTED", metadata={"error_type": type(exc).__name__})
        capture = hook.finalize("ABORTED")
        status = "ABORTED"
        architecture_receipt["runner_error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
    finally:
        if previous_corpus is None: os.environ.pop("CGNK_PROJECT_CORPUS_ROOT", None)
        else: os.environ["CGNK_PROJECT_CORPUS_ROOT"] = previous_corpus
    usage_totals = _usage_totals(memory.call_records)
    receipt = {
        "kind": "CGNKITER060FamilyRunReceipt", "schema_version": "1.0", "run_id": run_id,
        "family_id": family.family_id, "baseline": baseline, "split": family.split,
        "source_version": source_version, "policy_hash": policy.policy_hash, "public_hash": family.public_hash,
        "private_evaluator_hash": family.private_hash, "provider_calls": len(memory.call_records),
        "call_records": [item.as_dict() for item in memory.call_records], "usage_totals": usage_totals, "estimated_cost_usd": _token_cost_usd(usage_totals),
        "public_results": memory.public_results, "private_result": private.as_dict(),
        "architecture_receipt": architecture_receipt, "corpus_capture": capture.as_dict(),
        "status": status, "manual_intervention_count": 0, "corpus_read_enabled": False,
        "duration_ms": int((time.perf_counter() - started) * 1000), "finished_at": _now(), "finalized": True,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    _write_json(receipt_path, receipt)
    return receipt
