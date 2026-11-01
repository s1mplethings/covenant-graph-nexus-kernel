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


class GraphEditRejected(ValueError):
    """A proposed graph was rejected before any persistent mutation."""


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
    def __init__(self, registry: ExecutorRegistry, store: FileRunStore, *, max_parallel: int = 1, knowledge=None, resource_limits=None, reconciliation_executors=(), deliverable_checkers=None):
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

    @observed("dag", lambda a: a["self"].store.run_dir(a["project_id"], a["run_id"]))
    def run(self, *, project_id, run_id, **kwargs):
        with self.store.exclusive_run(project_id, run_id):
            return self._run(project_id=project_id, run_id=run_id, **kwargs)

    def _run(self, *, project_id: str, run_id: str, tree: CapabilityTree, dag: ExecutionDAG, resume: bool = False, retry_node: str | None = None, constraints: tuple[str, ...] = (), accept_edits: bool = False, cancel=None) -> RunSummary:
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
        self._bind_graph(state, dag, accept_edits=accept_edits, retry_node=retry_node)
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
                receipt = self.store.load_result(project_id,run_id,node_id)
                if receipt.metadata.get('deliverable_verdict') != 'VERIFIED':
                    raise GraphEditRejected('LEGACY_UNQUALIFIED_DELIVERABLE: explicit requalification required ' + node_id)
                c = dag.by_id[node_id].config['leaf_contract']
                checker = self.registry.resolve(self.deliverable_checkers[c['checker_ref']], 'deliverable.check@1')
                if checker.snapshot(c) != dict(receipt.metadata.get('deliverable_check',{}).get('subjects',{})):
                    raise GraphEditRejected('OBJECT_VERSION_MISMATCH: explicit affected-subgraph retry required ' + node_id)
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
                    if any(not self._compatible(self._effective_config(node), self._effective_config(dag.by_id[other]))
                           for other in inflight.values()):
                        continue
                    dependency_results = {d: self.store.load_result(project_id, run_id, d).outputs
                                          for d in node.depends_on}
                    # Durable admission precedes dispatch. Recovery sees RUNNING
                    # even if the process dies before NODE_STARTED is appended.
                    state.nodes[node_id].status = "RUNNING"
                    self.store.save_run(state)
                    self._event(project_id, run_id, "NODE_DISPATCHED", node_id=node_id,
                                attempt_id=attempt_id)
                    pending.remove(node_id)
                    actual.append(node_id)
                    future = pool.submit(self._execute, project_id, run_id, attempt_id,
                        node_id, node.capability_ref, dict(node.config), dependency_results, constraints)
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
        summary = RunSummary(project_id, run_id, state.status, len(state.nodes), tuple(actual), tuple(reused), failed, blocked, sum(max(0, len(value.attempts) - 1) for value in state.nodes.values()))
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
            for name in c.get('read_scope',()):enforced.setdefault('workspace:'+str(executor.actions._path(name)),'read')
        if enforced:
            config["resources"] = {**dict(config.get("resources", {})), **dict(enforced)}
        return config

    @staticmethod
    def _compatible(left, right) -> bool:
        """Explicit opt-in; shared writes serialize, shared reads may overlap.

        Resource names are trusted capability configuration, not OS isolation.
        Executors must still enforce their declared workspace boundary.
        """
        if not left.get("parallel_safe") or not right.get("parallel_safe"):
            return False
        a, b = left.get("resources", {}), right.get("resources", {})
        for claims in (a, b):
            if not isinstance(claims, Mapping) or any(v not in {"read", "write"} for v in claims.values()):
                raise ValueError("resources must map identity to read/write")
        return not any(a[key] == "write" or b[key] == "write" for key in a.keys() & b.keys())

    def _new_state(self, project_id: str, run_id: str, dag: ExecutionDAG) -> RunState:
        if (self.store.run_dir(project_id, run_id) / "run_state.json").exists():
            raise StateStoreError("existing run requires explicit resume; refusing to overwrite history")
        state = RunState(project_id, run_id, nodes={node.id: NodeExecutionRecord(node.id) for node in dag.nodes}, execution_dag=dag.as_dict(), graph_revision=1)
        self.store.save_run(state)
        self._event(project_id, run_id, "RUN_CREATED")
        return state

    def _bind_graph(self, state: RunState, dag: ExecutionDAG, *, accept_edits: bool, retry_node: str | None) -> None:
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
        if previous.goal != dag.goal or not set(previous.by_id) <= set(dag.by_id):
            raise ValueError("persisted run state does not match DAG: goal/removal")
        old = {n['id']: n for n in previous.as_dict()['nodes']}
        new = {n['id']: n for n in dag.as_dict()['nodes']}
        changed = {key for key in old if old[key] != new[key]}
        added = set(new) - set(old)
        if (changed or added) and not accept_edits:
            raise ValueError("persisted run state does not match DAG: explicit edit commit required")
        retry_scope = set(downstream_closure(dag, {retry_node})) if retry_node else set()
        affected = set(downstream_closure(dag, changed))
        if any(state.nodes[key].status == BlockStatus.SUCCEEDED.value and key not in retry_scope for key in affected & set(old)):
            raise GraphEditRejected("cannot edit/reuse succeeded nodes without explicit affected-subgraph retry; retry the earliest changed succeeded node, not only its failed descendant")
        if not (changed or added) and state.execution_dag is not None:
            return
        # No mutation above this line: illegal transitions preserve saved state.
        for key in added:
            state.nodes[key] = NodeExecutionRecord(key)
        for key in affected:
            state.nodes[key].status = "PENDING"
            state.nodes[key].latest_result_ref = None
            state.nodes[key].reused = False
        state.execution_dag = dag.as_dict()
        state.graph_revision += 1
        state.status = "PENDING"
        state.updated_at = utc_now()
        self.store.save_run(state)
        self._event(state.project_id, state.run_id, "GRAPH_COMMITTED", data={"revision": state.graph_revision, "added": sorted(added), "changed": sorted(changed), "invalidated": sorted(affected)})

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
        request = BlockExecutionRequest(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, component_ref=capability_ref, executor_ref=executor_ref, input_values=dict(config.get("inputs", {})), dependency_result_refs=tuple(dependencies), task_context=TaskContext(node_goal=str(config["leaf_contract"]["leaf_goal"]), node_config={key: value for key, value in config.items() if key not in {"inputs", "acceptance", "constraints"}}, dependency_results=dependencies, project_constraints=constraints, acceptance=((config["acceptance"],) if isinstance(config.get("acceptance"), str) else tuple(config.get("acceptance", ())))), timeout_seconds=float(config.get("timeout_seconds", 30.0)), declared_effects=tuple(config.get("effects", ())), metadata={"capability_ref": capability_ref})
        self._event(project_id, run_id, "NODE_STARTED", node_id=node_id, attempt_id=attempt_id, data={"executor_ref": executor_ref})
        try:
            from cgkn.execution.deliverables import progress_record, verified_proof
            from cgkn.state.task_feedback import digest
            c = config['leaf_contract']
            checker = self.registry.resolve(self.deliverable_checkers[c['checker_ref']], 'deliverable.check@1')
            before = checker.snapshot(c)
            executor = self.registry.resolve(executor_ref, capability_ref)
            live_root = None
            if hasattr(executor,'actions') or hasattr(executor,'in_candidate_workspace'):
                from cgkn.execution.materialization import stage_file_worker
                live_root=executor.candidate_root if hasattr(executor,'in_candidate_workspace') else executor.actions.root
                directory=self.store.run_dir(project_id,run_id)/'candidates'/node_id/attempt_id
                prior={}
                try:
                    previous=self.store.load_result(project_id,run_id,node_id)
                    prior=previous.as_dict()['metadata'].get('deliverable_check',{}).get('verified_artifacts',{})
                except StateStoreError: pass
                executor,checker,reused=stage_file_worker(executor,checker,c,directory,prior)
                request=replace(request,metadata={**dict(request.metadata),'verified_partial_artifacts':reused})
            result = executor.execute(request)
            # Preserve the executor observation before any independent checker can
            # fail. This is evidence in the existing run store, not another state.
            raw_path = self.store.run_dir(project_id,run_id)/'execution_receipts'/node_id/(attempt_id+'.json')
            if raw_path.exists():
                raise StateStoreError('refusing to overwrite raw execution receipt')
            self.store.atomic_json(raw_path, result.as_dict())
            if not result.succeeded:
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
                if live_root is not None:
                    from cgkn.execution.materialization import publish_candidate
                    publish_candidate(live_root,checker.root,before,proof['subjects'],store=self.store,
                        intent_path=self.store.run_dir(project_id,run_id)/'publication_intents'/node_id/(attempt_id+'.json'),
                        result=replace(result,metadata=metadata))
                return replace(result,metadata=metadata)
            return replace(result,status=BlockStatus.FAILED,metadata=metadata,
                error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,'EXECUTION_SUCCEEDED_DELIVERABLE_FAILED',
                    {'progress':metadata['implementation_progress'],'evidence_refs':proof.get('evidence_refs',[])}))
        except ExecutorResolutionError as exc:
            return BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=executor_ref or "unresolved", status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.EXECUTOR_NOT_FOUND, str(exc)))
        except Exception as exc:  # executor boundary fails closed
            original = locals().get('result')
            return BlockExecutionResult(project_id=project_id, run_id=run_id, attempt_id=attempt_id, node_id=node_id, executor_ref=executor_ref or "unresolved", status=BlockStatus.FAILED,
                usage=original.usage if original is not None else {},
                metadata={'execution_receipt':original.as_dict() if original is not None else None,'deliverable_verdict':'INVALID_EVALUATOR'},
                error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR, f"{type(exc).__name__}: {exc}",{'failure_domain':'HARNESS'}), retryable=False)

    def _event(self, project_id: str, run_id: str, event_type: str, *, node_id: str | None = None, attempt_id: str | None = None, data: dict[str, Any] | None = None) -> None:
        import os,time
        timing = dict(utc_unix=time.time(),monotonic_ns=time.monotonic_ns(),clock_pid=os.getpid())
        self.store.append_event(EventRecord(f"event.{uuid.uuid4().hex}", project_id, run_id, event_type, node_id, attempt_id, {**(data or {}),'timing':timing}))
