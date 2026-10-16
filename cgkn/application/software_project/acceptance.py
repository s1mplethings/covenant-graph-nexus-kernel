from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

from .contracts import AcceptanceResult, FailureClass, ProjectResultStatus


class ExternalAcceptanceExecutor:
    descriptor = ExecutorDescriptor("project.acceptance@1", "external_acceptance", ("project.acceptance.external@1",), ("process.execute", "test.observe"))

    def __init__(self, project_root: pathlib.Path | str, acceptance_root: pathlib.Path | str):
        self.project_root = pathlib.Path(project_root).resolve()
        self.acceptance_root = pathlib.Path(acceptance_root).resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        case_id = str(request.task_context.node_config.get("case_id", ""))
        snapshot_hash = ""
        for value in request.task_context.dependency_results.values():
            if isinstance(value, Mapping) and value.get("snapshot_hash"):
                snapshot_hash = str(value["snapshot_hash"])
        test_path = self.acceptance_root / f"test_{case_id}.py"
        if not test_path.is_file():
            result = AcceptanceResult(ProjectResultStatus.FAIL, FailureClass.HARNESS_FAILURE, "acceptance harness is unavailable", snapshot_hash=snapshot_hash)
            return self._block(request, result, started, clock)
        env = os.environ.copy()
        env.update({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CGKN_GENERATED_PROJECT": str(self.project_root), "PYTHONPATH": str(self.project_root)})
        try:
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(test_path)], cwd=self.project_root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=request.timeout_seconds, env=env)
            status = ProjectResultStatus.PASS if completed.returncode == 0 else ProjectResultStatus.FAIL
            failure = None if status is ProjectResultStatus.PASS else FailureClass.PROJECT_FAILURE
            summary = "all external requirements passed" if status is ProjectResultStatus.PASS else "one or more external requirements failed"
            failed_count = sum(1 for line in completed.stdout.splitlines() if line.startswith("FAILED "))
            failed = tuple(f"public-requirement-{index + 1}" for index in range(failed_count))
            stdout = self._sanitized_output(completed.stdout, status)
            stderr = self._sanitized_output(completed.stderr, status)
            result = AcceptanceResult(status, failure, summary, failed, (completed.returncode,), stdout, stderr, {"real_subprocess": True, "isolated_harness": True}, int((time.perf_counter() - clock) * 1000), snapshot_hash)
        except subprocess.TimeoutExpired:
            result = AcceptanceResult(ProjectResultStatus.FAIL, FailureClass.TIMEOUT, "external acceptance timed out", duration_ms=int((time.perf_counter() - clock) * 1000), snapshot_hash=snapshot_hash)
        return self._block(request, result, started, clock)

    @staticmethod
    def _sanitized_output(value: str, status: ProjectResultStatus) -> str:
        """Keep useful PASS evidence without leaking harness paths or assertions."""
        if not value:
            return ""
        if status is ProjectResultStatus.FAIL:
            return "external acceptance diagnostics withheld"
        lines = [line for line in value.splitlines() if "passed in" in line]
        return (lines[-1] + "\n") if lines else "external acceptance completed\n"

    @staticmethod
    def _block(request: BlockExecutionRequest, result: AcceptanceResult, started: str, clock: float) -> BlockExecutionResult:
        value = result.as_dict()
        status = BlockStatus.SUCCEEDED if result.status is ProjectResultStatus.PASS else BlockStatus.FAILED
        error = None if status is BlockStatus.SUCCEEDED else ExecutionError(ExecutionErrorCode.INVALID_OUTPUT, result.sanitized_summary, {"failure_class": result.failure_class.value if result.failure_class else None, "failed_requirement_ids": list(result.failed_requirement_ids)})
        return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id, node_id=request.node_id, executor_ref=request.executor_ref, status=status, outputs=value, error=error, started_at=started, ended_at=utc_now(), duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), metadata={"hidden_source_exposed": False})


def write_acceptance_receipt(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
