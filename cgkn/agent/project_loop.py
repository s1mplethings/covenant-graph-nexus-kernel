from __future__ import annotations

from cgkn.telemetry.lean import observed

import uuid
import json
import itertools
from dataclasses import dataclass
from typing import Any

from cgkn.execution import BlockStatus, BlockExecutionResult, ExecutionError, ExecutionErrorCode
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.runtime import DAGRunner, RunSummary
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import EventRecord, FileRunStore, StateStoreError
from cgkn.state.task_feedback import TaskFeedback

from .composer import AgentComposer, AgentDecisionContext, AgentDecisionValidationError


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
    def __init__(self, composer: AgentComposer, runner: DAGRunner, store: FileRunStore, *, known_capabilities: set[str], worker_model: str, capability_catalog: dict[str, Any] | None = None, max_decisions: int = 4, acceptance=None, continuous: bool = False):
        if not isinstance(max_decisions, int) or max_decisions < 1:
            raise ValueError("max_decisions must be a positive resource bound")
        self.composer, self.runner, self.store = composer, runner, store
        self.known_capabilities, self.max_decisions = frozenset(known_capabilities), max_decisions
        self.acceptance, self.continuous = acceptance, continuous
        self.capability_catalog = dict(capability_catalog or {})

    @observed("project_agent", lambda a: a["self"].store.run_dir(a["project_id"], a["run_id"]))
    def run(self, *, project_id: str, run_id: str, goal: str, constraints: tuple[str, ...] = (), continuation_feedback: dict[str, Any] | None = None, resume: bool = False) -> ProjectLoopResult:
        tree = CapabilityTree(goal, ())
        summary: RunSummary | None = None
        failure_details: dict[str, Any] = {}
        worker_calls = 0
        execution_results: dict[str, Any] = {}
        checkpoint = self.store.run_dir(project_id, run_id) / 'agent_checkpoint.json'
        first = 1
        if resume and not self.continuous:
            # Continue the canonical graph, never infer executable state from a report.
            root=self.store.run_dir(project_id,run_id)
            tree=CapabilityTree.from_dict(json.loads((root/'capability_tree.json').read_text(encoding='utf-8')))
            if tree.goal!=goal:raise ValueError('resume goal changed')
            state=self.store.load_run(project_id,run_id)
            if compile_tree(tree).as_dict()!=state.execution_dag:raise ValueError('resume graph mismatch')
            tree,summary=self._recover_interrupted(project_id,run_id,tree,summary)
            failure_details=self._failure_details(project_id,run_id,summary)
            decisions=list((root/'agent').glob('decision-*.json'))
            first=1+max([int(p.stem.removeprefix('decision-')) for p in decisions] or [0])
        if self.continuous and checkpoint.exists():
            prior = json.loads(checkpoint.read_text(encoding='utf-8'))
            if prior['goal'] != goal: raise ValueError('checkpoint goal changed')
            tree = CapabilityTree.from_dict(prior['tree'])
            summary = RunSummary(**prior['summary']) if prior['summary'] else None
            failure_details, execution_results = prior['failure_details'], prior['execution_results']
            worker_calls, first = prior['worker_calls'], prior['next_decision']
            for key,value in prior.get('composer_state',{}).items():
                if key in {'_previous_action','_blocked_action','_observation_repeats','_alternative_used','_stagnation_count','_stagnation_signature','_artifact_hash','_frontier_fingerprint','_frontier_rounds','_frontier_models'}:setattr(self.composer,key,value)
            if (checkpoint.parent/'agent'/f'decision-{first:02d}.json').exists():
                # A decision may have been persisted immediately before process
                # loss. Never send it again or replay an unknown side effect.
                tree, summary = self._recover_interrupted(project_id, run_id, tree, summary)
                if summary: failure_details = self._failure_details(project_id, run_id, summary)
                failure_details['checkpoint_recovery'] = {'decision_ref': f'agent/decision-{first:02d}.json', 'instruction': 'The saved graph is authoritative. A persisted decision may not have committed. Inspect current graph and results; changing a succeeded node requires retry_node on that node, not only its descendant. Do not replay successful work unnecessarily.'}
                rejection = [e for e in self.store.load_events(project_id, run_id)
                             if e.event_type=='AGENT_DECISION_REJECTED' and e.data.get('decision_number')==first]
                if rejection:
                    failure_details['decision_validation']={k:rejection[-1].data[k] for k in ('error','error_type') if k in rejection[-1].data}
                first += 1
        if continuation_feedback:
            failure_details["continuation_requirements"] = dict(continuation_feedback)
        for number in itertools.count(first) if self.continuous else range(first, first+self.max_decisions):
            if self.continuous:
                self.store.atomic_json(checkpoint, {'goal': goal, 'tree': tree.as_dict(),
                    'summary': summary.as_dict() if summary else None, 'failure_details': failure_details,
                    'execution_results': execution_results, 'worker_calls': worker_calls, 'next_decision': number,
                    'composer_state':{k:getattr(self.composer,k) for k in ('_previous_action','_blocked_action','_observation_repeats','_alternative_used','_stagnation_count','_stagnation_signature','_artifact_hash','_frontier_fingerprint','_frontier_rounds','_frontier_models') if hasattr(self.composer,k)}})
                if number > first and (number-1) % self.max_decisions == 0:
                    self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, 'AGENT_CHECKPOINT_CONTINUED', data={'next_decision': number}))
            try:
                decision = self.composer.decide(AgentDecisionContext(project_id, run_id, goal, number, tree, tuple(sorted(self.known_capabilities)), self.capability_catalog, summary.as_dict() if summary else {}, failure_details, execution_results, self.acceptance.view() if self.acceptance else {}, {**TaskFeedback(self.store, project_id, run_id).context(), "capability_observations": TaskFeedback(self.store, project_id, run_id).statistics(self.acceptance)}, self.runner.knowledge.retrieve(self.known_capabilities) if getattr(self.runner, "knowledge", None) else {}))
            except AgentDecisionValidationError as exc:
                failure_details = {**failure_details, "decision_validation": exc.feedback}
                self.store.save_agent_decision(project_id, run_id, number, {"rejected": True, **exc.feedback})
                self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION_REJECTED", data={"decision_number": number, **exc.feedback}))
                protocol=exc.feedback.get('protocol_error',{})
                if protocol.get('correction_path_terminated'):
                    return ProjectLoopResult('BLOCKED',number,number,worker_calls,tree,summary,
                        (protocol.get('failure_domain','ADMISSION')+': '+protocol.get('code','UNKNOWN'))
                        if protocol.get('failure_domain') else 'ADMISSION_STRATEGY_EXHAUSTED: identical invalid proposal reached bounded correction limit')
                continue
            self.store.save_agent_decision(project_id, run_id, number, decision.as_dict())
            self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION", data={"decision_id": decision.decision_id, "decision_number": number, "summary": decision.summary, "request_run": decision.request_run, "finish": decision.finish, "needs_escalation": decision.needs_escalation, "context_hash": decision.context_hash}))
            if decision.needs_escalation:
                return ProjectLoopResult("BLOCKED", number, number, worker_calls, tree, summary, decision.escalation_reason)
            retry_nodes = [edit.node_id for edit in decision.edits if edit.operation == "retry_node"]
            retry_node = retry_nodes[0] if retry_nodes else None
            try:
                if len(retry_nodes) > 1:
                    raise ValueError("one Agent decision may retry at most one node")
                if decision.goal_plan and decision.edits:
                    raise ValueError('commit goal plan and executable edits in separate validated decisions; no half-updated plan/graph')
                if self.acceptance and not self.acceptance.data['plans']:
                    if any(self.capability_catalog.get(edit.payload.get('capability_ref',''),{}).get('produces_artifacts') for edit in decision.edits):
                        raise ValueError('register requirement-linked goal plan before producer work; inspection can proceed')
                proposed = apply_tree_edits(tree, decision.edits, known_capabilities=self.known_capabilities)
                dag = compile_tree(proposed)
                proposed_plan = self.acceptance.propose(decision.goal_plan, proposed) if self.acceptance and decision.goal_plan else None
                if decision.request_run and not dag.nodes:
                    raise ValueError("Agent requested a run with no executable nodes")
            except (ValueError, KeyError, TypeError) as exc:
                feedback = {"error_type": type(exc).__name__, "error": str(exc), "decision_ref": f"agent/decision-{number:02d}.json"}
                failure_details = {**failure_details, "decision_validation": feedback}
                self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION_REJECTED", data={"decision_number": number, **feedback}))
                continue
            if proposed_plan is not None: self.acceptance.commit(proposed_plan)
            previous_tree = tree
            tree = proposed
            failure_details.pop("decision_validation", None)
            if decision.finish:
                if not self.acceptance:
                    # An explicit terminal decision without a goal checker is a
                    # closed, unqualified run. Do not keep calling the planner
                    # merely because execution-only legacy callers omitted it.
                    return ProjectLoopResult('FAILED',number,number,worker_calls,tree,summary,
                        'GOAL_ACCEPTANCE_NOT_BOUND: independent goal checker required')
                from cgkn.execution.deliverables import parent_projection
                receipts = {}
                for leaf in tree.nodes:
                    if not leaf.executable: continue
                    try:
                        receipt = self.store.load_result(project_id,run_id,leaf.id)
                        c = leaf.config['leaf_contract']
                        checker=self.runner.registry.resolve(self.runner.deliverable_checkers[c['checker_ref']], 'deliverable.check@1')
                        if checker.snapshot(c)==dict(receipt.metadata.get('deliverable_check',{}).get('subjects',{})):
                            receipts[leaf.id]=receipt
                    except StateStoreError: pass
                own = {g['id']:g['verdict'] for g in self.acceptance.view()['goals']}
                parents = parent_projection(tree,receipts,own)
                if any(v['verdict'] != 'VERIFIED' for v in parents.values()):
                    failure_details['parent_acceptance'] = parents
                    continue
                if self.acceptance and not self.acceptance.view()['complete']:
                    failure_details['goal_acceptance'] = {'error': 'MUST goals lack current valid evidence', 'view': self.acceptance.view()}
                    continue
                status = "GOALS_VERIFIED" if self.acceptance else "SUCCEEDED" if summary and summary.status == "SUCCEEDED" else "FAILED"
                return ProjectLoopResult(status, number, number, worker_calls, tree, summary)
            if decision.request_run:
                try:
                    summary = self.runner.run(project_id=project_id, run_id=run_id, tree=tree, dag=dag, resume=summary is not None, retry_node=retry_node, constraints=constraints, accept_edits=summary is not None)
                except GraphEditRejected as exc:
                    tree = previous_tree
                    feedback = {"error_type": type(exc).__name__, "error": str(exc), "decision_ref": f"agent/decision-{number:02d}.json"}
                    failure_details["decision_validation"] = feedback
                    self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION_REJECTED", data={"decision_number": number, **feedback}))
                    continue
                worker_calls += sum(1 for node_id in summary.actual_executions
                    if not tree.by_id[node_id].config.get("meta_operation")
                    and tree.by_id[node_id].config.get("executor_ref") != "task.evaluate@1"
                    and any(e.descriptor.executor_ref == tree.by_id[node_id].config.get("executor_ref") and e.descriptor.kind == "bounded_llm" for e in self.runner.registry.list()))
                if retry_node and tree.by_id[retry_node].config.get('repair_contract'):
                    from cgkn.state.repair import record_repair_phase
                    record_repair_phase(self.store,project_id,run_id,retry_node,'REPAIR_ADMITTED',
                        {'decision_id':decision.decision_id,'repair_contract':tree.by_id[retry_node].config['repair_contract'],
                         'graph_committed':True})
                failure_details = self._failure_details(project_id, run_id, summary)
                for node_id in summary.actual_executions:
                    result = self.store.load_result(project_id, run_id, node_id)
                    if tree.by_id[node_id].config.get('repair_contract'):
                        from cgkn.state.repair import record_repair_phase
                        record_repair_phase(self.store,project_id,run_id,node_id,
                            'REPAIR_EXECUTED' if result.status.value=='SUCCEEDED' else 'REPAIR_BLOCKED',
                            {'attempt_id':result.attempt_id,'execution_status':result.status.value,
                             'formal_acceptance':'NOT_IMPLIED_BY_EXECUTION'})
                    if self.acceptance and result.executor_ref in self.acceptance.checkers.values():
                        goal_id = result.outputs.get('goal_check', {}).get('goal_id')
                        if goal_id: self.acceptance.record(goal_id, result, executor_ref=result.executor_ref)
                    execution_results.pop(node_id, None)
                    execution_results[node_id] = {"status": result.status.value, "outputs": result.as_dict()['outputs'], "error": result.error.as_dict() if result.error else None}
                # Mechanical bounded history. Full per-node results remain in
                # FileRunStore and the route's own result-reference adapter.
                execution_results = dict(list(execution_results.items())[-6:])
        return ProjectLoopResult("BLOCKED", number, self.max_decisions, worker_calls, tree, summary, "agent decision limit reached")

    def _recover_interrupted(self, project_id, run_id, tree, summary):
        from cgkn.state.store import StateStoreError
        try: state = self.store.load_run(project_id,run_id)
        except StateStoreError: return tree,summary
        definition=self.store.run_dir(project_id,run_id)/'capability_tree.json'
        recovered=CapabilityTree.from_dict(json.loads(definition.read_text(encoding='utf-8')))
        if compile_tree(recovered, historical_read_only=True).as_dict()!=state.execution_dag:
            raise RuntimeError('RECOVERY_GRAPH_MISMATCH: reconcile committed graph before execution')
        state = self.runner.recover_interrupted(project_id, run_id, recovered)
        recovered_summary=RunSummary(project_id,run_id,'BLOCKED',len(state.nodes),(),
            tuple(n for n,r in state.nodes.items() if r.status=='SUCCEEDED'),
            tuple(n for n,r in state.nodes.items() if r.status in {'FAILED','TIMED_OUT'}),
            tuple(n for n,r in state.nodes.items() if r.status=='BLOCKED'),0)
        self.store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,'AGENT_CHECKPOINT_RECOVERED',
            data={'unknown_nodes':list(recovered_summary.blocked_nodes),'automatic_replay':False}))
        return recovered,recovered_summary

    def _failure_details(self, project_id: str, run_id: str, summary: RunSummary) -> dict[str, Any]:
        details: dict[str, Any] = {}
        for node_id in (*summary.failed_nodes, *summary.blocked_nodes):
            result = self.store.load_result(project_id, run_id, node_id)
            details[node_id] = {"status": result.status.value, "error": result.error.as_dict() if result.error else None, "outputs": result.as_dict()['outputs']}
        return details
