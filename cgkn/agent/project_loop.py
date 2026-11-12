from __future__ import annotations

from cgkn.telemetry.lean import observed

import uuid
import json
import itertools
from dataclasses import dataclass, replace
from typing import Any

from cgkn.execution import BlockStatus, BlockExecutionResult, ExecutionError, ExecutionErrorCode
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.orchestration.tree_edits import apply_tree_edits
from cgkn.runtime import DAGRunner, RunSummary
from cgkn.runtime.dag_runner import GraphEditRejected
from cgkn.state import EventRecord, FileRunStore, StateStoreError
from cgkn.state.task_feedback import TaskFeedback
from cgkn.protocol.normalization import ContractError

from .composer import AgentComposer, AgentDecisionContext, AgentDecisionValidationError
from .project_agent import AdmissionPolicy, ProjectProposal, admit_proposal
from .progress import (ExecutionProgressController, PROJECT_REPLAN, QUARANTINE_STRATEGY,
                       STOP_BUDGET, STOP_INFRA, STOP_UNKNOWN, observe_result)


@dataclass(frozen=True)
class ProjectLoopResult:
    status: str
    decision_count: int
    agent_calls: int
    worker_calls: int
    tree: CapabilityTree
    run_summary: RunSummary | None
    escalation_reason: str = ""
    execution_mode: str = 'LEGACY'  # Old serialized summaries have no governed provenance.

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "execution_mode": self.execution_mode, "decision_count": self.decision_count, "agent_calls": self.agent_calls, "worker_calls": self.worker_calls, "tree": self.tree.as_dict(), "run_summary": self.run_summary.as_dict() if self.run_summary else None, "escalation_reason": self.escalation_reason}


class ProjectSession:
    """Canonical project coordinator over the existing graph and run store.

    The session owns no separate state database, scheduler or acceptance truth.
    All checkpoints, effects and verification remain with the injected existing
    authorities. ``AgentProjectLoop`` below is an identity alias for callers
    migrating to the canonical public name, not a second lifecycle.
    """
    def __init__(self, composer: AgentComposer, runner: DAGRunner, store: FileRunStore, *, known_capabilities: set[str], worker_model: str, capability_catalog: dict[str, Any] | None = None, max_decisions: int = 4, acceptance=None, continuous: bool = False, subject_snapshot=None, admission_policy: AdmissionPolicy | None = None, progress_controller: ExecutionProgressController | None = None, skill_matcher=None, skill_task=None, execution_mode='GOVERNED'):
        from veriarbor.execution_authority import ExecutionMode
        self.execution_mode=ExecutionMode(execution_mode)
        if self.execution_mode=='IMPORTED_UNMANAGED':raise ValueError('audit imports do not execute a Session')
        if self.execution_mode!=runner.execution_mode:raise ValueError('Session and DAGRunner execution modes must match explicitly')
        if self.execution_mode=='GOVERNED' and admission_policy is None:
            raise ValueError('governed Session requires explicit capability admission policy')
        if self.execution_mode=='LEGACY':
            from veriarbor.governance import require_legacy
            require_legacy()
            import warnings
            warnings.warn('LEGACY ProjectSession: no governed lineage',RuntimeWarning)
        if not isinstance(max_decisions, int) or max_decisions < 1:
            raise ValueError("max_decisions must be a positive resource bound")
        self.composer, self.runner, self.store = composer, runner, store
        self.known_capabilities, self.max_decisions = frozenset(known_capabilities), max_decisions
        self.acceptance, self.continuous = acceptance, continuous
        self.subject_snapshot = subject_snapshot
        self.capability_catalog = dict(capability_catalog or {})
        self.admission_policy = admission_policy
        self.progress_controller = progress_controller
        self.tree_version = 1
        self.skill_matcher, self.skill_task = skill_matcher, skill_task
        if skill_matcher is not None and (admission_policy is None or not admission_policy.capability_contracts):
            raise ValueError('Skill reuse requires capability admission policy')

    @observed("project_agent", lambda a: a["self"].store.run_dir(a["project_id"], a["run_id"]))
    def run(self, *, project_id: str, run_id: str, **kwargs) -> ProjectLoopResult:
        # The DAG lock protects execution, but planning also publishes contexts,
        # admissions and checkpoints. Reuse the store's OS lock for that lifetime.
        # A distinct lock avoids recursively acquiring the DAG coordinator lock.
        with self.store.exclusive_file(self.store.run_dir(project_id, run_id) / 'session.lock'):
            return self._run(project_id=project_id, run_id=run_id, **kwargs)

    def _run(self, *, project_id: str, run_id: str, goal: str, constraints: tuple[str, ...] = (), continuation_feedback: dict[str, Any] | None = None, resume: bool = False, project_intent: dict[str, Any] | None = None, cancel=None, finish_when_verified: bool = False, planning=None) -> ProjectLoopResult:
        authority=self.runner._authority(project_id,run_id) if self.execution_mode=='GOVERNED' else None
        if self.execution_mode=='LEGACY':
            from veriarbor.governance import require_legacy
            self.store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,'LEGACY_EXECUTION_WARNING',
                data=require_legacy(project_id=project_id,run_id=run_id)))
        project_intent = self._bind_intent(project_id, run_id, goal, project_intent, constraints)
        if project_intent:
            declared_constraints = tuple(project_intent['constraints'])
            constraints = declared_constraints
        tree = CapabilityTree(goal, ())
        summary: RunSummary | None = None
        failure_details: dict[str, Any] = {}
        worker_calls = 0
        agent_calls = 0
        execution_results: dict[str, Any] = {}
        checkpoint = self.store.run_dir(project_id, run_id) / 'agent_checkpoint.json'
        # A saved incomplete planning response is also an unknown paid
        # attempt. Re-entering the session must not silently replace it with
        # a new declaration merely because no executable graph was committed.
        event_path = checkpoint.parent / 'events.jsonl'
        if event_path.exists():
            unresolved = [e for e in self.store.load_events(project_id, run_id)
                          if e.event_type == 'AGENT_DECISION_REJECTED'
                          and e.data.get('protocol_error', {}).get('outcome_unknown')]
            if unresolved:
                definition = checkpoint.parent / 'capability_tree.json'
                if definition.exists():
                    tree = CapabilityTree.from_dict(json.loads(definition.read_text(encoding='utf-8')))
                return ProjectLoopResult('BLOCKED', 0, 0, 0, tree, None,
                    'PLANNER_OUTCOME_UNKNOWN: reconcile saved response and accounting before continuation; '
                    + unresolved[-1].event_id, execution_mode=self.execution_mode.value)
        first = 1
        if resume and not self.continuous:
            # Continue the canonical graph, never infer executable state from a report.
            root=self.store.run_dir(project_id,run_id)
            tree=CapabilityTree.from_dict(json.loads((root/'capability_tree.json').read_text(encoding='utf-8')))
            if tree.goal!=goal:raise ValueError('resume goal changed')
            if (root/'run_state.json').exists():
                state=self.store.load_run(project_id,run_id)
                pending_admitted_edit=compile_tree(tree).as_dict()!=state.execution_dag
                if pending_admitted_edit:
                    # Admission can commit a repair proposal before DAG reuse
                    # validation rejects its missing retry. Keep both records:
                    # a trusted explicit redecision may repair that proposal,
                    # but must not rewrite or execute the older RunState here.
                    committed=authority.committed_tree() if authority else None
                    if (not (continuation_feedback or {}).get('redecision') or not committed or
                            CapabilityTree.from_dict(committed['tree']).as_dict()!=tree.as_dict()):
                        raise ValueError('resume graph mismatch')
                    if any(n.status in {'RUNNING','UNKNOWN'} for n in state.nodes.values()):
                        raise ValueError('resume pending edit has unresolved execution')
                    failure_details={'pending_admitted_edit':'Tree edit was admitted but did not commit to execution DAG. Repair proposal with explicit affected-subgraph retry; do not infer new execution.'}
                    summary=RunSummary(project_id,run_id,'BLOCKED',len(state.nodes),(),(),
                        tuple(k for k,v in state.nodes.items() if v.status=='FAILED'),
                        tuple(k for k,v in state.nodes.items() if v.status=='BLOCKED'),0,
                        execution_mode=self.execution_mode.value)
                else:
                    tree,summary=self._recover_interrupted(project_id,run_id,tree,summary)
                    failure_details=self._failure_details(project_id,run_id,summary)
            elif any(n.executable for n in tree.nodes):
                raise ValueError('resume executable graph has no run state')
            # Rejected planning-only attempts have receipts but no DAG run yet.
            # Resume their decision sequence without inventing execution state.
            decisions=list((root/'agent').glob('decision-*.json'))
            first=1+max([int(p.stem.removeprefix('decision-')) for p in decisions] or [0])
        if self.continuous and checkpoint.exists():
            prior = json.loads(checkpoint.read_text(encoding='utf-8'))
            if prior['goal'] != goal: raise ValueError('checkpoint goal changed')
            tree = CapabilityTree.from_dict(prior['tree'])
            summary = RunSummary(**prior['summary']) if prior['summary'] else None
            failure_details, execution_results = prior['failure_details'], prior['execution_results']
            worker_calls, first = prior['worker_calls'], prior['next_decision']
            self.tree_version = int(prior.get('tree_version', self.tree_version))
            for key,value in prior.get('composer_state',{}).items():
                if key in {'_previous_action','_blocked_action','_observation_repeats','_alternative_used','_stagnation_count','_stagnation_signature','_artifact_hash','_frontier_fingerprint','_frontier_rounds','_frontier_models'}:setattr(self.composer,key,value)
            # A committed graph can outlive an older Agent checkpoint even
            # when the next decision file does not exist (legacy admission
            # failure or interruption between checkpoints). The run store is
            # execution authority; never silently discard either graph branch.
            committed_graph_recovered = False
            if (checkpoint.parent/'run_state.json').exists():
                committed = self.store.load_run(project_id, run_id)
                planned_ids = {node.id for node in compile_tree(tree, historical_read_only=True).nodes}
                committed_ids = set(committed.nodes)
                if committed_ids - planned_ids:
                    if planned_ids - committed_ids:
                        raise RuntimeError('RECOVERY_GRAPH_DIVERGED: preserve uncommitted intent and reconcile both graph branches')
                    import base64, hashlib
                    original_checkpoint = checkpoint.read_bytes()
                    checkpoint_hash = hashlib.sha256(original_checkpoint).hexdigest()
                    snapshot = checkpoint.parent/'recovery'/('agent-checkpoint-'+checkpoint_hash+'.json')
                    self.store.immutable_json(snapshot, {'encoding':'base64','sha256':checkpoint_hash,
                        'content':base64.b64encode(original_checkpoint).decode('ascii')})
                    tree, summary = self._recover_interrupted(project_id, run_id, tree, summary)
                    committed_graph_recovered = True
                    if summary:
                        failure_details = {**failure_details, **self._failure_details(project_id, run_id, summary)}
                    self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id,
                        'AGENT_COMMITTED_GRAPH_RECONCILED', data={'checkpoint_snapshot_ref':str(snapshot),
                            'original_checkpoint_sha256':checkpoint_hash,
                            'adopted_committed_nodes':sorted(committed_ids-planned_ids),
                            'automatic_replay':False,'authority':'FileRunStore.execution_dag'}))
            if (checkpoint.parent/'agent'/f'decision-{first:02d}.json').exists():
                # A decision may have been persisted immediately before process
                # loss. Never send it again or replay an unknown side effect.
                if not committed_graph_recovered:
                    tree, summary = self._recover_interrupted(project_id, run_id, tree, summary)
                if summary: failure_details = self._failure_details(project_id, run_id, summary)
                failure_details['checkpoint_recovery'] = {'decision_ref': f'agent/decision-{first:02d}.json', 'instruction': 'The saved graph is authoritative. A persisted decision may not have committed. Inspect current graph and results; changing a succeeded node requires retry_node on that node, not only its descendant. Do not replay successful work unnecessarily.'}
                rejection = [e for e in self.store.load_events(project_id, run_id)
                             if e.event_type=='AGENT_DECISION_REJECTED' and e.data.get('decision_number')==first]
                if rejection:
                    failure_details['decision_validation']={k:rejection[-1].data[k] for k in ('error','error_type','protocol_error','raw_evidence') if k in rejection[-1].data}
                first += 1
        if self.acceptance and (resume or self.continuous and checkpoint.exists()):
            if self.acceptance.data['plans']:
                self._refresh_milestone_subjects(self.acceptance.data['plans'][-1])
                self._reconcile_completed_checks(project_id, run_id)
        if continuation_feedback:
            failure_details["continuation_requirements"] = dict(continuation_feedback)
        root = self.store.run_dir(project_id, run_id)
        if (root/'events.jsonl').exists():
            events = self.store.load_events(project_id, run_id)
        elif (root/'run_state.json').exists() or any((root/'agent').glob('decision-*.json')):
            raise StateStoreError('existing execution history has no event log; reconcile evidence before continuation')
        else:
            events = ()
        previous_progress = next((dict(e.data) for e in reversed(events)
                                  if e.event_type == 'PROJECT_PROGRESS'), {})
        admission_repeats={};finish_rejections=0;empty_blocked_runs=0
        for event in events:
            if event.event_type=='AGENT_CONTINUATION_REDECISION' or (event.event_type=='PROJECT_PROGRESS' and event.data.get('progress_observed')):
                admission_repeats.clear();finish_rejections=0
                if event.event_type=='AGENT_CONTINUATION_REDECISION':empty_blocked_runs=0
            elif event.event_type=='PROJECT_EXECUTION_CHECKPOINT':empty_blocked_runs=event.data['consecutive_empty_blocked_runs']
            elif event.event_type=='AGENT_FINISH_REJECTED':finish_rejections+=1
            elif event.event_type=='AGENT_DECISION_REJECTED':
                protocol=event.data.get('protocol_error',{})
                original=protocol.get('original_error',protocol)
                key=json.dumps([original.get('code',event.data.get('error')),original.get('fields',[])],sort_keys=True)
                admission_repeats[key]=admission_repeats.get(key,0)+1
        unknown_nodes = self._unresolved_execution_nodes(project_id, run_id)
        if unknown_nodes:
            return ProjectLoopResult('BLOCKED', 0, 0, worker_calls, tree, summary,
                'EXECUTION_OUTCOME_UNKNOWN: reconcile saved receipts before further planning; '
                + ','.join(unknown_nodes), execution_mode=self.execution_mode.value)
        redecision=(continuation_feedback or {}).get('redecision')
        if redecision is not None:
            import re
            if (not resume or not isinstance(redecision,dict) or set(redecision)!={'strategy_revision','reason','evidence_refs'}
                    or not re.fullmatch('[0-9a-f]{64}',str(redecision.get('strategy_revision','')))
                    or not isinstance(redecision.get('reason'),str) or not redecision['reason'].strip()
                    or not isinstance(redecision.get('evidence_refs'),list) or not redecision['evidence_refs']
                    or any(not isinstance(ref,str) or not ref.strip() for ref in redecision['evidence_refs'])):
                raise ValueError('explicit resume redecision requires revision, reason and evidence refs')
            if any(e.event_type=='AGENT_CONTINUATION_REDECISION' and e.data.get('strategy_revision')==redecision['strategy_revision'] for e in events):
                raise ValueError('redecision revision already consumed; do not reset repeated-failure protection')
            self.store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,'AGENT_CONTINUATION_REDECISION',data=dict(redecision)))
            admission_repeats.clear();finish_rejections=0;empty_blocked_runs=0
        pending_context = root/'agent'/f'context-{first:02d}.json'
        pending_decision = root/'agent'/f'decision-{first:02d}.json'
        while pending_context.exists() and not pending_decision.exists():
            if not redecision:
                return ProjectLoopResult('BLOCKED', 0, 0, worker_calls, tree, summary,
                    'PLANNER_CONTEXT_INTERRUPTED: inspect original request/accounting and explicitly redecide; '
                    + pending_context.name, execution_mode=self.execution_mode.value)
            import hashlib
            self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id,
                'AGENT_INTERRUPTED_CONTEXT_RETAINED', data={
                    'decision_number': first, 'context_ref': str(pending_context),
                    'context_sha256': hashlib.sha256(pending_context.read_bytes()).hexdigest(),
                    'strategy_revision': redecision['strategy_revision'],
                    'evidence_refs': redecision['evidence_refs'],
                    'disposition': 'New decision identity; original provider outcome/accounting unchanged'}))
            failure_details['interrupted_planning'] = {
                'context_ref': str(pending_context), 'decision_number': first,
                'instruction': 'Previous planning attempt was interrupted. Preserve its evidence; inspect current canonical receipts before this explicitly authorized new decision.'}
            first += 1
            pending_context = root/'agent'/f'context-{first:02d}.json'
            pending_decision = root/'agent'/f'decision-{first:02d}.json'
        if empty_blocked_runs>=2:
            return ProjectLoopResult('BLOCKED',0,0,worker_calls,tree,summary,
                'DAG_NO_EXECUTABLE_PROGRESS: repeated runs execute no nodes because prerequisites remain blocked; explicit redecision required', execution_mode=self.execution_mode.value)
        if any(count>=2 for count in admission_repeats.values()):
            return ProjectLoopResult('BLOCKED',0,0,worker_calls,tree,summary,
                'ADMISSION_NO_PROGRESS: repeated contract rejection; explicit strategy correction required', execution_mode=self.execution_mode.value)
        if finish_rejections>=2:
            return ProjectLoopResult('BLOCKED',0,0,worker_calls,tree,summary,
                'FINISH_NO_PROGRESS: repeated finish without current independent acceptance', execution_mode=self.execution_mode.value)
        for number in itertools.count(first) if self.continuous else range(first, first+self.max_decisions):
            if self.acceptance and self.acceptance.data['plans']:
                self._refresh_milestone_subjects(self.acceptance.data['plans'][-1])
            if self.continuous:
                self.store.atomic_json(checkpoint, {'goal': goal, 'tree': tree.as_dict(),
                    'summary': summary.as_dict() if summary else None, 'failure_details': failure_details,
                    'execution_results': execution_results, 'worker_calls': worker_calls, 'next_decision': number,
                    'tree_version': self.tree_version,
                    'composer_state':{k:getattr(self.composer,k) for k in ('_previous_action','_blocked_action','_observation_repeats','_alternative_used','_stagnation_count','_stagnation_signature','_artifact_hash','_frontier_fingerprint','_frontier_rounds','_frontier_models') if hasattr(self.composer,k)}})
                if number > first and (number-1) % self.max_decisions == 0:
                    self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, 'AGENT_CHECKPOINT_CONTINUED', data={'next_decision': number}))
            if cancel is not None and cancel.is_set():
                self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id,
                    'SESSION_STOPPED', data={'next_decision': number, 'boundary': 'before_planner',
                                             'remote_stop_confirmed': False}))
                return ProjectLoopResult('STOPPED', number-1, agent_calls, worker_calls,
                    tree, summary, 'cooperative stop requested', execution_mode=self.execution_mode.value)
            if finish_when_verified and self._current_completion(project_id, run_id, tree):
                self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id,
                    'SESSION_GOALS_VERIFIED', data={'planner_called': False,
                                                   'authority': 'GoalAcceptance and current parent projection'}))
                return ProjectLoopResult('GOALS_VERIFIED', number-1, agent_calls, worker_calls,
                    tree, summary, execution_mode=self.execution_mode.value)
            previous_progress, visible_progress = self._record_progress(project_id, run_id, number, tree, previous_progress)
            if previous_progress.get('progress_observed'):
                admission_repeats.clear();finish_rejections=0
            try:
                # Execution refreshes observations, not the user-authorized continuation scope.
                # Reattach the explicit continuation to every decision; current acceptance remains separate.
                if continuation_feedback:
                    failure_details["continuation_requirements"] = dict(continuation_feedback)
                context = AgentDecisionContext(project_id, run_id, goal, number, tree, tuple(sorted(self.known_capabilities)), self.capability_catalog, summary.as_dict() if summary else {}, failure_details, execution_results, self.acceptance.view() if self.acceptance else {}, {**TaskFeedback(self.store, project_id, run_id).context(), "capability_observations": TaskFeedback(self.store, project_id, run_id).statistics(self.acceptance), 'progress_receipt':visible_progress}, self.runner.knowledge.retrieve(self.known_capabilities) if getattr(self.runner, "knowledge", None) else {}, project_intent)
                if self.admission_policy and self.admission_policy.capability_contracts:
                    from cgkn.adapters.veriarbor.capability_adapter import load as capability_state
                    from veriarbor.capability import GoalGap
                    gaps = [dict(raw, priority=GoalGap(**raw).priority) for raw in self.admission_policy.goal_gaps.values()]
                    context = replace(context, task_feedback={**context.task_feedback, 'capability_governance': {
                        'contracts': dict(self.admission_policy.capability_contracts),
                        'goal_gaps': sorted(gaps, key=lambda row: (-row['priority'], row['gap_id'])),
                        'gates': {key: row.get('gates', {}) for key, row in
                                  capability_state(self.store, project_id, run_id)['nodes'].items()},
                        'proposal_instruction': 'For executable edits supply decision_audit.capability_claim: '
                            'target_capability_id, target_gap_id, strategy_capabilities; '
                            'bounded exploration may use exploration_reason, exploration_budget and exploration_measure.'}})
                if self.skill_matcher is not None:
                    index = [row for row in self.skill_matcher.registry.index()
                             if row['scope'] == 'SHARED' or row['project_id'] == project_id]
                    context = replace(context, retrieved_knowledge={**context.retrieved_knowledge,
                                                                  'skill_index': index})
                self.store.immutable_json(root/'agent'/f'context-{number:02d}.json', context.as_dict())
                try:
                    decision = None
                    if self.skill_matcher is not None and self.skill_task:
                        from cgkn.adapters.veriarbor.capability_adapter import skill_decision
                        trial=getattr(self,'skill_trial',None)
                        manifest=self.skill_lifecycle.trial_manifest(trial,project_id=project_id,task=self.skill_task) if trial else None
                        decision = skill_decision(self.skill_matcher,self.skill_task,context,compiler=self.composer,manifest=manifest,trial=bool(trial))
                    if decision is None:
                        agent_calls += 1
                        if planning is None:
                            decision = self.composer.decide(context)
                        else:
                            decision, tree = planning.decide(self, context)
                except RuntimeError as exc:
                    if str(exc).startswith("PROVIDER_BUDGET_EXHAUSTED"):
                        self.store.append_event(EventRecord(
                            str(uuid.uuid4()), project_id, run_id, "BUDGET_BLOCKED",
                            data={"decision_number": number, "stage": "planner",
                                  "message": str(exc)}))
                        return ProjectLoopResult(
                            'BLOCKED', number, agent_calls, worker_calls, tree, summary,
                            'BUDGET_BLOCKED: provider budget denied; no further planning or worker calls', execution_mode=self.execution_mode.value)
                    raise
            except (AgentDecisionValidationError, ContractError) as exc:
                feedback = exc.feedback if isinstance(exc, AgentDecisionValidationError) else {
                    'error_type':type(exc).__name__, 'error':str(exc), 'protocol_error':exc.as_dict(),
                    'raw_evidence':'canonical protocol trace; no synthetic provider response'}
                failure_details = {**failure_details, "decision_validation": feedback}
                self.store.save_agent_decision(project_id, run_id, number, {"rejected": True, **feedback})
                self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION_REJECTED", data={"decision_number": number, **feedback}))
                protocol=feedback.get('protocol_error',{})
                original=protocol.get('original_error',protocol)
                key=json.dumps([original.get('code',feedback.get('error')),original.get('fields',[])],sort_keys=True)
                admission_repeats[key]=admission_repeats.get(key,0)+1
                if admission_repeats[key]>=2:
                    return ProjectLoopResult('BLOCKED',number,agent_calls,worker_calls,tree,summary,
                        'ADMISSION_NO_PROGRESS: repeated contract rejection; explicit strategy correction required', execution_mode=self.execution_mode.value)
                if protocol.get('correction_path_terminated'):
                    return ProjectLoopResult('BLOCKED',number,agent_calls,worker_calls,tree,summary,
                        (protocol.get('failure_domain','ADMISSION')+': '+protocol.get('code','UNKNOWN'))
                        if protocol.get('failure_domain') else 'ADMISSION_STRATEGY_EXHAUSTED: identical invalid proposal reached bounded correction limit', execution_mode=self.execution_mode.value)
                continue
            self.store.save_agent_decision(project_id, run_id, number, decision.as_dict())
            self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION", data={"decision_id": decision.decision_id, "decision_number": number, "summary": decision.summary, "request_run": decision.request_run, "finish": decision.finish, "needs_escalation": decision.needs_escalation, "context_hash": decision.context_hash}))
            if decision.needs_escalation:
                return ProjectLoopResult("BLOCKED", number, agent_calls, worker_calls, tree, summary, decision.escalation_reason, execution_mode=self.execution_mode.value)
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
                if self.admission_policy is not None and decision.edits:
                    operations = []
                    for edit in decision.edits:
                        payload = dict(edit.payload)
                        operations.append({
                            "operation": edit.operation, "node_id": edit.node_id,
                            "capability_ref": payload.get("capability_ref", ""),
                            "parent_id": payload.get("parent_id", ""),
                            "depends_on": list(payload.get("depends_on") or ()),
                            "config": dict(payload.get("config") or {}),
                            "payload": payload,
                        })
                    proposal = ProjectProposal(
                        proposal_id=decision.decision_id, project_id=project_id,
                        base_tree_version=self.tree_version, goal_reference=goal,
                        observed_evidence_refs=tuple(str(x) for x in
                            (failure_details.get("evidence_refs") or ())),
                        proposed_operations=tuple(operations),
                        repair_strategy=decision.summary,
                        resource_preference="embedded-planner",
                        expected_progress=decision.summary,
                        reason_summary=decision.reason or decision.summary,
                        **dict(decision.decision_audit.get('capability_claim', {})),
                    )
                    if authority:
                        admission_id,admitted=authority.admit(tree,self.tree_version,proposal,
                            known_capabilities=self.known_capabilities,catalog=self.capability_catalog,
                            policy=self.admission_policy)
                    else:
                        admitted = admit_proposal(tree, self.tree_version, proposal,
                                                  known_capabilities=self.known_capabilities,
                                                  catalog=self.capability_catalog,
                                                  policy=self.admission_policy)
                    self.store.append_event(EventRecord(
                        str(uuid.uuid4()), project_id, run_id,
                        "PROJECT_PROPOSAL_ADMITTED" if admitted.valid else "PROJECT_PROPOSAL_REJECTED",
                        data={"decision_number": number, "proposal_id": proposal.proposal_id,
                              "base_tree_version": proposal.base_tree_version,
                              "code": admitted.code, "message": admitted.message,
                              "details": dict(admitted.details)}))
                    if not admitted.valid:
                        feedback = {"error_type": "AdmissionRejected", "error": admitted.message,
                                    "decision_ref": f"agent/decision-{number:02d}.json",
                                    "admission_code": admitted.code,
                                    "admission_details": dict(admitted.details)}
                        failure_details = {**failure_details, "decision_validation": feedback}
                        self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id,
                            "AGENT_DECISION_REJECTED", data={"decision_number": number, **feedback}))
                        key = "ADMISSION:" + admitted.code
                        admission_repeats[key] = admission_repeats.get(key, 0) + 1
                        if admission_repeats[key] >= 2:
                            return ProjectLoopResult('BLOCKED', number, agent_calls, worker_calls, tree, summary,
                                'ADMISSION_NO_PROGRESS: repeated admission rejection; ' + admitted.code, execution_mode=self.execution_mode.value)
                        continue
                edits_to_apply = decision.edits
                proposed = admitted.preview if authority and decision.edits else apply_tree_edits(tree, edits_to_apply, known_capabilities=self.known_capabilities)
                dag = compile_tree(proposed)
                if self.acceptance and decision.goal_plan:
                    self._refresh_milestone_subjects(decision.goal_plan)
                proposed_plan = self.acceptance.propose(decision.goal_plan, proposed) if self.acceptance and decision.goal_plan else None
                if decision.request_run and not dag.nodes:
                    raise ValueError("Agent requested a run with no executable nodes")
                if decision.request_run:
                    self.runner.validate_graph_transition(project_id=project_id,run_id=run_id,tree=proposed,dag=dag,
                        retry_node=retry_node,accept_edits=summary is not None)
            except (ValueError, KeyError, TypeError) as exc:
                feedback = {"error_type": type(exc).__name__, "error": str(exc), "decision_ref": f"agent/decision-{number:02d}.json"}
                failure_details = {**failure_details, "decision_validation": feedback}
                self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION_REJECTED", data={"decision_number": number, **feedback}))
                key=json.dumps([feedback['error'],[]],sort_keys=True)
                admission_repeats[key]=admission_repeats.get(key,0)+1
                if admission_repeats[key]>=2:
                    return ProjectLoopResult('BLOCKED',number,agent_calls,worker_calls,tree,summary,
                        'ADMISSION_NO_PROGRESS: repeated graph rejection; inspect preserved error before explicit redecision', execution_mode=self.execution_mode.value)
                continue
            if proposed_plan is not None: self.acceptance.commit(proposed_plan)
            if authority and decision.edits:
                proposed=authority.commit_tree(admission_id)
            previous_tree = tree
            tree = proposed
            if self.admission_policy and self.admission_policy.capability_contracts:
                from cgkn.adapters.veriarbor.capability_adapter import record_phase
                for edit in decision.edits:
                    record_phase(self.store, project_id, run_id, edit.node_id, 'ADMITTED')
                    bindings = self.admission_policy.evidence_inputs.get(edit.node_id)
                    if bindings:
                        from cgkn.adapters.veriarbor.capability_adapter import bind_inputs
                        bind_inputs(self.store, project_id, run_id, edit.node_id, bindings)
            if authority and decision.edits:
                self.tree_version=authority.committed_tree()['tree_version']
            elif proposed.as_dict() != previous_tree.as_dict():
                self.tree_version += 1
            failure_details.pop("decision_validation", None)
            if decision.finish:
                if self.admission_policy and self.admission_policy.capability_contracts:
                    from cgkn.adapters.veriarbor.capability_adapter import completion_ready
                    if not completion_ready(self.store, project_id, run_id, self.admission_policy.capability_contracts, execution_mode=self.execution_mode):
                        return ProjectLoopResult('BLOCKED', number, agent_calls, worker_calls, tree, summary,
                                                 'CAPABILITY_OUTCOME_NOT_VERIFIED', execution_mode=self.execution_mode.value)
                if not self.acceptance:
                    # An explicit terminal decision without a goal checker is a
                    # closed, unqualified run. Do not keep calling the planner
                    # merely because execution-only legacy callers omitted it.
                    return ProjectLoopResult('FAILED',number,agent_calls,worker_calls,tree,summary,
                        'GOAL_ACCEPTANCE_NOT_BOUND: independent goal checker required', execution_mode=self.execution_mode.value)
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
                finish_blocked=False
                if any(v['verdict'] != 'VERIFIED' for v in parents.values()):
                    failure_details['parent_acceptance'] = parents
                    finish_blocked=True
                if self.acceptance and not self.acceptance.view()['complete']:
                    failure_details['goal_acceptance'] = {'error': 'MUST goals lack current valid evidence', 'view': self.acceptance.view()}
                    finish_blocked=True
                if finish_blocked:
                    finish_rejections+=1
                    self.store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,'AGENT_FINISH_REJECTED',
                        data={'decision_number':number,'consecutive_without_progress':finish_rejections,
                              'reason':'Current parent or goal acceptance is not verified'}))
                    if finish_rejections>=2:
                        return ProjectLoopResult('BLOCKED',number,agent_calls,worker_calls,tree,summary,
                            'FINISH_NO_PROGRESS: repeated finish without current independent acceptance', execution_mode=self.execution_mode.value)
                    continue
                status = "GOALS_VERIFIED" if self.acceptance else "SUCCEEDED" if summary and summary.status == "SUCCEEDED" else "FAILED"
                return ProjectLoopResult(status, number, agent_calls, worker_calls, tree, summary, execution_mode=self.execution_mode.value)
            if decision.request_run:
                try:
                    summary = self.runner.run(project_id=project_id, run_id=run_id, tree=tree, dag=dag, resume=summary is not None, retry_node=retry_node, constraints=constraints, accept_edits=summary is not None, **({'cancel': cancel} if cancel is not None else {}))
                except GraphEditRejected as exc:
                    # Admission may already be committed; never replace that
                    # authority with the older in-memory planning snapshot.
                    tree = CapabilityTree.from_dict(authority.committed_tree()['tree']) if authority else previous_tree
                    feedback = {"error_type": type(exc).__name__, "error": str(exc), "decision_ref": f"agent/decision-{number:02d}.json"}
                    failure_details["decision_validation"] = feedback
                    self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id, "AGENT_DECISION_REJECTED", data={"decision_number": number, **feedback}))
                    key=json.dumps([feedback['error'],[]],sort_keys=True)
                    admission_repeats[key]=admission_repeats.get(key,0)+1
                    if admission_repeats[key]>=2:
                        return ProjectLoopResult('BLOCKED',number,agent_calls,worker_calls,tree,summary,
                            'ADMISSION_NO_PROGRESS: repeated graph rejection; inspect preserved error before explicit redecision', execution_mode=self.execution_mode.value)
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
                latest_results = {}
                for node_id in summary.actual_executions:
                    result = self.store.load_result(project_id, run_id, node_id)
                    latest_results[node_id] = result
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
                    execution_results[node_id] = {"status": result.status.value, "outputs": result.as_dict()['outputs'], "error": result.error.as_dict() if result.error else None, "attempt_id": result.attempt_id, "metadata": {"implementation_progress": result.as_dict().get("metadata", {}).get("implementation_progress", {}), "leaf_contract_hash": result.metadata.get("leaf_contract_hash")}}
                for node_id, result in latest_results.items():
                    details = dict(result.error.details or {}) if result.error else {}
                    if details.get("budget_blocked"):
                        self.store.append_event(EventRecord(
                            str(uuid.uuid4()), project_id, run_id, "BUDGET_BLOCKED",
                            data={"decision_number": number, "node_id": node_id,
                                  "attempt_id": result.attempt_id,
                                  "message": result.error.message if result.error else "budget blocked"}))
                        return ProjectLoopResult(
                            'BLOCKED', number, agent_calls, worker_calls, tree, summary,
                            'BUDGET_BLOCKED: provider budget denied; no further planning or worker calls', execution_mode=self.execution_mode.value)
                if self.progress_controller is not None:
                    for node_id, result in latest_results.items():
                        node = tree.by_id.get(node_id)
                        deliverable = dict((result.metadata or {}).get('deliverable_check') or {})
                        observation = observe_result(
                            result, node, deliverable_verdict=deliverable.get('verdict'))
                        decision = self.progress_controller.observe(observation)
                        self.store.append_event(EventRecord(
                            str(uuid.uuid4()), project_id, run_id, "PROGRESS_OBSERVATION",
                            data={**observation.as_dict(), "decision": decision,
                                  "decision_number": number}))
                        if decision == STOP_BUDGET:
                            return ProjectLoopResult(
                                'BLOCKED', number, agent_calls, worker_calls, tree, summary,
                                'BUDGET_BLOCKED: provider budget denied; no further planning or worker calls', execution_mode=self.execution_mode.value)
                        if decision == STOP_INFRA:
                            return ProjectLoopResult(
                                'BLOCKED', number, agent_calls, worker_calls, tree, summary,
                                'INFRA_BLOCKED: provider/transport failure repeated without new evidence', execution_mode=self.execution_mode.value)
                        if decision == STOP_UNKNOWN:
                            return ProjectLoopResult(
                                'BLOCKED', number, agent_calls, worker_calls, tree, summary,
                                'EXECUTION_OUTCOME_UNKNOWN: reconcile saved receipts before further planning', execution_mode=self.execution_mode.value)
                        if decision == QUARANTINE_STRATEGY:
                            return ProjectLoopResult(
                                'BLOCKED', number, agent_calls, worker_calls, tree, summary,
                                'EXECUTION_NO_PROGRESS: same strategy/failure/artifact repeated; strategy quarantined', execution_mode=self.execution_mode.value)
                        if decision == PROJECT_REPLAN:
                            failure_details = {**failure_details,
                                               "progress_replan": observation.as_dict() | {"decision": decision}}
                # Mechanical bounded history. Full per-node results remain in
                # FileRunStore and the route's own result-reference adapter.
                execution_results = dict(list(execution_results.items())[-6:])
                empty_blocked_runs = empty_blocked_runs+1 if not summary.actual_executions and summary.blocked_nodes else 0
                self.store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,
                    'PROJECT_EXECUTION_CHECKPOINT',data={'decision_number':number,
                        'actual_executions':list(summary.actual_executions),
                        'blocked_nodes':list(summary.blocked_nodes),
                        'consecutive_empty_blocked_runs':empty_blocked_runs}))
                if empty_blocked_runs>=2:
                    return ProjectLoopResult('BLOCKED',number,agent_calls,worker_calls,tree,summary,
                        'DAG_NO_EXECUTABLE_PROGRESS: repeated runs execute no nodes because prerequisites remain blocked; inspect dependency state before redecision', execution_mode=self.execution_mode.value)
                unknown_nodes = self._unresolved_execution_nodes(project_id, run_id)
                if unknown_nodes:
                    return ProjectLoopResult('BLOCKED', number, agent_calls, worker_calls, tree, summary,
                        'EXECUTION_OUTCOME_UNKNOWN: reconcile saved receipts before further planning; '
                        + ','.join(unknown_nodes), execution_mode=self.execution_mode.value)
        return ProjectLoopResult("BLOCKED", number, agent_calls, worker_calls, tree, summary, "agent decision limit reached", execution_mode=self.execution_mode.value)

    def _unresolved_execution_nodes(self, project_id, run_id):
        # Current canonical receipts, not stale checkpoint summaries, decide
        # whether explicit effect reconciliation has released the barrier.
        root = self.store.run_dir(project_id, run_id)
        if not (root / 'run_state.json').exists():
            return []
        state = self.store.load_run(project_id, run_id)
        unresolved = []
        for node_id, record in state.nodes.items():
            if record.latest_result_ref:
                receipt = self.store.load_result(project_id, run_id, node_id)
                if receipt.error and receipt.error.details.get('outcome_unknown'):
                    unresolved.append(node_id)
        return sorted(unresolved)

    def _refresh_milestone_subjects(self, plan):
        paths=set()
        compiled_paths={a['path'] for g in plan['goals']
                        for a in g.get('milestone_contract',{}).get('design',{}).get('artifacts',[])}
        for goal in plan['goals']:
            contract=goal.get('milestone_contract')
            if not contract: continue
            if 'design' not in contract:
                # Additive observations may bind an existing compiled boundary
                # without declaring a second implementation or artifact layout.
                allowed=set(goal['subject_refs'])
                owners=[g for g in plan['goals'] if g.get('milestone_contract',{}).get('design')]
                scoped_paths={a['path'] for g in owners
                              if set(goal['requirement_refs']) <= set(g['requirement_refs'])
                              for a in g['milestone_contract']['design']['artifacts']}
                scoped_paths.update(p for g in owners
                                    if set(goal['requirement_refs']) <= set(g['requirement_refs'])
                                    for p in g['milestone_contract'].get('dependency_artifacts',[]))
                if not allowed or not allowed <= compiled_paths or not allowed <= scoped_paths:
                    raise ValueError('observation must bind existing compiled artifacts in its requirement scope')
            else:
                allowed={a['path'] for a in contract['design']['artifacts']}
            dependency_paths=set(contract.get('dependency_artifacts',[]))
            if not dependency_paths<=compiled_paths:
                raise ValueError('milestone dependency must bind an existing compiled artifact')
            allowed.update(dependency_paths)
            if not set(goal['subject_refs']) <= allowed:
                raise ValueError('milestone subject must bind a compiled artifact')
            # The planner must see materialization of all declared deliverables,
            # including tests and documentation, before requesting acceptance.
            paths.update(allowed)
        if not paths: return
        if not callable(self.subject_snapshot):
            raise ValueError('milestone requires a registered current-object observer')
        observed=dict(self.subject_snapshot(sorted(paths)))
        if set(observed)!=paths or any(v is not None and (not isinstance(v,str) or not v) for v in observed.values()):
            raise ValueError('milestone observer did not bind exact compiled objects')
        # Only canonical subject metadata is needed here. Verdict consumers
        # still call view(), and record() still authenticates each new witness.
        # Reload validates immutable requirements/checker bindings; no cache or
        # acceptance certificate is trusted merely because metadata was read.
        self.acceptance._reload()
        current_subjects=dict(self.acceptance.data['subjects'])
        subjects={**current_subjects,**observed}
        if subjects!=current_subjects:
            self.acceptance.bind_subjects(subjects)

    def _record_progress(self, project_id, run_id, number, tree, previous):
        """Derived observation in existing events, never another state authority."""
        from cgkn.state.task_feedback import digest
        view = self.acceptance.view() if self.acceptance else {}
        goals = {g['id']:g for g in view.get('goals', ())}
        verified = sorted(k for k,g in goals.items() if g.get('verdict') == 'VERIFIED')
        conditions = {k:digest(g['acceptance']) for k,g in goals.items()}
        failures = sum(g.get('verdict') == 'FAILED' for g in goals.values())
        old_attempts = set(previous.get('observed_attempts', ()))
        attempts = set(old_attempts)
        deltas, measurements, unavailable = {}, {}, []
        for node in tree.nodes:
            if not node.executable: continue
            try:
                result = self.store.load_result(project_id, run_id, node.id)
            except StateStoreError: continue
            attempt = node.id + '/' + result.attempt_id
            if attempt in attempts: continue
            attempts.add(attempt)
            proof = result.metadata.get('deliverable_check', {})
            contract = node.config['leaf_contract']
            try:
                checker = self.runner.registry.resolve(self.runner.deliverable_checkers[contract['checker_ref']], 'deliverable.check@1')
                current = checker.snapshot(contract)
            except (AttributeError,KeyError,ValueError,OSError,LookupError) as exc:
                unavailable.append({'node_id':node.id,'error_type':type(exc).__name__})
                continue
            # Only published/current objects can count as project progress;
            # failed staged candidates remain attempt evidence, not progress.
            if result.metadata.get('deliverable_verdict') == 'VERIFIED' and current == dict(proof.get('subjects',{})):
                changes = dict(proof.get('artifact_delta',{})) | dict(proof.get('non_file_delta',{}))
                if changes: deltas[attempt] = changes
                if proof.get('progress_measurements'): measurements[attempt] = dict(proof['progress_measurements'])
        newly_verified = sorted(set(verified) - set(previous.get('verified_goals', ())))
        regressions = sorted(set(previous.get('verified_goals', ())) - set(verified))
        drift = sorted(k for k,v in conditions.items() if k in previous.get('conditions',{}) and previous['conditions'][k] != v)
        progressed = bool(deltas or newly_verified)
        row = {'kind':'ProgressReceipt','decision_number':number,
               'engineering_change_observed':bool(deltas),'goal_result_changed':bool(newly_verified or regressions),
               'subjective_quality':'NOT_ESTABLISHED_BY_FILE_CHANGES',
               'artifact_delta':deltas,'newly_verified_acceptance':newly_verified,
               'failure_count':failures,'failure_count_delta':failures-previous.get('failure_count',failures),
               'regressions':regressions,'regression_count':len(regressions),'contract_drift':drift,
               'test_delta':measurements or 'UNKNOWN_NOT_MEASURED',
               'remaining_obligations':[k for k,v in view.get('obligations',{}).items() if v['verdict'] != 'VERIFIED'],
               'verified_goals':verified,'conditions':conditions,'observed_attempts':sorted(attempts),
               'unavailable_observations':unavailable,'progress_observed':progressed,
               'consecutive_no_delta':0 if progressed else previous.get('consecutive_no_delta',0)+1,
               'authority':'current independent checker observations and GoalAcceptance; not a completion verdict'}
        event_id = 'progress.' + uuid.uuid4().hex
        from cgkn.component.spec import _thaw
        row = _thaw(row)
        self.store.append_event(EventRecord(event_id,project_id,run_id,'PROJECT_PROGRESS',data=row))
        visible = {k:v for k,v in row.items() if k not in {'conditions','observed_attempts','artifact_delta','test_delta'}}
        visible.update(raw_event_ref=event_id, artifact_delta_attempts=list(deltas),
                       instruction='Continue while evidence changes. With repeated no-delta, inspect, split, change bounded strategy or continue another branch. Never infer completion or escalate solely from elapsed rounds.')
        return row, visible

    def _bind_intent(self, project_id, run_id, goal, proposed, constraints):
        path = self.store.run_dir(project_id, run_id) / 'minimal_project_intent.json'
        if proposed is None and path.exists():
            proposed = json.loads(path.read_text(encoding='utf-8'))
        if proposed is None:
            if getattr(self.composer, 'planner_mode', None) == 'MILESTONE_MODE':
                raise ValueError('MILESTONE_MODE requires minimal project intent')
            return {}
        fields = {'overall_goal','user_visible_outcomes','constraints','forbidden_operations',
                  'delivery_expectations','major_acceptance_categories'}
        if not isinstance(proposed, dict) or set(proposed) != fields or proposed['overall_goal'] != goal:
            raise ValueError('minimal intent fields or goal mismatch')
        for key in fields - {'overall_goal'}:
            if not isinstance(proposed[key], list) or not all(isinstance(v,str) and v.strip() for v in proposed[key]):
                raise ValueError('minimal intent requires explicit text lists: ' + key)
        if any(not proposed[k] for k in ('user_visible_outcomes','delivery_expectations','major_acceptance_categories')):
            raise ValueError('minimal intent lacks outcomes, delivery or major acceptance')
        if constraints and constraints != tuple(proposed['constraints']):
            raise ValueError('project constraints differ from frozen minimal intent')
        self.store.immutable_json(path, proposed)
        return json.loads(json.dumps(proposed))

    def _reconcile_completed_checks(self, project_id, run_id):
        """Replay only the acceptance projection of committed checker receipts.

        Process loss after DAG completion can precede ProjectSession's record
        call. The existing acceptance authority validates current objects and
        provenance; this never dispatches an executor or promotes a model claim.
        """
        if not self.acceptance or not (self.store.run_dir(project_id, run_id)/'run_state.json').exists():
            return
        from cgkn.state.acceptance import identity
        self.acceptance._reload()  # metadata only; record() authenticates every recovered witness
        goals = {g['id']: g for g in self.acceptance.data['plans'][-1]['goals']}
        recorded = {(r['goal_id'], r['receipt_hash']) for r in self.acceptance.data['checks']}
        state = self.store.load_run(project_id, run_id)
        for node_id, node in sorted(state.nodes.items()):
            if node.status not in {'SUCCEEDED', 'FAILED'} or not node.attempts:
                continue
            result = self.store.load_result(project_id, run_id, node_id)
            if result.attempt_id != node.attempts[-1] or result.status.value != node.status:
                raise StateStoreError('RECOVERY_CHECK_RECEIPT_STATE_MISMATCH: '+node_id)
            check = result.as_dict()['outputs'].get('goal_check', {})
            goal_id = check.get('goal_id')
            if goal_id not in goals or result.executor_ref != self.acceptance.checkers[goals[goal_id]['checker']]:
                continue
            receipt_hash = identity(result.as_dict())
            if (goal_id, receipt_hash) in recorded:
                continue
            expected = {p:self.acceptance.data['subjects'].get(p) for p in goals[goal_id]['subject_refs']}
            if check.get('subjects') != expected or check.get('condition_hash') != identity(goals[goal_id]['acceptance']):
                continue  # historical/stale evidence stays immutable, never current
            row = self.acceptance.record(goal_id, result, executor_ref=result.executor_ref)
            recorded.add((goal_id, receipt_hash))
            self.store.append_event(EventRecord(str(uuid.uuid4()), project_id, run_id,
                'ACCEPTANCE_CHECK_RECOVERED', node_id=node_id, attempt_id=result.attempt_id,
                data={'goal_id':goal_id,'receipt_hash':receipt_hash,'verdict':row['verdict'],
                      'authority':'GoalAcceptance.record','executor_replayed':False}))

    def _recover_interrupted(self, project_id, run_id, tree, summary):
        from cgkn.state.store import StateStoreError
        try: state = self.store.load_run(project_id,run_id)
        except StateStoreError: return tree,summary
        definition=self.store.run_dir(project_id,run_id)/'capability_tree.json'
        recovered=CapabilityTree.from_dict(json.loads(definition.read_text(encoding='utf-8')))
        if recovered.goal != tree.goal:
            raise RuntimeError('RECOVERY_GOAL_MISMATCH: committed graph cannot change the project goal')
        if compile_tree(recovered, historical_read_only=True).as_dict()!=state.execution_dag:
            raise RuntimeError('RECOVERY_GRAPH_MISMATCH: reconcile committed graph before execution')
        state = self.runner.recover_interrupted(project_id, run_id, recovered)
        recovered_summary=RunSummary(project_id,run_id,'BLOCKED',len(state.nodes),(),
            tuple(n for n,r in state.nodes.items() if r.status=='SUCCEEDED'),
            tuple(n for n,r in state.nodes.items() if r.status in {'FAILED','TIMED_OUT'}),
            tuple(n for n,r in state.nodes.items() if r.status=='BLOCKED'),0,
            execution_mode=self.execution_mode.value)
        self.store.append_event(EventRecord(str(uuid.uuid4()),project_id,run_id,'AGENT_CHECKPOINT_RECOVERED',
            data={'unknown_nodes':list(recovered_summary.blocked_nodes),'automatic_replay':False}))
        return recovered,recovered_summary

    def _current_completion(self, project_id, run_id, tree):
        """Optional idle-service shortcut through existing independent acceptance.

        A task success or a Critical PASS alone is never sufficient. Re-read
        current subjects and preserve the same parent projection used by finish.
        """
        if not self.acceptance or not self.acceptance.view()['complete']:
            return False
        from cgkn.execution.deliverables import parent_projection
        receipts = {}
        for leaf in tree.nodes:
            if not leaf.executable:
                continue
            try:
                receipt = self.store.load_result(project_id, run_id, leaf.id)
                contract = leaf.config['leaf_contract']
                checker = self.runner.registry.resolve(self.runner.deliverable_checkers[contract['checker_ref']], 'deliverable.check@1')
                if checker.snapshot(contract) == dict(receipt.metadata.get('deliverable_check', {}).get('subjects', {})):
                    receipts[leaf.id] = receipt
            except StateStoreError:
                return False
        own = {g['id']: g['verdict'] for g in self.acceptance.view()['goals']}
        return all(v['verdict'] == 'VERIFIED' for v in parent_projection(tree, receipts, own).values())

    def _failure_details(self, project_id: str, run_id: str, summary: RunSummary) -> dict[str, Any]:
        details: dict[str, Any] = {}
        for node_id in (*summary.failed_nodes, *summary.blocked_nodes):
            result = self.store.load_result(project_id, run_id, node_id)
            details[node_id] = {"status": result.status.value, "error": result.error.as_dict() if result.error else None, "outputs": result.as_dict()['outputs']}
        return details


# Compatibility names resolve to the exact same coordinator and run method.
AgentProjectLoop = ProjectSession
