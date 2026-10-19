from __future__ import annotations

import os
import pathlib
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Mapping

from cgkn.application.materialization import materialize_json

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.llm import WORKER_SCHEMA, validate_worker_proposal
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object
from cgkn.application.learning import GenerationRequest, ProductionGenerationClient, default_production_client

from .contracts import WorkerScope


class ScopeViolation(ValueError):
    pass


_plain = materialize_json


@dataclass(frozen=True)
class PlannedWrite:
    relative: str
    target: pathlib.Path
    content: bytes
    existed: bool
    previous: bytes | None


class ScopedFileTransaction:
    """Validate a whole worker proposal before applying any filesystem effect."""

    def __init__(self, project_root: pathlib.Path | str, scope: WorkerScope):
        self.root = pathlib.Path(project_root).resolve()
        self.scope = scope
        self.allowed = frozenset(self._normalize(item) for item in scope.visible_paths)
        self.targets = frozenset(self._normalize(item) for item in scope.writable_paths)

    @staticmethod
    def _normalize(value: object) -> str:
        raw = str(value).replace("\\", "/").strip("/")
        if not raw or raw in {".", ".."} or pathlib.PurePosixPath(raw).is_absolute() or ".." in pathlib.PurePosixPath(raw).parts:
            raise ScopeViolation("worker path must be a safe project-relative path")
        return pathlib.PurePosixPath(raw).as_posix()

    def _target(self, relative: str) -> pathlib.Path:
        if relative not in self.allowed:
            raise ScopeViolation(f"path is outside declared worker scope: {relative}")
        parts = pathlib.PurePosixPath(relative).parts
        protected = {item.lower().replace("\\", "/").strip("/") for item in self.scope.protected_paths}
        if any(part.lower() in protected for part in parts) or any(relative.lower() == item or relative.lower().startswith(item + "/") for item in protected):
            raise ScopeViolation("protected path rejected")
        target = (self.root / pathlib.Path(*parts)).resolve()
        if self.root not in target.parents:
            raise ScopeViolation("path escapes project root")
        current = self.root
        for part in parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ScopeViolation("symlink path rejected")
        return target

    def validate(self, actions: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[PlannedWrite]]:
        if len(actions) > self.scope.max_actions:
            raise ScopeViolation("worker action count exceeds scope")
        observations: list[dict[str, Any]] = []
        planned: dict[str, PlannedWrite] = {}
        for action in actions:
            kind = str(action.get("action", ""))
            relative = self._normalize(action.get("path", ""))
            target = self._target(relative)
            if kind == "read_file":
                if set(action) != {"action", "path"} or not target.is_file():
                    raise ScopeViolation("invalid scoped read_file action")
                observations.append({"action": kind, "path": relative, "content": target.read_text(encoding="utf-8")})
                continue
            if kind == "list_files":
                raise ScopeViolation("scoped project workers may not enumerate directories")
            if kind == "write_file":
                if relative not in self.targets:
                    raise ScopeViolation("write_file target is not declared in target_paths")
                if set(action) != {"action", "path", "content"} or (target.exists() and not self.scope.allow_patch) or (not target.exists() and not self.scope.allow_create):
                    raise ScopeViolation("write_file violates create/patch policy")
                content = str(action["content"]).encode("utf-8")
            elif kind == "patch_file":
                if relative not in self.targets:
                    raise ScopeViolation("patch_file target is not declared in target_paths")
                if set(action) != {"action", "path", "find", "replace"} or not self.scope.allow_patch or not target.is_file():
                    raise ScopeViolation("invalid scoped patch_file action")
                before = target.read_text(encoding="utf-8")
                find = str(action["find"])
                if not find or before.count(find) != 1:
                    raise ScopeViolation("patch find text must occur exactly once")
                content = before.replace(find, str(action["replace"]), 1).encode("utf-8")
            else:
                raise ScopeViolation(f"forbidden worker action: {kind}")
            if relative in planned:
                raise ScopeViolation("worker may write each target at most once")
            previous = target.read_bytes() if target.is_file() else None
            if target.suffix == ".py":
                try:
                    compile(content.decode("utf-8"), relative, "exec")
                except (SyntaxError, UnicodeDecodeError) as exc:
                    raise ScopeViolation(f"generated Python failed syntax validation: {exc}") from exc
            planned[relative] = PlannedWrite(relative, target, content, target.exists(), previous)
        if len(planned) > self.scope.max_write_files:
            raise ScopeViolation("worker write-file count exceeds scope")
        if sum(len(item.content) for item in planned.values()) > self.scope.max_total_output_bytes:
            raise ScopeViolation("worker output bytes exceed scope")
        return observations, list(planned.values())

    def apply(self, actions: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        observations, planned = self.validate(actions)
        staged: list[tuple[PlannedWrite, pathlib.Path]] = []
        replaced: list[PlannedWrite] = []
        try:
            for item in planned:
                item.target.parent.mkdir(parents=True, exist_ok=True)
                fd, name = tempfile.mkstemp(prefix=f".{item.target.name}.", suffix=".cgkn-stage", dir=item.target.parent)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(item.content)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged.append((item, pathlib.Path(name)))
            for item, temporary in staged:
                os.replace(temporary, item.target)
                replaced.append(item)
            observations.extend({"action": "write_file", "path": item.relative, "bytes": len(item.content)} for item in planned)
            return observations
        except Exception:
            for item in reversed(replaced):
                try:
                    if item.existed and item.previous is not None:
                        item.target.write_bytes(item.previous)
                    else:
                        item.target.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            for _, temporary in staged:
                temporary.unlink(missing_ok=True)


class ScopedProjectLLMExecutor:
    descriptor = ExecutorDescriptor("llm.cheap@1", "bounded_project_llm", ("project.file.generate@1", "project.file.patch@1", "project.tests.generate@1"), ("filesystem.read", "filesystem.write"), supports_cost_reporting=True)

    def __init__(self, project_root: pathlib.Path | str, client: CompletionClient | ProductionGenerationClient, config: ModelRoleConfig):
        if config.role != "worker":
            raise ValueError("scoped project executor requires worker model config")
        self.root = pathlib.Path(project_root).resolve()
        self.generation = client if isinstance(client, ProductionGenerationClient) else default_production_client(client)
        self.client = self.generation.client
        self.config = config

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        usage: dict[str, Any] = {}
        try:
            scope = WorkerScope.from_mapping(request.task_context.node_config)
            prompt = {
                "node_id": request.node_id,
                "project_root": ".",
                "goal": request.task_context.node_goal,
                "file_purpose": request.task_context.node_config.get("file_purpose", ""),
                "interfaces": _plain(request.task_context.node_config.get("interfaces", {})),
                "target_paths": list(scope.target_paths),
                "allowed_paths": list(scope.allowed_paths),
                "protected_paths": list(scope.protected_paths),
                "constraints": list(request.task_context.project_constraints),
                "acceptance": list(request.task_context.acceptance),
                "relevant_dependency_results": _plain(request.task_context.dependency_results),
                "allowed_actions": ["write_file", "patch_file", "read_file"],
                "limits": {"max_actions": scope.max_actions, "max_write_files": scope.max_write_files, "max_total_output_bytes": scope.max_total_output_bytes, "allow_create": scope.allow_create, "allow_patch": scope.allow_patch, "allow_delete": scope.allow_delete},
            }
            import json
            raw = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
            attempts: list[dict[str, Any]] = []
            proposal: dict[str, Any] = {}
            results: list[dict[str, Any]] = []
            rejection = ""
            for attempt_number in range(1, 4):
                attempt_prompt = raw if not rejection else raw[:-1] + f', "previous_rejection": {json.dumps(rejection)}' + "}"
                retry_directive = ""
                if rejection:
                    retry_directive = " The previous proposal was deterministically rejected. You MUST now use write_file with the complete corrected content for each target; do not retry patch_file."
                effective_prompt = json.loads(attempt_prompt)
                generated = self.generation.generate(GenerationRequest(
                    task_class="project.codegen", operation="REPAIR" if rejection else "GENERATION",
                    project_id=request.project_id, capability_ref=request.component_ref,
                    provider_id=self.config.model,
                    system="You are a bounded software-project file worker. Project constraints and public acceptance override any conflicting node wording. Produce complete production-ready file content only for explicit target_paths. Every referenced Python name must be defined or imported. Use one write_file per new target or one exact patch_file per existing target; if an exact patch cannot be guaranteed unique, replace the complete declared target with write_file when allow_patch is true. Never enumerate directories, run commands, access hidden acceptance, use absolute paths, add network dependencies, alter goals or DAGs, or emit placeholders. Return JSON only." + retry_directive,
                    goal=effective_prompt, contract={"interfaces": prompt["interfaces"], "acceptance": prompt["acceptance"], "target_paths": prompt["target_paths"]},
                    state={"current": effective_prompt.get("current_sources", {})}, failure_evidence={"previous_rejection": rejection} if rejection else {},
                    schema_name="cgkn_scoped_project_worker", schema=WORKER_SCHEMA, model_config=self.config,
                    allowed_actions=("write_file", "patch_file", "read_file"), forbidden_actions=("network", "shell", "dag_change", "hidden_acceptance"),
                    run_id=request.run_id,
                ))
                completion = generated.completion
                attempts.append({"request_id": completion.request_id, "usage": dict(completion.usage), "transport_attempts": completion.attempts})
                usage = self._usage(attempts, len(raw))
                try:
                    proposal = validate_worker_proposal(parse_json_object(completion.text), request.node_id)
                    if proposal["needs_escalation"]:
                        raise ScopeViolation(str(proposal["escalation_reason"]) or "worker requested escalation")
                    results = ScopedFileTransaction(self.root, scope).apply(proposal["actions"])
                    break
                except (ValueError, PermissionError, OSError) as exc:
                    rejection = str(exc)
                    if attempt_number == 3:
                        raise
            modified = [item["path"] for item in results if item["action"] == "write_file"]
            return self._result(request, BlockStatus.SUCCEEDED, started, clock, {"summary": proposal["summary"], "action_results": results, "modified_files": modified}, None, usage, {"proposal": proposal, "proposal_attempts": attempts})
        except TimeoutError as exc:
            return self._result(request, BlockStatus.TIMED_OUT, started, clock, {}, ExecutionError(ExecutionErrorCode.TIMEOUT, str(exc)), usage, {}, True)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            policy = isinstance(exc, (ScopeViolation, PermissionError))
            code = ExecutionErrorCode.POLICY_BLOCKED if policy else ExecutionErrorCode.INVALID_OUTPUT if isinstance(exc, ValueError) else ExecutionErrorCode.EXECUTION_ERROR
            return self._result(request, BlockStatus.FAILED, started, clock, {}, ExecutionError(code, str(exc)), usage, {"scope_failure": policy})

    def _usage(self, attempts: list[dict[str, Any]], context_chars: int) -> dict[str, Any]:
        def total(name: str) -> int | str:
            values = [item["usage"].get(name) for item in attempts]
            if any(not isinstance(value, int) for value in values):
                return "TOKEN_USAGE_UNAVAILABLE"
            return sum(values)

        return {
            "model": self.config.model, "request_id": attempts[-1]["request_id"], "request_ids": [item["request_id"] for item in attempts],
            "provider_attempts": sum(int(item["transport_attempts"]) for item in attempts), "proposal_attempts": len(attempts), "context_chars": context_chars,
            "prompt_tokens": total("prompt_tokens"),
            "completion_tokens": total("completion_tokens"),
            "total_tokens": total("total_tokens"),
        }

    @staticmethod
    def _result(request: BlockExecutionRequest, status: BlockStatus, started: str, clock: float, outputs: Mapping[str, Any], error: ExecutionError | None, usage: Mapping[str, Any], metadata: Mapping[str, Any], retryable: bool = False) -> BlockExecutionResult:
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=outputs, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage, metadata=metadata, retryable=retryable)
