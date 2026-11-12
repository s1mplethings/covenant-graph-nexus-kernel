from __future__ import annotations

from cgkn.telemetry.lean import observed

import uuid
import json
from dataclasses import dataclass, replace
from typing import Any, Mapping

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, TaskContext
from cgkn.execution.contracts import utc_now
from cgkn.executors import ExecutorRegistry, ExecutorResolutionError
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.orchestration.execution_dag import ExecutionDAG
from cgkn.orchestration.invalidation import downstream_closure
from cgkn.state import EventRecord, FileRunStore, NodeExecutionRecord, ProjectState, RunState, StateStoreError


from cgkn.orchestration.tree_edits import GraphEditRejected


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
    execution_mode: str = 'LEGACY'  # Compatibility for old persisted summaries only.

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__ | {key: list(value) for key, value in self.__dict__.items() if isinstance(value, tuple)}


class DAGRunner:
    def __init__(self, registry: ExecutorRegistry, store: FileRunStore, *, max_parallel: int = 1, knowledge=None, resource_limits=None, reconciliation_executors=(), deliverable_checkers=None, execution_mode='GOVERNED', critical_check_registry=None):
        from veriarbor.execution_authority import ExecutionMode
        self.execution_mode = ExecutionMode(execution_mode)
        self.critical_check_registry = critical_check_registry
        if self.execution_mode == 'IMPORTED_UNMANAGED':
            raise ValueError('use authority.import_unmanaged for audit-only artifacts')
        if self.execution_mode == 'LEGACY':
            from veriarbor.governance import require_legacy
            require_legacy()
            import warnings
            warnings.warn('LEGACY DAGRunner: no governed execution lineage', RuntimeWarning)
        if isinstance(max_parallel,bool) or not isinstance(max_parallel,int) or not 1<=max_parallel<=32:
            raise ValueError('parallelism must be an integer between 1 and 32')
        self.registry = registry
        self.store = store
        self.max_parallel = max_parallel
        self.knowledge = knowledge
        self.resource_limits=dict(resource_limits or {})
        if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in self.resource_limits.values()):
            raise ValueError('resource capacities must be positive integers')
        self.reconciliation_executors=frozenset(reconciliation_executors)
        self.deliverable_checkers = dict(deliverable_checkers or {})

    @observed("dag", lambda a: a["self"].store.run_dir(a["project_id"], a["run_id"]), share_parent=True)
    def run(self, *, project_id, run_id, **kwargs):
        with self.store.exclusive_run(project_id, run_id):
            return self._run(project_id=project_id, run_id=run_id, **kwargs)

    def _run(self, *, project_id: str, run_id: str, tree: CapabilityTree, dag: ExecutionDAG, resume: bool = False, retry_node: str | None = None, constraints: tuple[str, ...] = (), accept_edits: bool = False, cancel=None) -> RunSummary:
        if self.execution_mode == 'GOVERNED':
            self._authority(project_id, run_id).validate_tree(tree)
        else:
            from veriarbor.governance import require_legacy
            self._event(project_id, run_id, 'LEGACY_EXECUTION_WARNING', data=require_legacy(project_id=project_id,run_id=run_id))
        dag.topological_order()
        for node in dag.nodes:
            self.store._validate_segment(node.id)
            self._compatible(self._effective_config(node), self._effective_config(node))
            claims=node.config.get('capacity_claims',{})
            if not isinstance(claims,Mapping) or any(k not in self.resource_limits or isinstance(v,bool) or not isinstance(v,int) or v<1 or v>self.resource_limits[k] for k,v in claims.items()):
                raise ValueError('capacity claim exceeds configured resource limit')
        from cgkn.orchestration.execution_dag import compile_tree
        if dag.as_dict() != compile_tree(tree).as_dict():
            raise ValueError("execution DAG does not match executable CapabilityTree nodes")
        for node in dag.nodes:
            c = node.config['leaf_contract']
            checker_ref = self.deliverable_checkers.get(c['checker_ref'])
            if not checker_ref or checker_ref == node.config['executor_ref']:
                raise GraphEditRejected('independent registered deliverable checker required: ' + node.id)
            checker = self.registry.resolve(checker_ref, 'deliverable.check@1')
            checker.validate_contract(c)
        try:
            state = self.store.load_run(project_id, run_id) if resume or retry_node else self._new_state(project_id, run_id, dag)
        except StateStoreError:
            if resume or retry_node:
                raise
            state = self._new_state(project_id, run_id, dag)
        if (state.project_id, state.run_id) != (project_id, run_id):
            raise ValueError("persisted run identity does not match requested run")
        if retry_node:
            for affected in downstream_closure(dag, {retry_node}):
                record = state.nodes.get(affected)
                if record and record.latest_result_ref:
                    prior = self.store.load_result(project_id, run_id, affected)
                    if prior.error and prior.error.details.get('outcome_unknown'):
                        raise GraphEditRejected('UNRESOLVED_OUTCOME: reconcile original attempt before retrying ' + affected)
        if state.execution_dag:
            original = ExecutionDAG.from_dict(state.execution_dag)
            for old in original.nodes:
                record = state.nodes[old.id]
                if not record.latest_result_ref:
                    continue
                receipt = self.store.load_result(project_id, run_id, old.id)
                if not (receipt.error and receipt.error.details.get('outcome_unknown')):
                    continue
                operation = old.config.get('operation_id')
                for proposed in dag.nodes:
                    if proposed.id == old.id or proposed.id in state.nodes:
                        continue
                    old_resources = self._effective_config(old).get('resources', {})
                    new_resources = self._effective_config(proposed).get('resources', {})
                    shared_write = any(old_resources[k] == 'write' or new_resources[k] == 'write'
                                       for k in old_resources.keys() & new_resources.keys())
                    same_operation = operation and proposed.config.get('operation_id') == operation
                    uncertain_alias = not operation and proposed.capability_ref == old.capability_ref
                    if same_operation or shared_write or uncertain_alias:
                        raise GraphEditRejected('UNRESOLVED_OPERATION: reconcile unknown effect before replacement node ' + proposed.id)
        # Validate all reuse against the last committed graph before mutating
        # graph/state or invalidating retries. Historical version chains remain
        # evidence even when a descendant is about to receive a new attempt.
        self._bind_graph(state, dag, accept_edits=accept_edits, retry_node=retry_node, validate_only=True)
        previous_dag = ExecutionDAG.from_dict(state.execution_dag) if state.execution_dag is not None else dag
        retry_scope = set(downstream_closure(dag, {retry_node})) if retry_node else set()
        reuse_proofs = {}
        stale_measurements = {}
        for node_id, record in state.nodes.items():
            if record.status != 'SUCCEEDED' or node_id in retry_scope or node_id not in dag.by_id:
                continue
            receipt = self.store.load_result(project_id, run_id, node_id)
            if receipt.metadata.get('deliverable_verdict') != 'VERIFIED':
                raise GraphEditRejected('LEGACY_UNQUALIFIED_DELIVERABLE: explicit requalification required ' + node_id)
            contract = previous_dag.by_id[node_id].config['leaf_contract']
            checker = self.registry.resolve(self.deliverable_checkers[contract['checker_ref']], 'deliverable.check@1')
            live = checker.snapshot(contract)
            if live != dict(receipt.metadata.get('deliverable_check', {}).get('subjects', {})):
                proof = self._verified_successor_chain(state, previous_dag, node_id, receipt, live)
                if not proof:
                    # A stale terminal observer is historical evidence, not
                    # reusable current execution. Retire it without dispatching
                    # another checker or blocking a bounded source repair.
                    # Producer/consumer nodes still require their version proof.
                    measurement_kinds = {'TEST', 'INSPECTION'}
                    if (contract['task_kind'] in measurement_kinds
                            and set(downstream_closure(dag, {node_id})) == {node_id}):
                        stale_measurements[node_id] = {'previous_subjects': dict(receipt.metadata['deliverable_check']['subjects']),
                            'current_subjects': live, 'retry_authority': retry_node,
                            'disposition': 'BLOCKED_AWAITING_EXPLICIT_RETRY'}
                        continue
                    raise GraphEditRejected('OBJECT_VERSION_MISMATCH: explicit affected-subgraph retry required ' + node_id)
                reuse_proofs[node_id] = proof
        self._bind_graph(state, dag, accept_edits=accept_edits, retry_node=retry_node)
        for node_id, proof in stale_measurements.items():
            state.nodes[node_id].status = 'BLOCKED'
            state.nodes[node_id].reused = False
            self._event(project_id, run_id, 'STALE_MEASUREMENT_INVALIDATED', node_id=node_id, data=proof)
        if stale_measurements:
            self.store.save_run(state)
        for node_id, proof in reuse_proofs.items():
            self._event(project_id, run_id, 'HISTORICAL_WRITER_VERSION_REUSED', node_id=node_id, data=proof)
        self.store.save_project(ProjectState(project_id, tree.goal, run_id, constraints))
        self.store.save_definition(project_id, run_id, "capability_tree.json", tree.as_dict())
        self.store.save_definition(project_id, run_id, "execution_dag.json", dag.as_dict())
        if retry_node:
            self._invalidate(state, dag, retry_node)
        actual: list[str] = []
        reused: list[str] = []
        # One coordinator owns state/result commits; workers only execute bounded
        # components. Refill on FIRST_COMPLETED, never on an entire ready wave.
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        order = dag.topological_order()
        pending = []
        ready_observed = set()
        for node_id in order:
            record = state.nodes[node_id]
            if record.status == "SUCCEEDED":
                from cgkn.adapters.veriarbor.capability_adapter import validate_inputs
                scope_code = validate_inputs(self.store, project_id, run_id, node_id, execution_mode=self.execution_mode)
                if self.execution_mode == 'GOVERNED':
                    saved = self.store.load_result(project_id, run_id, node_id)
                    self._authority(project_id,run_id).validate_execution_result(saved)
                    self._validate_dependencies(project_id,run_id,dag.by_id[node_id].depends_on)
                if scope_code != 'VALID':
                    raise GraphEditRejected(scope_code + ': cached consumer binding changed ' + node_id)
                record.reused = True
                reused.append(node_id)
                self._event(project_id, run_id, "NODE_REUSED", node_id=node_id)
            elif record.status == "RUNNING":
                # Persisted intent without committed receipt is an unknown side
                # effect. Never automatically replay it on process recovery.
                self._recover_record(state, tree, node_id)
            elif record.status == "PENDING":
                pending.append(node_id)
            else:
                self._event(project_id, run_id, "NODE_AWAITING_RETRY", node_id=node_id)

        def commit(result):
            record = state.nodes[result.node_id]
            self.store.save_result(result)
            from cgkn.adapters.veriarbor.capability_adapter import record_phase
            record_phase(self.store, project_id, run_id, result.node_id, 'EXECUTED',
                         execution_status='PASS' if result.status.value == 'SUCCEEDED' else
                         'UNKNOWN' if result.status.value == 'UNKNOWN' else
                         'BLOCKED' if result.status.value == 'BLOCKED' else 'FAIL',
                         execution_mode=self.execution_mode,commit_receipt_id=result.metadata.get('node_commit_receipt_id'))
            from cgkn.state.task_feedback import TaskFeedback
            TaskFeedback(self.store, project_id, run_id).terminal(result, tree.by_id[result.node_id])
            record.attempts.append(result.attempt_id)
            record.latest_result_ref = f"node_results/{result.node_id}.json"
            record.status = result.status.value
            record.reused = False
            state.updated_at = utc_now()
            self.store.save_run(state)
            self._event(project_id, run_id, "NODE_FINISHED", node_id=result.node_id,
                        attempt_id=result.attempt_id, data={"status": result.status.value})

        self.store.save_run(state)
        inflight = {}
        cancellation_sent = set()
        with ThreadPoolExecutor(max_workers=self.max_parallel) as pool:
            while pending or inflight:
                for node_id in list(pending):
                    node = dag.by_id[node_id]
                    if cancel is not None and cancel.is_set():
                        pending.remove(node_id)
                        commit(BlockExecutionResult(project_id=project_id, run_id=run_id,
                            attempt_id=f"attempt-{len(state.nodes[node_id].attempts)+1:04d}", node_id=node_id,
                            executor_ref=str(node.config.get("executor_ref", "unresolved")), status=BlockStatus.BLOCKED,
                            error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, "CANCELLED_BEFORE_DISPATCH")))
                        continue
                    dependencies = [state.nodes[d].status for d in node.depends_on]
                    if any(status in {"PENDING", "RUNNING"} for status in dependencies):
                        continue
                    attempt_id = f"attempt-{len(state.nodes[node_id].attempts) + 1:04d}"
                    failed_dependencies = [d for d in node.depends_on if state.nodes[d].status != "SUCCEEDED"]
                    if failed_dependencies:
                        pending.remove(node_id)
                        commit(BlockExecutionResult(project_id=project_id, run_id=run_id,
                            attempt_id=attempt_id, node_id=node_id,
                            executor_ref=str(node.config.get("executor_ref", "unresolved")),
                            status=BlockStatus.BLOCKED,
                            error=ExecutionError(ExecutionErrorCode.DEPENDENCY_FAILED,
                                "dependency did not succeed", {"dependencies": failed_dependencies})))
                        continue
                    if node_id not in ready_observed:
                        self._event(project_id, run_id, 'NODE_READY', node_id=node_id, attempt_id=attempt_id)
                        ready_observed.add(node_id)
                    if len(inflight) >= self.max_parallel:
                        continue
                    if any(sum(dag.by_id[n].config.get('capacity_claims',{}).get(k,0) for n in inflight.values())+v>self.resource_limits[k]
                           for k,v in node.config.get('capacity_claims',{}).items()):
                        continue
                    from cgkn.adapters.veriarbor.dag_adapter import select_batch
                    candidates = {key: self._effective_config(dag.by_id[key]) for key in pending
                                  if all(state.nodes[d].status == 'SUCCEEDED' for d in dag.by_id[key].depends_on)
                                  and not any(sum(dag.by_id[n].config.get('capacity_claims', {}).get(k, 0)
                                                  for n in inflight.values()) + value > self.resource_limits[k]
                                              for k, value in dag.by_id[key].config.get('capacity_claims', {}).items())}
                    chosen = select_batch(candidates, slots=self.max_parallel,
                                          running=[(other, self._effective_config(dag.by_id[other])) for other in inflight.values()])
                    if node_id not in chosen:
                        continue
                    dependency_results = {d: self.store.load_result(project_id, run_id, d).outputs
                                          for d in node.depends_on}
                    from cgkn.adapters.veriarbor.capability_adapter import validate_inputs, record_phase
                    scope_code = validate_inputs(self.store, project_id, run_id, node_id, execution_mode=self.execution_mode)
                    if self.execution_mode == 'GOVERNED':
                        self._validate_dependencies(project_id,run_id,node.depends_on)
                    if scope_code != 'VALID':
                        pending.remove(node_id)
                        commit(BlockExecutionResult(project_id=project_id, run_id=run_id,
                            attempt_id=attempt_id, node_id=node_id,
                            executor_ref=str(node.config.get('executor_ref', 'unresolved')),
                            status=BlockStatus.BLOCKED,
                            error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, scope_code)))
                        continue
                    affected = set(downstream_closure(dag, {node_id}))
                    for key in tuple(affected):
                        parent = tree.by_id[key].parent_id
                        while parent:
                            affected.add(parent)
                            parent = tree.by_id[parent].parent_id
                    record_phase(self.store, project_id, run_id, node_id, 'EXECUTING', invalidate_nodes=affected)
                    # Durable admission precedes dispatch. Recovery sees RUNNING
                    # even if the process dies before NODE_STARTED is appended.
                    state.nodes[node_id].status = "RUNNING"
                    self.store.save_run(state)
                    self._event(project_id, run_id, "NODE_DISPATCHED", node_id=node_id,
                                attempt_id=attempt_id)
                    pending.remove(node_id)
                    actual.append(node_id)
                    # ThreadPoolExecutor does not propagate ContextVars. Each
                    # dispatch needs its own context so audit/observation scope
                    # survives without sharing mutable Context bindings across
                    # concurrently executing nodes.
                    from contextvars import copy_context
                    execution_config = dict(node.config)
                    if retry_node and node_id in retry_scope and node_id != retry_node:
                        root_config = dag.by_id[retry_node].config
                        reason = root_config.get('verified_artifact_change_reason')
                        if reason:
                            from cgkn.state.task_feedback import digest
                            authorization = {'root_node_id':retry_node,'affected_node_id':node_id,
                                'root_leaf_contract_hash':digest(root_config['leaf_contract']),
                                'reason':reason,'authority':'explicit Agent affected-subgraph reexecution'}
                            execution_config.setdefault('verified_artifact_change_reason',
                                'Dependent reexecution from '+retry_node+': '+reason)
                            execution_config['inherited_change_authorization'] = authorization
                    future = pool.submit(copy_context().run, self._execute, project_id, run_id, attempt_id,
                        node_id, node.capability_ref, execution_config, dependency_results, constraints)
                    inflight[future] = node_id
                if inflight:
                    if cancel is not None and cancel.is_set():
                        for node_id in inflight.values():
                            if node_id in cancellation_sent: continue
                            cancellation_sent.add(node_id)
                            node = dag.by_id[node_id]
                            executor = self.registry.resolve(str(node.config.get("executor_ref", "")), node.capability_ref)
                            cancel_action = getattr(executor, "cancel", None)
                            if cancel_action: cancel_action(project_id, run_id, node_id)
                            self._event(project_id, run_id, "CANCEL_REQUESTED", node_id=node_id,
                                        data={"executor_cancel_supported": bool(cancel_action), "remote_stop_confirmed": False})
                    done, _ = wait(inflight, return_when=FIRST_COMPLETED, timeout=.1 if cancel is not None else None)
                    for future in sorted(done, key=lambda f: order.index(inflight[f])):
                        result = future.result()
                        if cancel is not None and cancel.is_set():
                            result = replace(result, status=BlockStatus.BLOCKED,
                                error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED, "CANCELLED_RESULT_RETAINED: effects must be reconciled before retry", {'outcome_unknown':True}),
                                metadata={**dict(result.metadata), "observed_execution_status": result.status.value})
                        commit(result)
                        del inflight[future]
                elif pending:
                    raise StateStoreError("pending DAG has no executable frontier")
        failed = tuple(node_id for node_id, value in state.nodes.items() if value.status in {BlockStatus.FAILED.value, BlockStatus.TIMED_OUT.value})
        blocked = tuple(node_id for node_id, value in state.nodes.items() if value.status == BlockStatus.BLOCKED.value)
        state.status = "SUCCEEDED" if not failed and not blocked and all(value.status == BlockStatus.SUCCEEDED.value for value in state.nodes.values()) else "FAILED"
        state.updated_at = utc_now()
        self.store.save_run(state)
        summary = RunSummary(project_id, run_id, state.status, len(state.nodes), tuple(actual), tuple(reused), failed, blocked, sum(max(0, len(value.attempts) - 1) for value in state.nodes.values()), execution_mode=self.execution_mode.value)
        self.store.save_run_summary(project_id, run_id, summary.as_dict())
        self._event(project_id, run_id, "RUN_FINISHED", data=summary.as_dict())
        return summary

    def _recover_record(self, state, tree, node_id):
        project_id, run_id = state.project_id, state.run_id
        record = state.nodes[node_id]
        attempt_id = f"attempt-{len(record.attempts) + 1:04d}"
        receipt = self.store.run_dir(project_id, run_id) / "attempts" / node_id / (attempt_id + ".json")
        from cgkn.state.task_feedback import TaskFeedback
        if receipt.exists():
            result = BlockExecutionResult.from_dict(json.loads(receipt.read_text(encoding="utf-8")))
            if (result.project_id, result.run_id, result.node_id, result.attempt_id) != (project_id, run_id, node_id, attempt_id):
                raise StateStoreError("recovered receipt identity mismatch")
            event = "RECEIPT_RECOVERED"
        else:
            intent=self.store.run_dir(project_id,run_id)/'publication_intents'/node_id/(attempt_id+'.json')
            disposition={'disposition':'UNKNOWN','reason':'no durable publication intent'}
            if intent.exists():
                from cgkn.execution.materialization import inspect_publication
                from cgkn.state.task_feedback import digest
                from cgkn.orchestration.capability_tree import _thaw
                c=_thaw(tree.by_id[node_id].config['leaf_contract'])
                checker=self.registry.resolve(self.deliverable_checkers[c['checker_ref']],'deliverable.check@1')
                disposition=inspect_publication(self.store,intent,expected_root=checker.root,
                    expected_staged=self.store.run_dir(project_id,run_id)/'candidates'/node_id/attempt_id,
                    contract_hash=digest(c))
                if disposition['disposition']=='COMPLETED':
                    recovered=BlockExecutionResult.from_dict(disposition['result'])
                    if (recovered.project_id,recovered.run_id,recovered.node_id,recovered.attempt_id)!=(project_id,run_id,node_id,attempt_id):
                        raise StateStoreError('publication receipt identity mismatch')
                    if checker.snapshot(c)!=dict(recovered.metadata['deliverable_check']['subjects']):
                        raise StateStoreError('publication current subject mismatch')
                    result=replace(recovered,metadata={**dict(recovered.metadata),
                        'publication_recovery':{'disposition':'COMPLETED','intent_ref':str(intent)}})
                    self.store.save_result(result)
                    self._event(project_id,run_id,'PUBLICATION_RECOVERED',node_id=node_id,attempt_id=attempt_id)
                    return self._recover_record(state,tree,node_id)
            result = BlockExecutionResult(project_id=project_id, run_id=run_id, node_id=node_id,
                attempt_id=attempt_id, executor_ref=str(tree.by_id[node_id].config.get("executor_ref", "unresolved")),
                status=BlockStatus.BLOCKED, error=ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,
                    'INTERRUPTED_'+disposition['disposition']+': inspect before explicit retry',
                    {'outcome_unknown':disposition['disposition']!='NOT_APPLIED'}),
                metadata={'publication_recovery':disposition})
            self.store.save_result(result)
            event = "INTERRUPTED_UNKNOWN"
        TaskFeedback(self.store, project_id, run_id).terminal(result, tree.by_id[node_id])
        self.store.atomic_json(self.store.run_dir(project_id, run_id) / "node_results" / (node_id + ".json"), result.as_dict())
        record.attempts.append(attempt_id)
        record.status = result.status.value
        record.latest_result_ref = f"node_results/{node_id}.json"
        self._event(project_id, run_id, event, node_id=node_id, attempt_id=attempt_id)

    def validate_graph_transition(self, *, project_id, run_id, tree, dag, retry_node=None, accept_edits=False):
        """Read-only precommit check using the existing graph-binding rules."""
        from cgkn.orchestration.execution_dag import compile_tree
        if compile_tree(tree).as_dict()!=dag.as_dict():
            raise GraphEditRejected('execution DAG does not match executable CapabilityTree nodes')
        if (self.store.run_dir(project_id,run_id)/'run_state.json').exists():
            self._bind_graph(self.store.load_run(project_id,run_id),dag,accept_edits=accept_edits,
                retry_node=retry_node,validate_only=True)

    def recover_interrupted(self, project_id, run_id, tree):
        """Reconcile only; never dispatch pending work during recovery."""
        with self.store.exclusive_run(project_id, run_id):
            state = self.store.load_run(project_id, run_id)
            starts = {(e.node_id, e.attempt_id) for e in self.store.load_events(project_id, run_id)
                      if e.event_type in {"NODE_STARTED", "NODE_DISPATCHED"}}
            for node_id, record in state.nodes.items():
                attempt = f"attempt-{len(record.attempts)+1:04d}"
                if record.status == "RUNNING" or (record.status == "PENDING" and (node_id, attempt) in starts):
                    self._recover_record(state, tree, node_id)
            self.store.save_run(state)
            return state

    def reconcile_effects(self, project_id, run_id, node_id, checker_result):
        """Explicit trusted read-only verifier resolves an unknown effect.

        Keep the interrupted receipt and append a new reconciliation receipt.
        This is execution recovery, never independent business acceptance.
        """
        from cgkn.state.task_feedback import digest,TaskFeedback
        from cgkn.state.provenance import ProvenanceGate
        if checker_result.executor_ref not in self.reconciliation_executors or checker_result.status!=BlockStatus.SUCCEEDED:
            raise ValueError('trusted successful reconciliation executor required')
        if (checker_result.project_id,checker_result.run_id)!=(project_id,run_id):
            raise ValueError('reconciliation run mismatch')
        path=self.store.run_dir(project_id,run_id)/'attempts'/checker_result.node_id/(checker_result.attempt_id+'.json')
        if json.loads(path.read_text(encoding='utf-8'))!=checker_result.as_dict():raise ValueError('uncommitted reconciliation checker')
        proof=checker_result.as_dict()['outputs'].get('effect_reconciliation',{})
        if proof.get('disposition') not in {'COMPLETED','NOT_APPLIED'} or not proof.get('evidence_refs'):
            raise ValueError('explicit effect disposition and raw evidence required')
        for ref in proof['evidence_refs']:ProvenanceGate(self.store,project_id,run_id).resolve(ref)
        with self.store.exclusive_run(project_id,run_id):
            state=self.store.load_run(project_id,run_id);record=state.nodes[node_id]
            prior=self.store.load_result(project_id,run_id,node_id)
            if not prior.error or not prior.error.details.get('outcome_unknown') or proof.get('source_receipt_hash')!=digest(prior.as_dict()):
                raise ValueError('reconciliation must identify current unknown receipt')
            result=BlockExecutionResult(project_id=project_id,run_id=run_id,node_id=node_id,
                attempt_id=f'attempt-{len(record.attempts)+1:04d}',executor_ref=checker_result.executor_ref,
                status=BlockStatus.SUCCEEDED if proof['disposition']=='COMPLETED' else BlockStatus.BLOCKED,
                outputs=proof.get('recovered_outputs',{}),
                error=None if proof['disposition']=='COMPLETED' else ExecutionError(ExecutionErrorCode.POLICY_BLOCKED,'VERIFIED_NOT_APPLIED: explicit retry permitted'),
                metadata={'reconciliation':proof,'original_attempt_id':prior.attempt_id,'checker_receipt_hash':digest(checker_result.as_dict())})
            node=CapabilityTree.from_dict(json.loads((self.store.run_dir(project_id,run_id)/'capability_tree.json').read_text(encoding='utf-8'))).by_id[node_id]
            if result.succeeded:
                # Effect reconciliation is not deliverable acceptance. Run the
                # independently registered checker without replaying the worker.
                from cgkn.execution.deliverables import verified_proof,progress_record
                from cgkn.orchestration.capability_tree import _thaw
                c=_thaw(node.config['leaf_contract'])
                checker=self.registry.resolve(self.deliverable_checkers[c['checker_ref']], 'deliverable.check@1')
                req=BlockExecutionRequest(project_id=project_id,run_id=run_id,node_id=node_id,attempt_id=result.attempt_id,
                    executor_ref=checker.descriptor.executor_ref,component_ref='deliverable.check@1',
                    task_context=TaskContext(c['leaf_goal'],{'leaf_contract':c}),
                    input_values={'before':checker.snapshot(c),'execution_receipt':result.as_dict(),
                        'execution_receipt_ref':{'path':str(path),'sha256':__import__('hashlib').sha256(path.read_bytes()).hexdigest()}})
                checked=checker.execute(req)
                valid,deliverable=verified_proof(checked,req,checker,c)
                result=replace(result,metadata={**dict(result.metadata),'leaf_contract_hash':digest(c),
                    'deliverable_verdict':'VERIFIED' if valid else 'FAILED','goal_acceptance':'NOT_EVALUATED',
                    'deliverable_check':deliverable,'checker_receipt':checked.as_dict(),
                    'implementation_progress':progress_record(c,deliverable,node_id=node_id)},
                    status=BlockStatus.SUCCEEDED if valid else BlockStatus.BLOCKED,
                    error=None if valid else ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,'RECONCILED_EFFECT_DELIVERABLE_NOT_VERIFIED'))
            if result.succeeded and self.execution_mode=='GOVERNED':
                # Reconciliation never dispatches the original executor. Bind the
                # independently observed output through the same Host commit owner
                # with no effect or spending authority, retaining the UNKNOWN attempt.
                from veriarbor.capability import CapabilityContract
                from veriarbor.execution_authority import NodeExecutionResult
                from .node_authority import file_hash
                authority=self._authority(project_id,run_id)
                current=authority.committed_tree()
                admitted=authority._find('PROPOSAL_ADMITTED','admission_id',current['admission_id'])
                cid=node.config.get('capability_contract_id',node.capability_ref)
                previous=[e['data']['permit'] for e in authority.events()
                          if e['event_type']=='NODE_PERMIT_ISSUED' and e['node_id']==node_id]
                if previous and authority._permit(previous[-1]['permit_id']).status=='ACTIVE':
                    authority.revoke_permit(previous[-1]['permit_id'],'INDEPENDENT_EFFECT_RECONCILIATION')
                permit=authority.issue_permit(node_id=node_id,contract=CapabilityContract(**admitted['contracts'][cid]),
                    allowed_effects=(),budget_scope={},executor_identity=node.config['executor_ref'],
                    input_bindings={'reconciliation':proof,'checker_receipt_hash':digest(checker_result.as_dict())})
                authority.begin_node_execution(permit.permit_id)
                packet=authority.staging_dir(permit.permit_id)/'outputs.json'
                self.store.immutable_json(packet,result.as_dict()['outputs'])
                authority.submit_node_result(NodeExecutionResult(permit.permit_id,{str(packet):file_hash(packet)},
                    (),(),tuple(proof['evidence_refs']),{},{}))
                receipt=authority.commit_node_execution(permit.permit_id)
                result=replace(result,executor_ref=node.config['executor_ref'],metadata={**dict(result.metadata),
                    'reconciliation_executor_ref':checker_result.executor_ref,'execution_mode':'GOVERNED',
                    'node_commit_receipt_id':receipt.receipt_id,'node_output_packet':str(packet)})
            record.status='RUNNING'
            self.store.save_run(state)
            self.store.save_result(result)
            TaskFeedback(self.store,project_id,run_id).terminal(result,node)
            record.attempts.append(result.attempt_id);record.status=result.status.value;record.latest_result_ref=f'node_results/{node_id}.json'
            self.store.save_run(state)
            self._event(project_id,run_id,'EFFECT_RECONCILED',node_id=node_id,attempt_id=result.attempt_id,data={'disposition':proof['disposition'],'original_receipt_hash':proof['source_receipt_hash']})
            return result

    def _effective_config(self, node):
        config = dict(node.config)
        try:
            executor = self.registry.resolve(str(config.get("executor_ref", "")), node.capability_ref)
        except ExecutorResolutionError:
            return config
        enforced = getattr(executor, "resource_claims", {})
        if hasattr(executor,'actions') and config.get('leaf_contract'):
            c=config['leaf_contract']
            enforced={'workspace:'+str(executor.actions._path(name)):'write' for name in c['target_scope']}
            # Exact writers share a read claim on the container; extensible roots
            # acquire it exclusively so new child paths cannot race exact writers.
            enforced['workspace:'+str(executor.actions.root)]='write' if c.get('component_roots') else 'read'
            for name in c.get('read_scope',()):enforced.setdefault('workspace:'+str(executor.actions._path(name)),'read')
        if enforced:
            config["resources"] = {**dict(config.get("resources", {})), **dict(enforced)}
        return config

    @staticmethod
    def _compatible(left, right) -> bool:
        from cgkn.adapters.veriarbor.dag_adapter import compatible
        return compatible(left, right)


    def _new_state(self, project_id: str, run_id: str, dag: ExecutionDAG) -> RunState:
        if (self.store.run_dir(project_id, run_id) / "run_state.json").exists():
            raise StateStoreError("existing run requires explicit resume; refusing to overwrite history")
        state = RunState(project_id, run_id, nodes={node.id: NodeExecutionRecord(node.id) for node in dag.nodes}, execution_dag=dag.as_dict(), graph_revision=1)
        self.store.save_run(state)
        self._event(project_id, run_id, "RUN_CREATED")
        return state

    def _bind_graph(self, state: RunState, dag: ExecutionDAG, *, accept_edits: bool, retry_node: str | None, validate_only: bool = False) -> None:
        """Commit bounded Agent edits; ordinary resume still requires the same DAG.

        State and its DAG are one atomic JSON commit. Definition files are readable
        mirrors, not a second state authority. Legacy runs use their saved DAG.
        Removing executed identities and silently reusing changed successes are
        forbidden. An explicit retry retains the existing invalidation contract.
        """
        if state.execution_dag is None:
            if set(state.nodes) != set(dag.by_id):
                raise ValueError("persisted run state does not match DAG")
            path = self.store.run_dir(state.project_id, state.run_id) / "execution_dag.json"
            try:
                previous = ExecutionDAG.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise StateStoreError("persisted run has no valid bound DAG") from exc
        else:
            previous = ExecutionDAG.from_dict(state.execution_dag)
        if set(state.nodes) != set(previous.by_id):
            raise ValueError("persisted run state does not match DAG")
        if previous.goal != dag.goal:
            raise ValueError("persisted run state does not match DAG: goal/removal")
        old = {n['id']: n for n in previous.as_dict()['nodes']}
        new = {n['id']: n for n in dag.as_dict()['nodes']}
        removed=set(old)-set(new)
        if removed:
            if not accept_edits:raise GraphEditRejected('goal/removal: explicit archival edit required')
            self._authority(state.project_id,state.run_id).validate_archive_transition(state,previous,dag)
        changed = {key for key in set(old)&set(new) if old[key] != new[key]}
        added = set(new) - set(old)
        if (changed or added or removed) and not accept_edits:
            raise ValueError("persisted run state does not match DAG: explicit edit commit required")
        retry_scope = set(downstream_closure(dag, {retry_node})) if retry_node else set()
        affected = set(downstream_closure(dag, changed))
        if any(state.nodes[key].status == BlockStatus.SUCCEEDED.value and key not in retry_scope for key in affected & set(old)):
            raise GraphEditRejected("cannot edit/reuse succeeded nodes without explicit affected-subgraph retry; retry the earliest changed succeeded node, not only its failed descendant")
        if validate_only:
            return
        if not (changed or added or removed) and state.execution_dag is not None:
            return
        # No mutation above this line: illegal transitions preserve saved state.
        for key in removed:
            state.archived_nodes.setdefault(key,[]).append({'node':old[key],
                'execution':state.nodes[key].as_dict(),'graph_revision':state.graph_revision,
                'evidence_applicability':'HISTORICAL_ONLY'})
            del state.nodes[key]
        for key in added:
            history=state.archived_nodes.get(key,[])
            attempts=list(history[-1]['execution']['attempts']) if history else []
            state.nodes[key] = NodeExecutionRecord(key,attempts=attempts)

        for key in affected:
            state.nodes[key].status = "PENDING"
            state.nodes[key].latest_result_ref = None
            state.nodes[key].reused = False
        state.execution_dag = dag.as_dict()
        state.graph_revision += 1
        state.status = "PENDING"
        state.updated_at = utc_now()
        self.store.save_run(state)
        self._event(state.project_id, state.run_id, "GRAPH_COMMITTED", data={"revision": state.graph_revision, "added": sorted(added), "archived": sorted(removed), "changed": sorted(changed), "invalidated": sorted(affected)})

    def _verified_successor_chain(self, state, dag, node_id, receipt, live):
        """Historical writer identity follows immutable committed versions.

        Use canonical event order, including earlier successful attempts of a
        retried descendant. Never treat this as current business acceptance.
        """
        from pathlib import Path
        from cgkn.orchestration.leaf_contract import WRITING
        from cgkn.execution.materialization import file_hash
        from cgkn.state.task_feedback import digest
        contract = dag.by_id[node_id].config['leaf_contract']
        if contract['task_kind'] not in WRITING:
            return False
        versions = dict(receipt.metadata.get('deliverable_check', {}).get('subjects', {}))
        if not versions or set(versions) != set(live):
            return False
        folder = self.store.run_dir(state.project_id, state.run_id)

        def publication(owner, result):
            self.store._validate_segment(result.attempt_id)
            if self.execution_mode == 'GOVERNED':
                self._authority(state.project_id, state.run_id)._validate_historical_execution_result(result)
            row = result.as_dict()
            if (result.project_id, result.run_id, result.node_id) != (state.project_id, state.run_id, owner):
                raise ValueError('publication result identity mismatch')
            if json.loads((folder/'attempts'/owner/(result.attempt_id+'.json')).read_text(encoding='utf-8')) != row:
                raise ValueError('immutable attempt mismatch')
            path = folder/'publication_intents'/owner/(result.attempt_id+'.json')
            journal = json.loads(path.read_text(encoding='utf-8'))
            if journal['result'] != row or journal['after'] != dict(result.metadata['deliverable_check']['subjects']):
                raise ValueError('publication/result mismatch')
            after, before = journal['after'], journal['before']
            if set(before) != set(after):
                raise ValueError('publication scope mismatch')
            staged = (folder/'candidates'/owner/result.attempt_id).resolve()
            if Path(journal['staged']).resolve() != staged or any(
                    staged not in (staged/name).resolve().parents or file_hash(staged/name) != value
                    for name,value in after.items()):
                raise ValueError('publication candidate mismatch')
            ref = result.metadata['raw_execution_receipt_ref']
            raw = (self.store.root/ref['path']).resolve()
            if self.store.root not in raw.parents or file_hash(raw) != ref['sha256']:
                raise ValueError('raw execution evidence mismatch')
            return journal, {'node_id':owner,'attempt_id':result.attempt_id,
                'publication_ref':str(path),'sha256':file_hash(path)}

        try:
            original, _ = publication(node_id, receipt)
            if original['after'] != versions or receipt.metadata.get('leaf_contract_hash') != digest(dict(contract)):
                return False
            order = {(event.node_id,event.attempt_id):index for index,event in enumerate(
                self.store.load_events(state.project_id,state.run_id))
                if event.event_type == 'NODE_FINISHED' and event.data.get('status') == 'SUCCEEDED'}
            origin = order[(node_id,receipt.attempt_id)]
            # Sibling writes may be explicitly authorized by the same Agent
            # root repair. Their committed CAS journals, not sibling order or
            # timestamps alone, establish the object-version handoff.
            def repair_authority(owner, result):
                auth = result.metadata.get('inherited_change_authorization', {})
                root = auth.get('root_node_id')
                if (auth.get('authority') != 'explicit Agent affected-subgraph reexecution'
                        or auth.get('affected_node_id') != owner or not auth.get('reason')
                        or root not in dag.by_id or root == owner
                        or owner not in downstream_closure(dag, {root})
                        or auth.get('root_leaf_contract_hash') != digest(dict(dag.by_id[root].config['leaf_contract']))
                        or auth.get('reason') != dag.by_id[root].config.get('verified_artifact_change_reason')):
                    return None
                parent = self.store.load_result(state.project_id, state.run_id, root)
                if (not parent.succeeded or parent.metadata.get('deliverable_verdict') != 'VERIFIED'
                        or parent.metadata.get('leaf_contract_hash') != auth['root_leaf_contract_hash']
                        or order[(root,parent.attempt_id)] >= order[(owner,result.attempt_id)]):
                    return None
                publication(root, parent)
                return (root, parent.attempt_id, auth['root_leaf_contract_hash'], auth['reason'])

            original_authority = repair_authority(node_id, receipt)
            descendants = set(downstream_closure(dag, {node_id})) - {node_id}
            candidates = (set(dag.by_id) - {node_id}) if original_authority else descendants
            transitions = []
            for successor in candidates:
                leaf = dag.by_id[successor].config['leaf_contract']
                from cgkn.execution.file_actions import writable_path
                if leaf['task_kind'] not in WRITING or not any(writable_path(leaf,name) for name in versions):
                    continue
                record = state.nodes[successor]
                if record.status == 'SUCCEEDED':
                    latest = self.store.load_result(state.project_id,state.run_id,successor)
                    if latest.metadata.get('leaf_contract_hash') != digest(dict(leaf)):
                        return False
                for attempt in record.attempts:
                    self.store._validate_segment(attempt)
                    result = BlockExecutionResult.from_dict(json.loads(
                        (folder/'attempts'/successor/(attempt+'.json')).read_text(encoding='utf-8')))
                    if not result.succeeded or result.metadata.get('deliverable_verdict') != 'VERIFIED':
                        continue
                    position = order[(successor,attempt)]
                    if position <= origin:
                        continue
                    if successor not in descendants and repair_authority(successor, result) != original_authority:
                        continue
                    journal, ref = publication(successor,result)
                    if journal.get('root') != original.get('root'):
                        return False
                    transitions.append((position,journal,ref))
            chain = []
            for position,journal,ref in sorted(transitions,key=lambda item:item[0]):
                shared = set(versions).intersection(journal['after'])
                if not shared:
                    continue
                for name in shared:
                    if journal['before'][name] != versions[name]:
                        return False
                    versions[name] = journal['after'][name]
                chain.append({**ref,'event_order':position})
        except (OSError, ValueError, KeyError, TypeError, StateStoreError):
            return False
        if not chain or versions != live:
            return False
        return {'successor_chain':chain,'current_subjects':live,'business_acceptance':'NOT_EVALUATED'}

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
        from cgkn.state.task_feedback import TaskFeedback
        config = {**config, "task_feedback": TaskFeedback(self.store, project_id, run_id).context(node_ids={node_id, *dependencies})}
        if self.knowledge:
            config["retrieved_knowledge"] = self.knowledge.retrieve([capability_ref])
        executor_ref = str(config.get("executor_ref", ""))
        request = BlockExecutionRequest(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, component_ref=capability_ref, executor_ref=executor_ref, input_values=dict(config.get("inputs", {})), dependency_result_refs=tuple(dependencies), task_context=TaskContext(node_goal=str(config["leaf_contract"]["leaf_goal"]), node_config={key: value for key, value in config.items() if key not in {"inputs", "acceptance", "constraints"}}, dependency_results=dependencies, project_constraints=constraints, acceptance=((config["acceptance"],) if isinstance(config.get("acceptance"), str) else tuple(config.get("acceptance", ())))), timeout_seconds=float(config.get("timeout_seconds", 30.0)), declared_effects=tuple(config.get("effects", ())), metadata={"capability_ref": capability_ref, "execution_mode": self.execution_mode.value})
        self._event(project_id, run_id, "NODE_STARTED", node_id=node_id, attempt_id=attempt_id, data={"executor_ref": executor_ref})
        try:
            authority = self._authority(project_id,run_id) if self.execution_mode == 'GOVERNED' else None
            permit = None
            if authority:
                from veriarbor.capability import CapabilityContract
                committed = authority.committed_tree()
                admitted = authority._find('PROPOSAL_ADMITTED','admission_id',committed['admission_id'])
                cid = config.get('capability_contract_id',capability_ref)
                if cid not in admitted['contracts']:raise ValueError('CAPABILITY_CONTRACT_REQUIRED')
                inputs = self._validate_dependencies(project_id,run_id,dependencies)
                producers={}
                for dependency in dependencies:
                    saved=self.store.load_result(project_id,run_id,dependency)
                    rid=saved.metadata['node_commit_receipt_id']
                    producers.update({path:rid for path in authority.validate_receipt(rid).output_hashes})
                from cgkn.runtime.node_authority import file_hash
                for path in config.get('input_paths',()):inputs[path]=file_hash(path)
                # A registered typed executor may declare immutable output names
                # before its Permit exists. Only independently checked bytes at
                # those exact names may later enter the Host receipt.
                bound_executor=self.registry.resolve(executor_ref,capability_ref)
                output_paths=tuple(bound_executor.declared_output_paths(request)) if hasattr(bound_executor,'declared_output_paths') else ()
                permit = authority.issue_permit(node_id=node_id,contract=CapabilityContract(**admitted['contracts'][cid]),
                    input_hashes=inputs,input_bindings={'dependency_nodes':list(dependencies),'producer_receipts':producers},executor_identity=executor_ref,
                    output_paths=output_paths)
                authority.validate_permit(permit.permit_id,node_id=node_id,capability_id=cid,
                    project_id=project_id,run_id=run_id,tree_version=committed['tree_version'],
                    contract_hash=CapabilityContract(**admitted['contracts'][cid]).fingerprint,input_hashes=inputs)
                authority.begin_node_execution(permit.permit_id)
                request=replace(request,metadata={**dict(request.metadata),'node_execution_permit':permit.as_dict(),
                                                  'execution_mode':'GOVERNED'})
            from cgkn.execution.deliverables import progress_record, verified_proof
            from cgkn.state.task_feedback import digest
            c = config['leaf_contract']
            checker = self.registry.resolve(self.deliverable_checkers[c['checker_ref']], 'deliverable.check@1')
            before = checker.snapshot(c)
            executor = self.registry.resolve(executor_ref, capability_ref)
            if "timeout_seconds" not in config:
                request = replace(request, timeout_seconds=executor.descriptor.default_timeout_seconds)
            live_root = None
            if ((hasattr(executor,'actions') or hasattr(executor,'in_candidate_workspace'))
                    and (not hasattr(executor,'requires_candidate_workspace') or executor.requires_candidate_workspace(request))):
                from cgkn.execution.materialization import stage_file_worker
                live_root=executor.candidate_root if hasattr(executor,'in_candidate_workspace') else executor.actions.root
                directory=self.store.run_dir(project_id,run_id)/'candidates'/node_id/attempt_id
                prior={}; previously_protected={}
                try:
                    previous=self.store.load_result(project_id,run_id,node_id)
                    previous_metadata=previous.as_dict()['metadata']
                    prior=previous_metadata.get('deliverable_check',{}).get('verified_artifacts',{})
                    previously_protected=previous_metadata.get('protected_existing_input_hashes',{})
                except StateStoreError: pass
                executor,checker,reused=stage_file_worker(executor,checker,c,directory,prior)
                staged_subjects=checker.snapshot(c)
                current_protected={name:staged_subjects[name] for name in set(prior)|set(previously_protected)
                    if name not in reused and name in staged_subjects and staged_subjects[name]}
                request=replace(request,metadata={**dict(request.metadata),'verified_partial_artifacts':reused,
                    'protected_existing_artifacts':current_protected})
            from contextlib import nullcontext
            from cgkn.execution.node_effects import execution_scope
            with execution_scope(authority,permit.permit_id) if authority else nullcontext():
                result = executor.execute(request)
            result = replace(result, metadata={**dict(result.metadata),
                "execution_mode": self.execution_mode.value,
                "execution_timeout_seconds": request.timeout_seconds,
                "execution_timeout_source": "node" if "timeout_seconds" in config else "executor_default"})
            if config.get('inherited_change_authorization'):
                result=replace(result,metadata={**dict(result.metadata),
                    'inherited_change_authorization':config['inherited_change_authorization']})
            if request.metadata.get('protected_existing_artifacts'):
                result=replace(result,metadata={**dict(result.metadata),
                    'protected_existing_input_hashes':dict(request.metadata['protected_existing_artifacts'])})
            # Preserve the executor observation before any independent checker can
            # fail. This is evidence in the existing run store, not another state.
            raw_path = self.store.run_dir(project_id,run_id)/'execution_receipts'/node_id/(attempt_id+'.json')
            if raw_path.exists():
                raise StateStoreError('refusing to overwrite raw execution receipt')
            self.store.atomic_json(raw_path, result.as_dict())
            if not result.succeeded:
                if authority:authority.revoke_permit(permit.permit_id,'EXECUTOR_FAILED')
                if live_root is not None and reused:
                    retained={name:{'path':str(checker.root/name),'sha256':h} for name,h in reused.items()}
                    return replace(result,metadata={**dict(result.metadata),
                        'deliverable_verdict':'UNRESOLVED','deliverable_check':{'verified_artifacts':retained,'verdict':'UNRESOLVED'},
                        'partial_continuation':'retained; reconcile UNKNOWN before another attempt'})
                return result
            check_request = replace(request, executor_ref=checker.descriptor.executor_ref,
                component_ref='deliverable.check@1',input_values={'before':before,'execution_receipt':result.as_dict(),
                    'execution_receipt_ref':{'path':str(raw_path),'sha256':__import__('hashlib').sha256(raw_path.read_bytes()).hexdigest()}})
            checked = checker.execute(check_request)
            valid,proof = verified_proof(checked,check_request,checker,c)
            metadata = {**dict(result.metadata),'execution_status':'EXECUTION_SUCCESS',
                'raw_execution_receipt_ref':{'path':raw_path.relative_to(self.store.root).as_posix(),
                    'sha256':__import__('hashlib').sha256(raw_path.read_bytes()).hexdigest()},
                'leaf_contract_hash':digest(request.task_context.as_dict()['node_config']['leaf_contract']),
                'deliverable_verdict':'VERIFIED' if valid else 'FAILED', 'goal_acceptance':'NOT_EVALUATED',
                'deliverable_check':proof, 'checker_receipt':checked.as_dict(),
                'implementation_progress':progress_record(c, proof,node_id=node_id)}
            if valid:
                if authority:
                    from veriarbor.execution_authority import NodeExecutionResult
                    from cgkn.runtime.node_authority import file_hash
                    # The canonical output packet binds in-memory dependency values too.
                    packet=authority.staging_dir(permit.permit_id)/'outputs.json'
                    self.store.immutable_json(packet,result.as_dict()['outputs'])
                    hashes={str(packet):file_hash(packet)}
                    checked_paths={str(__import__('pathlib').Path(item['path']).resolve()):item['sha256']
                        for item in proof.get('evidence_refs',()) if isinstance(item,dict) and 'path' in item and 'sha256' in item}
                    for path in permit.input_bindings.get('_output_paths',()):
                        if checked_paths.get(path)!=file_hash(path):
                            raise ValueError('OUTPUT_BINDING_REJECT: declared typed output lacks independent evidence')
                        hashes[path]=checked_paths[path]
                    # Copy verified candidate artifacts into the permit's immutable
                    # output scope; no post-hoc adoption of arbitrary live paths.
                    for name,item in proof.get('verified_artifacts',{}).items():
                        if isinstance(item,dict) and item.get('path'):
                            import shutil, hashlib
                            staged=packet.parent/(hashlib.sha256(str(name).encode()).hexdigest()+'.artifact')
                            shutil.copyfile(item['path'],staged)
                            hashes[str(staged)]=file_hash(staged)
                    authority.submit_node_result(NodeExecutionResult(permit.permit_id,hashes,
                        tuple(result.metadata.get('effects_used',())),
                        tuple(result.metadata.get('decision_records',())),tuple(proof.get('evidence_refs',())),
                        {k:result.usage[k] for k in permit.budget_scope if k in result.usage},dict(permit.input_hashes),
                        consumed_inputs=tuple(result.metadata.get('consumed_inputs',permit.input_bindings.get('manifest',()))),
                        claim_refs=tuple(result.metadata.get('claim_refs',()))))
                    receipt=authority.commit_node_execution(permit.permit_id)
                    metadata.update(node_commit_receipt_id=receipt.receipt_id,
                                    node_output_packet=str(packet),execution_mode='GOVERNED')
                if live_root is not None:
                    from cgkn.execution.materialization import publish_candidate
                    publish_candidate(live_root,checker.root,before,proof['subjects'],store=self.store,
                        intent_path=self.store.run_dir(project_id,run_id)/'publication_intents'/node_id/(attempt_id+'.json'),
                        result=replace(result,metadata=metadata))
                return replace(result,metadata=metadata)
            if authority:authority.revoke_permit(permit.permit_id,'DELIVERABLE_FAILED')
            failed=replace(result,status=BlockStatus.FAILED,metadata=metadata,
                error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,'EXECUTION_SUCCEEDED_DELIVERABLE_FAILED',
                    {'progress':metadata['implementation_progress'],'evidence_refs':proof.get('evidence_refs',[])}))
            return authority.record_failed_execution(permit.permit_id,failed) if authority else failed
        except ExecutorResolutionError as exc:
            if locals().get('authority') and locals().get('permit'):
                if authority._permit(permit.permit_id).status=='ACTIVE':
                    authority.revoke_permit(permit.permit_id,'EXECUTOR_NOT_FOUND')
            return BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=executor_ref or "unresolved", status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTOR_NOT_FOUND, str(exc)))
        except Exception as exc:  # executor boundary fails closed
            if locals().get('authority') and locals().get('permit'):
                p=authority._permit(permit.permit_id)
                if p.status=='ACTIVE':authority.revoke_permit(p.permit_id,str(exc))
            original = locals().get('result')
            return BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=executor_ref or "unresolved", status=BlockStatus.FAILED,
                usage=original.usage if original is not None else {},
                metadata={'execution_receipt':original.as_dict() if original is not None else None,'deliverable_verdict':'INVALID_EVALUATOR'},
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}",{'failure_domain':'HARNESS'}), retryable=False)

    def _authority(self, project_id, run_id):
        from .node_authority import ExecutionAuthority
        return ExecutionAuthority(self.store,project_id,run_id,registry=self.critical_check_registry)

    def _validate_dependencies(self, project_id, run_id, dependencies):
        from .node_authority import file_hash
        inputs={}
        for node_id in dependencies:
            result=self.store.load_result(project_id,run_id,node_id)
            receipt=self._authority(project_id,run_id).validate_execution_result(result)
            state=self.store.load_run(project_id,run_id)
            dag=ExecutionDAG.from_dict(state.execution_dag)
            producer=dag.by_id[node_id]
            contract=producer.config['leaf_contract']
            checker=self.registry.resolve(self.deliverable_checkers[contract['checker_ref']], 'deliverable.check@1')
            live=checker.snapshot(contract)
            if live!=dict(result.metadata.get('deliverable_check',{}).get('subjects',{})):
                if not self._verified_successor_chain(state,dag,node_id,result,live):
                    raise ValueError('OUTPUT_BINDING_REJECT: producer subjects changed')
            packet=result.metadata.get('node_output_packet')
            if not packet or packet not in receipt.output_hashes or json.loads(__import__('pathlib').Path(packet).read_text(encoding='utf-8'))!=result.as_dict()['outputs']:
                raise ValueError('OUTPUT_BINDING_REJECT: dependency packet differs')
            inputs.update(receipt.output_hashes)
        return inputs

    def _event(self, project_id: str, run_id: str, event_type: str, *, node_id: str | None = None, attempt_id: str | None = None, data: dict[str, Any] | None = None) -> None:
        import os,time
        timing = dict(utc_unix=time.time(),monotonic_ns=time.monotonic_ns(),clock_pid=os.getpid())
        self.store.append_event(EventRecord(f"event.{uuid.uuid4().hex}", project_id, run_id, event_type, node_id, attempt_id, {**(data or {}),'timing':timing}))
