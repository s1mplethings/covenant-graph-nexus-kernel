"""Application-visible request/response receipts; never credentials or hidden thought."""
import dataclasses
import time
import uuid
import json
import hashlib
from contextvars import ContextVar
from contextlib import contextmanager

_EXECUTION = ContextVar("recorded_execution", default=None)


@contextmanager
def recorded_execution(request):
    """Trusted executor identity, never a model field or an upstream parameter."""
    identity = {k:getattr(request,k) for k in ("project_id","run_id","node_id","attempt_id")}
    token = _EXECUTION.set(identity)
    try:
        yield
    finally:
        _EXECUTION.reset(token)

from .gateway_client import GatewayCompletionClient,GatewayCompletionError


class RecordedCompletionClient:
    def __init__(self, client, store, project_id, run_id, *, escalation_evidence_producers=()):
        self.project_id, self.run_id = project_id, run_id
        self.client, self.store = client, store
        self.root = store.run_dir(project_id, run_id) / 'provider_calls'
        self.escalation_evidence_producers = frozenset(escalation_evidence_producers)

    def complete(self, **kwargs):
        public = {k:v for k,v in kwargs.items() if k != 'config'}
        config=dataclasses.asdict(kwargs['config'])
        execution = _EXECUTION.get()
        retry_admissions = []
        # Serialize admission only for the same logical request. Distinct
        # independent calls release this lock before any network execution.
        from cgkn.adapters.veriarbor.provider_novelty_adapter import request_novelty, novelty_disposition
        novelty = request_novelty(public, config['role'], execution)
        logical = hashlib.sha256(json.dumps(novelty, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.store.exclusive_file(self.root/'admission'/ (logical+'.lock'),wait_seconds=10):
            # Reopening a controller must not evade the budget latch by minting a
            # new cgkn_attempt_id for the same unresolved logical request.
            previous_novelty = []
            for path in self.root.glob('*/request.json'):
                prior=json.loads(path.read_text(encoding='utf-8'))
                if prior.get('config',{}).get('role') != config['role']:continue
                prior_error_path = path.with_name('error.json')
                prior_error = json.loads(prior_error_path.read_text(encoding='utf-8')) if prior_error_path.exists() else {}
                # A cooperative pre-dispatch hold consumed no upstream request.
                if prior_error.get('category') != 'controller_hold_before_dispatch':
                    old_novelty = prior.get('novelty') or request_novelty(prior['request'], config['role'], prior.get('execution_identity'))
                    previous_novelty.append(old_novelty)
                if prior.get('request') != public:continue
                error_path=path.with_name('error.json');response_path=path.with_name('response.json')
                failure=json.loads(error_path.read_text(encoding='utf-8')) if error_path.exists() else None
                if (failure and failure.get('outcome_unknown')) or (failure is None and not response_path.exists()):
                    admission = self._reconciled_retry(path, prior, execution, config['role'])
                    if admission is not None:
                        retry_admissions.append(admission)
                        continue
                    raise GatewayCompletionError('prior_submission_unknown',
                        'Original recorded request '+str(prior.get('identity'))+' requires read-only reconciliation; no new attempt created',outcome_unknown=True)
            if retry_admissions:
                # A verified local-effect reconciliation is new host evidence,
                # not a reset or replay of the upstream UNKNOWN receipt.
                novelty = {**novelty, 'evidence': hashlib.sha256(json.dumps(
                    {'request_evidence': novelty['evidence'], 'reconciliations': retry_admissions},
                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
            if novelty_disposition(previous_novelty, novelty) == 'NO_NOVEL_DELTA':
                from cgkn.state import EventRecord
                self.store.append_event(EventRecord(uuid.uuid4().hex, self.project_id, self.run_id,
                    'PROVIDER_NOVELTY_DENIED', data={'scope': novelty['scope'], 'dimensions': novelty,
                    'reason': 'NO_NOVEL_DELTA', 'provider_dispatched': False}))
                raise GatewayCompletionError('NO_NOVEL_DELTA',
                    'No new variant, artifact, contract, evidence or checker qualification; original request retained')
            identity = uuid.uuid4().hex
            directory = self.root / identity
            self.store.atomic_json(directory / 'request.json', {
                'identity': identity, 'started_at': time.time(), 'config': dataclasses.asdict(kwargs['config']),
                'transport_kind':'recorded_gateway' if isinstance(self.client,GatewayCompletionClient) else 'bounded_completion_client',
                'request': public, 'execution_identity': execution,
                'reconciled_retry_admissions': retry_admissions, 'novelty': novelty})
        try:
            from .routing import admit_recorded_model
            admission=admit_recorded_model(self.store,self.root.parent,kwargs['config'],public,
                                           evidence_producers=self.escalation_evidence_producers)
            self.store.immutable_json(directory/'model_admission.json', admission)
            if isinstance(self.client, GatewayCompletionClient):
                from cgkn.protocol.adaptive_context import prepare_completion
                packed_system, packed_user, packing = prepare_completion(kwargs['system'], kwargs['user'], kwargs['config'])
                self.store.immutable_json(directory/'packing.json', packing)
                if self.client.input_token_ceiling is not None and kwargs['config'].model in {'qwen','deepseek'}:
                    from .text_wire import completion_preflight
                    check=completion_preflight(system=packed_system,user=packed_user,**{k:kwargs[k] for k in ('schema_name','schema','config')},ceiling=self.client.input_token_ceiling)
                    self.store.immutable_json(directory/'preflight.json',check)
                kwargs = {**kwargs, 'call_identity': identity}
            result = self.client.complete(**kwargs)
            self.store.atomic_json(directory / 'response.json', {
                'identity': identity, 'ended_at': time.time(), 'text': result.text, 'model': result.model,
                'request_id': result.request_id, 'usage': dict(result.usage),
                'attempts': result.attempts, 'routing': dict(result.routing),
                'raw_finish_reason':result.raw_finish_reason})
            return result
        except Exception as exc:
            self.store.atomic_json(directory / 'error.json', {
                'identity': identity, 'ended_at': time.time(), 'error_type': type(exc).__name__,
                'category': getattr(exc, 'category', None),
                'completed_response': getattr(exc, 'completed_response', None),
                'provider_dispatched': getattr(exc, 'provider_dispatched', None),
                'outcome_unknown': getattr(exc, 'outcome_unknown', None), 'error': str(exc)[:1500]})
            raise

    def _reconciled_retry(self, request_path, prior_request, execution, role):
        """A new DAG attempt after verified NOT_APPLIED, never reset UNKNOWN.

        A different prompt/config/attempt number alone grants no authorization.
        The original error, stored reconciliation and its controller event must
        identify this node and the exact prior provider request.
        """
        if role != 'worker' or not isinstance(execution, dict):return None
        if (execution.get('project_id'),execution.get('run_id')) != (self.project_id,self.run_id):return None
        from cgkn.state.provenance import ProvenanceGate,reference
        from cgkn.state.task_feedback import digest
        from cgkn.state.store import StateStoreError
        try:
            node_id=execution['node_id'];attempt_id=execution['attempt_id']
            old_identity=prior_request.get('execution_identity')
            if old_identity and any(old_identity.get(k)!=execution[k] for k in ('project_id','run_id','node_id')):return None
            record=self.store.load_run(self.project_id,self.run_id).nodes[node_id]
            if record.status!='RUNNING' or attempt_id!=f'attempt-{len(record.attempts)+1:04d}':return None
            error_path=request_path.with_name('error.json')
            if not error_path.is_file() or not json.loads(error_path.read_text(encoding='utf8')).get('outcome_unknown'):return None
            error_ref=reference(self.store.root,error_path)
            gate=ProvenanceGate(self.store,self.project_id,self.run_id)
            events=self.store.load_events(self.project_id,self.run_id)
            for saved_attempt in reversed(record.attempts):
                path=self.root.parent/'attempts'/node_id/(saved_attempt+'.json')
                row=json.loads(path.read_text(encoding='utf8'));meta=row.get('metadata',{});proof=meta.get('reconciliation',{})
                if proof.get('disposition')!='NOT_APPLIED':continue
                if (row.get('project_id'),row.get('run_id'),row.get('node_id'),row.get('attempt_id'))!=(self.project_id,self.run_id,node_id,saved_attempt):continue
                source=self.root.parent/'attempts'/node_id/(meta['original_attempt_id']+'.json')
                original=json.loads(source.read_text(encoding='utf8'))
                if digest(original)!=proof.get('source_receipt_hash') or not original.get('error',{}).get('details',{}).get('outcome_unknown'):continue
                event=next((e for e in events if e.event_type=='EFFECT_RECONCILED' and e.node_id==node_id and e.attempt_id==saved_attempt and e.data.get('disposition')=='NOT_APPLIED' and e.data.get('original_receipt_hash')==proof['source_receipt_hash']),None)
                if event is None:continue
                # The controller only emits EFFECT_RECONCILED after admitting a
                # trusted checker; retain and verify that exact checker receipt.
                checker=None
                for candidate in (self.root.parent/'attempts').glob('*/*.json'):
                    value=json.loads(candidate.read_text(encoding='utf8'))
                    if digest(value)==meta.get('checker_receipt_hash'):
                        checker=value;break
                if not checker or checker.get('status')!='SUCCEEDED' or checker.get('outputs',{}).get('effect_reconciliation')!=proof:continue
                for ref in proof.get('evidence_refs',[]):
                    inspection=json.loads(gate.resolve(ref))
                    if (inspection.get('disposition')=='NOT_APPLIED'
                            and inspection.get('source_receipt_sha256')==proof['source_receipt_hash']
                            and inspection.get('raw_error_ref')==error_ref):
                        gate.resolve(error_ref)
                        return {'kind':'VerifiedNotAppliedNewAttempt','original_request_ref':reference(self.store.root,request_path),
                            'original_error_ref':error_ref,'reconciliation_ref':reference(self.store.root,path),
                            'inspection_ref':ref,'event_id':event.event_id,'execution_identity':dict(execution),
                            'upstream_usage_and_cost':'UNKNOWN_UNCHANGED'}
        except (OSError,ValueError,KeyError,TypeError,AttributeError,StateStoreError):
            return None
        return None
