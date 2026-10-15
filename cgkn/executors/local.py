from __future__ import annotations

import pathlib
import os
import subprocess
import sys
import tempfile
import time
from typing import Any

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now

from .protocol import ExecutorDescriptor


def _within(root: pathlib.Path, value: str | pathlib.Path = ".") -> pathlib.Path:
    path = (root / value).resolve() if not pathlib.Path(value).is_absolute() else pathlib.Path(value).resolve()
    if path != root and root not in path.parents:
        raise PermissionError("path escapes project root")
    return path


def _result(request: BlockExecutionRequest, *, status: BlockStatus, started: str, clock: float, outputs: dict[str, Any] | None = None, error: ExecutionError | None = None, observations: tuple[dict[str, Any], ...] = (), retryable: bool = False) -> BlockExecutionResult:
    return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=outputs or {}, test_observations=observations, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), retryable=retryable)


class FileExecutor:
    descriptor = ExecutorDescriptor("local.file@1", "file", ("*",), ("filesystem.read", "filesystem.write"))

    def __init__(self, project_root: pathlib.Path | str):
        self.root = pathlib.Path(project_root).resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        config = request.task_context.node_config
        try:
            action = str(config.get("action", ""))
            path = _within(self.root, str(config.get("path", ".")))
            if action == "write_file":
                path.parent.mkdir(parents=True, exist_ok=True)
                content = str(config.get("content", request.input_values.get("content", "")))
                path.write_text(content, encoding="utf-8")
                outputs = {"path": str(path.relative_to(self.root)), "bytes": len(content.encode("utf-8"))}
            elif action == "read_file":
                outputs = {"path": str(path.relative_to(self.root)), "content": path.read_text(encoding="utf-8")}
            elif action == "list_files":
                outputs = {"files": sorted(str(item.relative_to(self.root)).replace("\\", "/") for item in path.rglob("*") if item.is_file())}
            else:
                raise ValueError(f"unsupported file action: {action}")
            return _result(request, status=BlockStatus.SUCCEEDED, started=started, clock=clock, outputs=outputs)
        except (OSError, ValueError, PermissionError) as exc:
            code = ExecutionErrorCode.POLICY_BLOCKED if isinstance(exc, PermissionError) else ExecutionErrorCode.EXECUTION_ERROR
            return _result(request, status=BlockStatus.FAILED, started=started, clock=clock, error=ExecutionError(code, str(exc)))


class CommandExecutor:
    descriptor = ExecutorDescriptor("local.command@1", "command", ("*",), ("process.execute",))
    _blocked = {"rm", "rmdir", "del", "format", "shutdown", "reboot", "diskpart", "git clean", "git reset --hard"}

    def __init__(self, project_root: pathlib.Path | str):
        self.root = pathlib.Path(project_root).resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        config = request.task_context.node_config
        try:
            expected = config.get("assert_dependency_stdout_contains")
            if expected is not None:
                observed = "".join(str(value.get("stdout", "")) for value in request.task_context.dependency_results.values() if isinstance(value, dict))
                outputs = {"expected": str(expected), "observed_stdout": observed, "matched": str(expected) in observed}
                if not outputs["matched"]:
                    return _result(request, status=BlockStatus.FAILED, started=started, clock=clock, outputs=outputs, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, "expected text absent from dependency stdout"))
                return _result(request, status=BlockStatus.SUCCEEDED, started=started, clock=clock, outputs=outputs, observations=({"check": "stdout_contains", "status": "PASS"},))
            command = config.get("command")
            if not isinstance(command, (list, tuple)) or not command or not all(isinstance(item, str) and item for item in command):
                raise ValueError("command must be a non-empty argv list")
            rendered = " ".join(command).lower()
            if any(token in rendered for token in self._blocked):
                raise PermissionError("dangerous command rejected")
            cwd = _within(self.root, str(config.get("cwd", ".")))
            environment = os.environ.copy()
            environment.update({str(key): str(value) for key, value in dict(config.get("environment", {})).items()})
            completed = subprocess.run(list(command), cwd=cwd, text=True, capture_output=True, timeout=request.timeout_seconds, shell=False, env=environment)
            outputs = {"command": list(command), "cwd": str(cwd.relative_to(self.root) or "."), "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
            if completed.returncode:
                return _result(request, status=BlockStatus.FAILED, started=started, clock=clock, outputs=outputs, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"command exited {completed.returncode}"), retryable=True)
            return _result(request, status=BlockStatus.SUCCEEDED, started=started, clock=clock, outputs=outputs)
        except subprocess.TimeoutExpired as exc:
            return _result(request, status=BlockStatus.TIMED_OUT, started=started, clock=clock, error=ExecutionError(ExecutionErrorCode.TIMEOUT, str(exc)), retryable=True)
        except (OSError, ValueError, PermissionError) as exc:
            code = ExecutionErrorCode.POLICY_BLOCKED if isinstance(exc, PermissionError) else ExecutionErrorCode.CONTRACT_ERROR
            return _result(request, status=BlockStatus.FAILED, started=started, clock=clock, error=ExecutionError(code, str(exc)))


class PythonTestExecutor(CommandExecutor):
    descriptor = ExecutorDescriptor("local.python-test@1", "test", ("*",), ("process.execute", "test.observe"))

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        with tempfile.TemporaryDirectory(prefix="cgkn-pycache-") as pycache:
            config = dict(request.task_context.node_config)
            config["command"] = [sys.executable, "-m", "pytest", *list(config.get("pytest_args", ["-q"]))]
            config["environment"] = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONPYCACHEPREFIX": pycache}
            context = type(request.task_context)(node_goal=request.task_context.node_goal, node_config=config, dependency_results=request.task_context.dependency_results, artifact_refs=request.task_context.artifact_refs, project_constraints=request.task_context.project_constraints, acceptance=request.task_context.acceptance)
            return super().execute(type(request)(**{**request.__dict__, "task_context": context}))


class LocalActionExecutorAdapter:
    descriptor = ExecutorDescriptor("local.action@1", "local_action_adapter", ("*",), ("filesystem.read", "filesystem.write", "process.execute"))

    def __init__(self, project_root: pathlib.Path | str):
        self.file = FileExecutor(project_root)
        self.command = CommandExecutor(project_root)

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        action = str(request.task_context.node_config.get("action", ""))
        if action == "run_command":
            return self.command.execute(request)
        if action in {"write_file", "read_file", "list_files"}:
            return self.file.execute(request)
        now, clock = utc_now(), time.perf_counter()
        return _result(request, status=BlockStatus.FAILED, started=now, clock=clock, error=ExecutionError(ExecutionErrorCode.CONTRACT_ERROR, f"unsupported local action: {action}"))
