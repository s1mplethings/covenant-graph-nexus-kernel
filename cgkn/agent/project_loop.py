from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from cgkn.execution import BlockStatus
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.runtime import DAGRunner, RunSummary
from cgkn.state import EventRecord, FileRunStore

from .composer import AgentComposer, AgentDecisionContext


@dataclass(frozen=True)
class ProjectLoopResult:
    status: str
    decision_count: int
    agent_calls: int
    worker_calls: int
    tree: CapabilityTree
    run_summary: RunSummary | None
    escalation_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "decision_count": self.decision_count, "agent_calls": self.agent_calls, "worker_calls": self.worker_calls, "tree": self.tree.as_dict(), "run_summary": self.run_summary.as_dict() if self.run_summary else None, "escalation_reason": self.escalation_reason}


class AgentProjectLoop:
    def __init__(self, composer: AgentComposer, runner: DAGRunner, store: FileRunStore, *, known_capabilities: set[str], worker_model: str, capability_catalog: dict[str, Any] | None = None, max_decisions: int = 4):
        if composer.config.model == worker_model:
            raise ValueError("Agent and worker models must be independently configured and different")
        if not 1 <= max_decisions <= 4:
            raise ValueError("max_decisions must be between 1 and 4")
        self.composer, self.runner, self.store = composer, runner, store
        self.known_capabilities, self.max_decisions = frozenset(known_capabilities), max_decisions
        self.capability_catalog = dict(capability_catalog or {})

    def run(self, *, project_id: str, run_id: str, goal: str, constraints: tuple[str, ...] = ()) -> ProjectLoopResult:
        tree = CapabilityTree(goal, ())
        summary: RunSummary | None = None
        failure_details: dict[str, Any] = {}
        worker_calls = 0
        for number in range(1, self.max_decisions + 1):
            decision = self.composer.decide(AgentDecisionContext(project_id, run_id, goal, number, tree, tuple(sorted(self.known_capabilities)), self.capability_catalog, summary.as_dict() if summary else {}, failure_details))
            self.store.save_agent_decision(project_id, run_id, number, decision.as_dict())
            self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION", data={"decision_id": decision.decision_id, "decision_number": number, "summary": decision.summary, "request_run": decision.request_run, "finish": decision.finish, "needs_escalation": decision.needs_escalation, "context_hash": decision.context_hash}))
            if decision.needs_escalation:
                return ProjectLoopResult("BLOCKED", number, number, worker_calls, tree, summary, decision.escalation_reason)
            retry_nodes = [edit.node_id for edit in decision.edits if edit.operation == "retry_node"]
            if len(retry_nodes) > 1:
                raise ValueError("one Agent decision may retry at most one node")
            retry_node = retry_nodes[0] if retry_nodes else None
            tree = apply_tree_edits(tree, decision.edits, known_capabilities=self.known_capabilities)
            if decision.finish:
                status = "SUCCEEDED" if summary and summary.status == "SUCCEEDED" else "FAILED"
                return ProjectLoopResult(status, number, number, worker_calls, tree, summary)
            if decision.request_run:
                dag = compile_tree(tree)
                if not dag.nodes:
                    raise ValueError("Agent requested a run with no executable nodes")
                summary = self.runner.run(project_id=project_id, run_id=run_id, tree=tree, dag=dag, resume=summary is not None, retry_node=retry_node, constraints=constraints)
                worker_calls += sum(1 for node_id in summary.actual_executions if tree.by_id[node_id].config.get("executor_ref") == "llm.cheap@1")
                failure_details = self._failure_details(project_id, run_id, summary)
        return ProjectLoopResult("BLOCKED", self.max_decisions, self.max_decisions, worker_calls, tree, summary, "agent decision limit reached")

    def _failure_details(self, project_id: str, run_id: str, summary: RunSummary) -> dict[str, Any]:
        details: dict[str, Any] = {}
        for node_id in (*summary.failed_nodes, *summary.blocked_nodes):
            result = self.store.load_result(project_id, run_id, node_id)
            details[node_id] = {"status": result.status.value, "error": result.error.as_dict() if result.error else None, "outputs": dict(result.outputs)}
        return details
