from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorRegistry, ExecutorResolutionError
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import ExecutionDAG
from cgkn.orchestration.invalidation import downstream_closure
from cgkn.state import EventRecord, FileRunStore, NodeExecutionRecord, ProjectState, RunState, StateStoreError


@dataclass(frozen=True)
class RunSummary:
    project_id: str
    run_id: str
    status: str
    node_count: int
    actual_executions: tuple[str, ...]
    reused_nodes: tuple[str, ...]
    failed_nodes: tuple[str, ...]
    blocked_nodes: tuple[str, ...]
    retry_attempts: int

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__ | {key: list(value) for key, value in self.__dict__.items() if isinstance(value, tuple)}


class DAGRunner:
    def __init__(self, registry: ExecutorRegistry, store: FileRunStore):
        self.registry = registry
        self.store = store

    def run(self, *, project_id: str, run_id: str, tree: CapabilityTree, dag: ExecutionDAG, resume: bool = False, retry_node: str | None = None, constraints: tuple[str, ...] = ()) -> RunSummary:
        dag.topological_order()
        if set(dag.by_id) != {node.id for node in tree.nodes if node.executable}:
            raise ValueError("execution DAG does not match executable CapabilityTree nodes")
        try:
            state = self.store.load_run(project_id, run_id) if resume or retry_node else self._new_state(project_id, run_id, dag)
        except StateStoreError:
            if resume or retry_node:
                raise
            state = self._new_state(project_id, run_id, dag)
        if set(state.nodes) != set(dag.by_id):
            raise ValueError("persisted run state does not match DAG")
        self.store.save_project(ProjectState(project_id, tree.goal, run_id, constraints))
        self.store.save_definition(project_id, run_id, "capability_tree.json", tree.as_dict())
        self.store.save_definition(project_id, run_id, "execution_dag.json", dag.as_dict())
        if retry_node:
            self._invalidate(state, dag, retry_node)
        actual: list[str] = []
        reused: list[str] = []
        for node_id in dag.topological_order():
            record = state.nodes[node_id]
            if record.status == BlockStatus.SUCCEEDED.value:
                record.reused = True
                reused.append(node_id)
                self._event(project_id, run_id, "NODE_REUSED", node_id=node_id)
                continue
            node = dag.by_id[node_id]
            dependency_results: dict[str, Any] = {}
            failed_dependencies: list[str] = []
            for dependency in node.depends_on:
                dep_record = state.nodes[dependency]
                if dep_record.status != BlockStatus.SUCCEEDED.value:
                    failed_dependencies.append(dependency)
                else:
                    dependency_results[dependency] = self.store.load_result(project_id, run_id, dependency).outputs
            attempt_id = f"attempt-{len(record.attempts) + 1:04d}"
            if failed_dependencies:
                result = BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=str(node.config.get("executor_ref", "unresolved")), status=BlockStatus.BLOCKED, error=ExecutionError(ExecutionErrorCode.DEPENDENCY_FAILED, "dependency did not succeed", {"dependencies": failed_dependencies}))
            else:
                result = self._execute(project_id, run_id, attempt_id, node_id, node.capability_ref, dict(node.config), dependency_results, constraints)
                actual.append(node_id)
            self.store.save_result(result)
            record.attempts.append(attempt_id)
            record.latest_result_ref = f"node_results/{node_id}.json"
            record.status = result.status.value
            record.reused = False
            state.updated_at = utc_now()
            self.store.save_run(state)
            self._event(project_id, run_id, "NODE_FINISHED", node_id=node_id, attempt_id=attempt_id, data={"status": result.status.value})
        failed = tuple(node_id for node_id, value in state.nodes.items() if value.status in {BlockStatus.FAILED.value, BlockStatus.TIMED_OUT.value})
        blocked = tuple(node_id for node_id, value in state.nodes.items() if value.status == BlockStatus.BLOCKED.value)
        state.status = "SUCCEEDED" if not failed and not blocked and all(value.status == BlockStatus.SUCCEEDED.value for value in state.nodes.values()) else "FAILED"
        state.updated_at = utc_now()
        self.store.save_run(state)
        summary = RunSummary(project_id, run_id, state.status, len(state.nodes), tuple(actual), tuple(reused), failed, blocked, sum(max(0, len(value.attempts) - 1) for value in state.nodes.values()))
        self.store.atomic_json(self.store.run_dir(project_id, run_id) / "run_summary.json", summary.as_dict())
        self._event(project_id, run_id, "RUN_FINISHED", data=summary.as_dict())
        return summary

    def _new_state(self, project_id: str, run_id: str, dag: ExecutionDAG) -> RunState:
        state = RunState(project_id, run_id, nodes={node.id: NodeExecutionRecord(node.id) for node in dag.nodes})
        self.store.save_run(state)
        self._event(project_id, run_id, "RUN_CREATED")
        return state

    def _invalidate(self, state: RunState, dag: ExecutionDAG, node_id: str) -> None:
        for affected in downstream_closure(dag, {node_id}):
            record = state.nodes[affected]
            record.status = "PENDING"
            record.latest_result_ref = None
            record.reused = False
        state.status = "PENDING"
        self.store.save_run(state)
        self._event(state.project_id, state.run_id, "SUBGRAPH_INVALIDATED", node_id=node_id, data={"affected": list(downstream_closure(dag, {node_id}))})

    def _execute(self, project_id: str, run_id: str, attempt_id: str, node_id: str, capability_ref: str, config: dict[str, Any], dependencies: dict[str, Any], constraints: tuple[str, ...]) -> BlockExecutionResult:
        executor_ref = str(config.get("executor_ref", ""))
        request = BlockExecutionRequest(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, component_ref=capability_ref, executor_ref=executor_ref, input_values=dict(config.get("inputs", {})), dependency_result_refs=tuple(dependencies), task_context=TaskContext(node_goal=str(config.get("goal", node_id)), node_config={key: value for key, value in config.items() if key not in {"inputs", "acceptance", "constraints"}}, dependency_results=dependencies, project_constraints=constraints, acceptance=tuple(config.get("acceptance", ()))), timeout_seconds=float(config.get("timeout_seconds", 30.0)), declared_effects=tuple(config.get("effects", ())), metadata={"capability_ref": capability_ref})
        self._event(project_id, run_id, "NODE_STARTED", node_id=node_id, attempt_id=attempt_id, data={"executor_ref": executor_ref})
        try:
            return self.registry.resolve(executor_ref, capability_ref).execute(request)
        except ExecutorResolutionError as exc:
            return BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=executor_ref or "unresolved", status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTOR_NOT_FOUND, str(exc)))
        except Exception as exc:  # executor boundary fails closed
            return BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=executor_ref or "unresolved", status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}"), retryable=True)

    def _event(self, project_id: str, run_id: str, event_type: str, *, node_id: str | None = None, attempt_id: str | None = None, data: dict[str, Any] | None = None) -> None:
        self.store.append_event(EventRecord(f"event.{uuid.uuid4().hex}", project_id, run_id, event_type, node_id, attempt_id, data or {}))
