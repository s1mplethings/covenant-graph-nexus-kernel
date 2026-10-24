from __future__ import annotations

import json
from pathlib import Path
import time
from cgkn.application.requirements.obligation import ObligationSet
from cgkn.application.requirements.policy import DependencyPolicy
from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.execution.contracts import utc_now
from cgkn.executors.protocol import ExecutorDescriptor

from .contracts import OraclePlan, OracleStatus
from .contract_test_compiler import ContractTestCompiler
from .contract_test_renderer import ContractTestRenderer
from .contract_test_validator import ContractTestValidator
from .executor import OracleExecutor


class ContractTestCompilerExecutor:
    descriptor = ExecutorDescriptor(
        "project.contract-test-compiler@1", "deterministic_contract_test_compiler",
        ("project.contract-test-plan@1",), ("filesystem.read", "filesystem.write"),
    )

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult:
        started, clock = utc_now(), time.perf_counter()
        try:
            config = request.task_context.node_config
            obligations = ObligationSet.from_dict(config["obligation_set"])
            oracle_plan = OraclePlan.from_dict(config["oracle_plan"])
            policies = tuple(DependencyPolicy.from_dict(item) for item in config.get("dependency_policies", ()))
            if len(policies) != 1:
                raise ValueError("contract test compiler requires exactly one dependency policy")
            plan = ContractTestCompiler().compile(obligations, oracle_plan, policies[0])
            artifact = ContractTestRenderer().render(plan, policies[0])
            validation = ContractTestValidator().validate(
                plan, artifact.manifest, artifact.source, obligations, oracle_plan, policies[0]
            )
            if validation.status != "PASS":
                raise ValueError("contract test validation failed: " + ",".join(validation.errors))
            target = self.workspace / artifact.path
            manifest_path = self.workspace / "tests" / "contract_test_manifest.json"
            manifest_text = json.dumps(artifact.manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            reused = (
                target.is_file() and target.read_text(encoding="utf-8") == artifact.source
                and manifest_path.is_file() and manifest_path.read_text(encoding="utf-8") == manifest_text
            )
            if not reused:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(artifact.source, encoding="utf-8")
                manifest_path.write_text(manifest_text, encoding="utf-8")
            return BlockExecutionResult(
                project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id,
                node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.SUCCEEDED,
                outputs={"status": "PASS", "reused": reused, "plan": plan.as_dict(),
                         "manifest": artifact.manifest.as_dict(), "test_path": artifact.path},
                error=None, started_at=started, ended_at=utc_now(),
                duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage={},
                metadata={"deterministic_contract_tests": True}, retryable=False,
            )
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            return BlockExecutionResult(
                project_id=request.project_id, run_id=request.run_id, attempt_id=request.attempt_id,
                node_id=request.node_id, executor_ref=request.executor_ref, status=BlockStatus.FAILED,
                outputs={"status": "FAIL", "reused": False},
                error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, str(exc)),
                started_at=started, ended_at=utc_now(),
                duration_ms=max(0, int((time.perf_counter() - clock) * 1000)), usage={},
                metadata={"deterministic_contract_tests": True}, retryable=False,
            )


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
