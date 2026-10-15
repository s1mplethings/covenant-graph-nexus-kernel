from __future__ import annotations

import pathlib
import time
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.providers import CompletionClient, ModelRoleConfig, parse_json_object

from .protocol import ExecutorDescriptor


ALLOWED_ACTIONS = {"read_file", "list_files", "write_file", "patch_file"}
PROTECTED_PARTS = {".git", ".hg", ".svn"}

WORKER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "node_id", "summary", "actions", "expected_outputs", "confidence", "needs_escalation", "escalation_reason"],
    "properties": {
        "schema_version": {"const": "1.0"}, "node_id": {"type": "string"}, "summary": {"type": "string"},
        "actions": {"type": "array", "items": {"oneOf": [
            {"type": "object", "additionalProperties": False, "required": ["action", "path"], "properties": {"action": {"const": "read_file"}, "path": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path"], "properties": {"action": {"const": "list_files"}, "path": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path", "content"], "properties": {"action": {"const": "write_file"}, "path": {"type": "string"}, "content": {"type": "string"}}},
            {"type": "object", "additionalProperties": False, "required": ["action", "path", "find", "replace"], "properties": {"action": {"const": "patch_file"}, "path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}}},
        ]}}, "expected_outputs": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "needs_escalation": {"type": "boolean"}, "escalation_reason": {"type": "string"},
    },
}


class ProposalError(ValueError):
    pass


class BoundedFileActions:
    def __init__(self, root: pathlib.Path | str):
        self.root = pathlib.Path(root).resolve()

    def _path(self, value: object) -> pathlib.Path:
        raw = str(value or ".")
        candidate = (self.root / raw).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PermissionError("path escapes project root")
        relative = candidate.relative_to(self.root)
        if any(part.lower() in PROTECTED_PARTS for part in relative.parts):
            raise PermissionError("protected path rejected")
        return candidate

    def apply(self, action: Mapping[str, Any]) -> dict[str, Any]:
        kind = str(action.get("action", ""))
        allowed_fields = {
            "read_file": {"action", "path"}, "list_files": {"action", "path"},
            "write_file": {"action", "path", "content"}, "patch_file": {"action", "path", "find", "replace"},
        }
        if kind not in ALLOWED_ACTIONS or set(action) != allowed_fields.get(kind):
            raise ProposalError(f"invalid or over-broad worker action: {kind}")
        path = self._path(action["path"])
        if kind == "read_file":
            return {"action": kind, "path": str(path.relative_to(self.root)).replace("\\", "/"), "content": path.read_text(encoding="utf-8")}
        if kind == "list_files":
            return {"action": kind, "files": sorted(str(item.relative_to(self.root)).replace("\\", "/") for item in path.rglob("*") if item.is_file())}
        path.parent.mkdir(parents=True, exist_ok=True)
        if kind == "write_file":
            content = str(action["content"])
        else:
            before = path.read_text(encoding="utf-8")
            find = str(action["find"])
            if not find or before.count(find) != 1:
                raise ProposalError("patch find text must occur exactly once")
            content = before.replace(find, str(action["replace"]), 1)
        path.write_text(content, encoding="utf-8")
        return {"action": kind, "path": str(path.relative_to(self.root)).replace("\\", "/"), "bytes": len(content.encode("utf-8"))}


def validate_worker_proposal(value: Mapping[str, Any], node_id: str) -> dict[str, Any]:
    required = set(WORKER_SCHEMA["required"])
    if set(value) != required or value.get("schema_version") != "1.0" or value.get("node_id") != node_id:
        raise ProposalError("worker proposal has invalid envelope")
    if not isinstance(value.get("actions"), list) or not isinstance(value.get("expected_outputs"), list):
        raise ProposalError("worker proposal arrays are invalid")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ProposalError("worker confidence is invalid")
    for action in value["actions"]:
        if not isinstance(action, dict) or action.get("action") not in ALLOWED_ACTIONS:
            raise ProposalError("worker proposal contains a forbidden action")
    if bool(value["needs_escalation"]) and value["actions"]:
        raise ProposalError("escalation proposal cannot contain actions")
    return dict(value)


class LLMExecutor:
    descriptor = ExecutorDescriptor("llm.cheap@1", "bounded_llm", ("*",), ("filesystem.read", "filesystem.write"))

    def __init__(self, project_root: pathlib.Path | str, client: CompletionClient, config: ModelRoleConfig):
        if config.role != "worker":
            raise ValueError("LLMExecutor requires worker model config")
        self.actions, self.client, self.config = BoundedFileActions(project_root), client, config

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        context = request.task_context.as_dict()
        prompt = {"node_id": request.node_id, "goal": request.task_context.node_goal, "config": context["node_config"], "dependency_results": context["dependency_results"], "constraints": list(request.task_context.project_constraints), "acceptance": list(request.task_context.acceptance), "allowed_actions": sorted(ALLOWED_ACTIONS)}
        import json
        raw_prompt = json.dumps(prompt, ensure_ascii=False, sort_keys=True)
        usage: dict[str, Any] = {}
        try:
            completion = self.client.complete(system="You are a bounded CGKN worker. Propose only read/list/write/patch actions. Never propose shell, network, goals, DAG edits, tests, delivery, or hidden reasoning. Return JSON only.", user=raw_prompt, schema_name="cgkn_worker_proposal", schema=WORKER_SCHEMA, config=self.config)
            usage = dict(completion.usage) | {"model": completion.model, "request_id": completion.request_id, "provider_attempts": completion.attempts, "context_chars": len(raw_prompt), "dependency_count": len(context["dependency_results"])}
            proposal = validate_worker_proposal(parse_json_object(completion.text), request.node_id)
            if proposal["needs_escalation"]:
                return self._result(request, BlockStatus.BLOCKED, started, clock, error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, str(proposal["escalation_reason"]), {"needs_escalation": True}), usage=usage, metadata={"proposal": proposal})
            results = [self.actions.apply(action) for action in proposal["actions"]]
            modified = [item["path"] for item in results if item["action"] in {"write_file", "patch_file"}]
            return self._result(request, BlockStatus.SUCCEEDED, started, clock, outputs={"summary": proposal["summary"], "action_results": results, "modified_files": modified, "expected_outputs": proposal["expected_outputs"]}, usage=usage, metadata={"proposal": proposal})
        except TimeoutError as exc:
            return self._result(request, BlockStatus.TIMED_OUT, started, clock, error=ExecutionError(ExecutionErrorCode.TIMEOUT, str(exc)), usage=usage, retryable=True)
        except (OSError, ValueError, PermissionError, RuntimeError) as exc:
            code = ExecutionErrorCode.POLICY_BLOCKED if isinstance(exc, PermissionError) else ExecutionErrorCode.INVALID_OUTPUT if isinstance(exc, (ValueError, ProposalError)) else ExecutionErrorCode.EXECUTION_ERROR
            return self._result(request, BlockStatus.FAILED, started, clock, error=ExecutionError(code, str(exc)), usage=usage, retryable=isinstance(exc, RuntimeError))

    @staticmethod
    def _result(request: BlockExecutionRequest, status: BlockStatus, started: str, clock: float, *, outputs: Mapping[str, Any] | None = None, error: ExecutionError | None = None, usage: Mapping[str, Any] | None = None, metadata: Mapping[str, Any] | None = None, retryable: bool = False) -> BlockExecutionResult:
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=outputs or {}, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage=usage or {}, metadata=metadata or {}, retryable=retryable)
