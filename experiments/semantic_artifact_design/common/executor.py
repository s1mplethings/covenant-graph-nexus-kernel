from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.software_project.scope import ScopedFileTransaction, ScopeViolation, _plain
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object

from .designs import get_design
from .interface import PythonInterfaceExtractor, compare_interfaces


@dataclass(frozen=True)
class CohesiveWorkerScope:
    allowed_paths: tuple[str, ...]
    target_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    max_actions: int
    max_write_files: int
    max_total_output_bytes: int
    allow_create: bool
    allow_patch: bool
    allow_delete: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CohesiveWorkerScope":
        allowed = tuple(str(item) for item in value.get("allowed_paths", ()))
        targets = tuple(str(item) for item in value.get("target_paths", ()))
        if not allowed or not targets or len(targets) > 5 or any(item not in allowed for item in targets):
            raise ValueError("cohesive worker requires one to five target paths within allowed_paths")
        if bool(value.get("allow_delete", False)):
            raise ValueError("cohesive workers may not delete files")
        for raw in (*allowed, *targets):
            path = pathlib.PurePosixPath(raw.replace("\\", "/"))
            if path.is_absolute() or not str(path) or ".." in path.parts:
                raise ValueError("cohesive worker paths must be safe and relative")
        return cls(allowed, targets, tuple(str(item) for item in value.get("protected_paths", ())), int(value.get("max_actions", 7)),
                   int(value.get("max_write_files", 5)), int(value.get("max_total_output_bytes", 64000)), bool(value.get("allow_create", True)), bool(value.get("allow_patch", True)), False)


class SemanticWorkUnitExecutor:
    descriptor = ExecutorDescriptor("experiment.semantic-worker@1", "semantic_work_unit", ("semantic.work-unit@1",), ("filesystem.read", "filesystem.write"), supports_cost_reporting=True)

    def __init__(self, root: pathlib.Path, client: CompletionClient, config: ModelRoleConfig):
        self.root, self.client, self.config = root.resolve(), client, config
        self.extractor = PythonInterfaceExtractor()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        attempts: list[dict[str, Any]] = []
        try:
            config = request.task_context.node_config
            design = get_design(str(config["design_id"]))
            scope = CohesiveWorkerScope.from_mapping(config)
            current_sources = {}
            for relative in scope.allowed_paths:
                path = self.root / pathlib.PurePosixPath(relative)
                if path.is_file() and path.suffix in {".py", ".md"}:
                    current_sources[relative] = path.read_text(encoding="utf-8")
            dependency_artifacts = []
            for output in request.task_context.dependency_results.values():
                if isinstance(output, Mapping):
                    dependency_artifacts.extend(output.get("semantic_artifacts", []))
            prompt = {"design": design.design_id, "node_id": request.node_id, "project_root": ".",
                      "work_unit_contract": _plain(config["work_unit_contract"]), "project_contract": _plain(config["project_contract"]),
                      "current_sources": current_sources, "current_interface_manifest": _plain(config.get("current_interface_manifest", {})),
                      "direct_dependency_artifacts": [_plain(item) for item in dependency_artifacts], "failure_evidence": _plain(config.get("failure_evidence")),
                      "public_acceptance_subset": list(request.task_context.acceptance), "target_paths": list(scope.target_paths),
                      "allowed_paths": list(scope.allowed_paths), "allowed_actions": ["write_file", "patch_file", "read_file"],
                      "limits": {"max_actions": scope.max_actions, "max_write_files": scope.max_write_files, "max_total_output_bytes": scope.max_total_output_bytes,
                                 "allow_create": scope.allow_create, "allow_patch": scope.allow_patch, "allow_delete": scope.allow_delete}}
            raw = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
            rejection = ""
            proposal: dict[str, Any] = {}
            for number in range(1, 4):
                user = raw if not rejection else json.dumps(prompt | {"previous_rejection": rejection}, ensure_ascii=False, sort_keys=True)
                completion = self.client.complete(
                    system=("You are a bounded cohesive-interface-unit worker. The supplied semantic artifacts, current source text, and deterministic interface manifest are authoritative. "
                            "Write or patch only target_paths, preserve existing public interfaces during repair, implement every referenced name, and return JSON actions only. "
                            "Never infer hidden tests, enumerate directories, execute commands, use network dependencies, emit placeholders, or change the project contract."),
                    user=user, schema_name="cgkn_semantic_worker", schema=WORKER_SCHEMA, config=self.config)
                attempts.append({"request_id": completion.request_id, "usage": dict(completion.usage), "transport_attempts": completion.attempts})
                try:
                    proposal = validate_worker_proposal(parse_json_object(completion.text), request.node_id)
                    if proposal["needs_escalation"]: raise ScopeViolation(proposal["escalation_reason"] or "worker escalation")
                    self._validate_and_apply(scope, proposal["actions"])
                    break
                except (ValueError, OSError, PermissionError) as exc:
                    rejection = str(exc)
                    if number == 3: raise
            manifest = self.extractor.extract_path(self.root)
            artifact = design.create("interface.manifest@1", request.project_id, manifest, producer_ref=request.node_id, revision=len(attempts))
            usage = self._usage(attempts, len(raw))
            modified = [str(item.get("path")) for item in proposal["actions"] if item.get("action") in {"write_file", "patch_file"}]
            return self._result(request, BlockStatus.SUCCEEDED, started, clock, {"summary": proposal["summary"], "modified_files": modified,
                                "interface_manifest": manifest, "semantic_artifacts": [design.as_dict(artifact)]}, None, usage,
                                {"proposal_attempts": attempts, "semantic_context": {"context_chars": len(raw), "included_artifacts": 2 + len(dependency_artifacts),
                                 "included_files": len(current_sources), "included_interfaces": len(manifest["modules"])}})
        except TimeoutError as exc:
            return self._result(request, BlockStatus.TIMED_OUT, started, clock, {}, ExecutionError(ExecutionErrorCode.TIMEOUT, str(exc)), self._usage(attempts, 0), {}, True)
        except (ValueError, OSError, PermissionError, RuntimeError) as exc:
            policy = isinstance(exc, (ScopeViolation, PermissionError))
            code = ExecutionErrorCode.POLICY_BLOCKED if policy else ExecutionErrorCode.INVALID_OUTPUT
            return self._result(request, BlockStatus.FAILED, started, clock, {}, ExecutionError(code, str(exc)), self._usage(attempts, 0), {"scope_failure": policy})

    def _validate_and_apply(self, scope: CohesiveWorkerScope, actions: list[Mapping[str, Any]]) -> None:
        transaction = ScopedFileTransaction(self.root, scope)
        transaction.validate(actions)
        old = self.extractor.extract_path(self.root)
        with tempfile.TemporaryDirectory(prefix="cgkn-semantic-stage-") as temporary:
            staged = pathlib.Path(temporary) / "project"
            shutil.copytree(self.root, staged)
            ScopedFileTransaction(staged, scope).apply(actions)
            new = self.extractor.extract_path(staged)
            compatibility = compare_interfaces(old, new, allow_breaking_change=False)
            if not compatibility.compatible:
                raise ScopeViolation("breaking interface change rejected: " + "; ".join(compatibility.breaking_changes))
        transaction.apply(actions)

    @staticmethod
    def _usage(attempts: list[dict[str, Any]], context_chars: int) -> dict[str, Any]:
        return {"request_ids": [item["request_id"] for item in attempts], "provider_attempts": sum(int(item["transport_attempts"]) for item in attempts),
                "proposal_attempts": len(attempts), "context_chars": context_chars,
                "prompt_tokens": sum(int(item["usage"].get("prompt_tokens", 0)) for item in attempts),
                "completion_tokens": sum(int(item["usage"].get("completion_tokens", 0)) for item in attempts),
                "total_tokens": sum(int(item["usage"].get("total_tokens", 0)) for item in attempts)}

    @staticmethod
    def _result(request: BlockExecutionRequest, status: BlockStatus, started: str, clock: float, outputs: Mapping[str, Any], error: ExecutionError | None, usage: Mapping[str, Any], metadata: Mapping[str, Any], retryable: bool = False) -> BlockExecutionResult:
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id,
                                    executor_ref=request.executor_ref, status=status, outputs=outputs, error=error, started_at=started, ended_at=utc_now(),
                                    duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage, metadata=metadata, retryable=retryable)
