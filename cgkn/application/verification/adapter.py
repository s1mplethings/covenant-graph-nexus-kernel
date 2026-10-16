from __future__ import annotations

from pathlib import Path
import time
from typing import Mapping

from cgkn.application.requirements.policy import DependencyPolicy
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

from .contracts import OraclePlan, OracleStatus
from .executor import OracleExecutor


class ObligationOracleExecutorAdapter:
    descriptor = ExecutorDescriptor(
        "project.obligation-oracle@1",
        "deterministic_obligation_oracle",
        ("project.obligation-oracle-plan@1",),
        ("filesystem.read", "process.execute"),
    )

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        try:
            config = request.task_context.node_config
            plan = OraclePlan.from_dict(config["oracle_plan"])
            policies = tuple(DependencyPolicy.from_dict(item) for item in config.get("dependency_policies", ()))
            evidence = OracleExecutor(policies).execute_plan(plan, self.workspace)
            passed = all(item.status is OracleStatus.PASS for item in evidence)
            error = None if passed else ExecutionError(
                ExecutionErrorCode.EXECUTION_ERROR,
                "required obligation Oracle did not pass",
            )
            return BlockExecutionResult(
                project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id,
                node_id=request.node_id, executor_ref=request.executor_ref,
                status=BlockStatus.SUCCEEDED if passed else BlockStatus.FAILED,
                outputs={"status": "PASS" if passed else "FAIL", "evidence": [item.as_dict() for item in evidence]},
                error=error, started_at=started, ended_at=utc_now(),
                duration_ms=max(0, int((time.perf_counter() - clock) * 1000)),
                usage={}, metadata={"deterministic_oracle": True}, retryable=False,
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            return BlockExecutionResult(
                project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id,
                node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.FAILED,
                outputs={"status": "HARNESS_FAILURE", "evidence": []},
                error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, str(exc)),
                started_at=started, ended_at=utc_now(),
                duration_ms=max(0, int((time.perf_counter() - clock) * 1000)),
                usage={}, metadata={"deterministic_oracle": True}, retryable=False,
            )
