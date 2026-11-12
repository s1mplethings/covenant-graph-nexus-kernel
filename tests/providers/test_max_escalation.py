import dataclasses
import hashlib
import json

import pytest

from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.providers.recording import RecordedCompletionClient
from cgkn.providers.routing import ESCALATION_CHECKS, ModelEscalationDenied, _canonical
from cgkn.state import FileRunStore


class Client:
    def __init__(self): self.calls=[]
    def complete(self, **kw):
        self.calls.append(kw)
        return ProviderCompletion('{}',kw['config'].model_id,'offline-receipt',{'input_tokens':1,'output_tokens':1})


def setup(tmp_path, *, role='agent', call_kind='semantic_decision_attempt'):
    store=FileRunStore(tmp_path);root=store.run_dir('p','r');client=Client()
    recorded=RecordedCompletionClient(client,store,'p','r',escalation_evidence_producers={'independent-fixture-verifier'})
    config=ModelRoleConfig(role,'qwen',model_id='qwen3.8-max')
    kwargs=dict(config=config,system='offline qualification',user=json.dumps({'call_kind':call_kind}),
                schema_name='cgkn_agent_decision',schema=None)
    public={k:v for k,v in kwargs.items() if k!='config'}
    key=hashlib.sha256(_canonical({'config':dataclasses.asdict(config),'request':public}).encode()).hexdigest()
    source=root/'raw-semantic-observation.txt';source.parent.mkdir(parents=True,exist_ok=True)
    source.write_text('controlled independent semantic failure evidence fixture')
    source_ref={'path':source.name,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    checks={}
    for name in ESCALATION_CHECKS:
        path=root/'checks'/(name+'.json')
        store.immutable_json(path,{'producer':'independent-fixture-verifier','request_hash':key,
            'check':name,'passed':True,'failure_domain':'SEMANTIC','source_refs':[source_ref]})
        checks[name]={'path':str(path.relative_to(root)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    grant={'request_hash':key,'reason':'REPEATED_CHEAP_SEMANTIC_FAILURE_WITH_VALID_CONTEXT',
           'operation':'project_semantic_decision','checks':checks}
    path=root/'model_escalations'/(key+'.json')
    return store,root,recorded,client,kwargs,path,grant


def test_max_requires_exact_checked_receipt_and_cannot_reuse_grant(tmp_path):
    store,root,recorded,client,kwargs,path,grant=setup(tmp_path)
    store.immutable_json(path,grant)
    assert recorded.complete(**kwargs).request_id=='offline-receipt'
    assert len(client.calls)==1
    before=path.read_bytes()
    from cgkn.providers.gateway_client import GatewayCompletionError
    from cgkn.providers.routing import admit_recorded_model
    with pytest.raises(GatewayCompletionError, match='NO_NOVEL_DELTA'):
        recorded.complete(**kwargs)
    # The earlier novelty gate must not replace or weaken one-use authorization.
    with pytest.raises(ModelEscalationDenied, match='already consumed'):
        admit_recorded_model(store, root, kwargs['config'],
            {k:v for k,v in kwargs.items() if k != 'config'},
            evidence_producers={'independent-fixture-verifier'})
    assert len(client.calls)==1 and path.read_bytes()==before
    admissions=list((root/'provider_calls').glob('*/model_admission.json'))
    assert len(admissions)==1
    assert json.loads(admissions[0].read_text())['escalated'] is True


@pytest.mark.parametrize('reason', ['missing','harness','source_changed','self_authorized','wrong_request','routine'])
def test_ineligible_or_tampered_escalations_never_dispatch(tmp_path, reason):
    store,root,recorded,client,kwargs,path,grant=setup(tmp_path)
    if reason=='harness':
        name='cheap_semantic_failure';p=root/grant['checks'][name]['path']
        doc=json.loads(p.read_text());doc['failure_domain']='HARNESS';p.write_text(json.dumps(doc))
        grant['checks'][name]['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    if reason=='source_changed': (root/'raw-semantic-observation.txt').write_text('changed')
    if reason=='self_authorized': recorded.escalation_evidence_producers=frozenset()
    if reason=='wrong_request': grant['request_hash']='another request'
    if reason=='routine': grant['operation']='routine_coding'
    if reason!='missing': store.immutable_json(path,grant)
    with pytest.raises(ModelEscalationDenied): recorded.complete(**kwargs)
    assert not client.calls and not path.with_suffix('.used.json').exists()


@pytest.mark.parametrize('role,kind',[('worker','semantic_decision_attempt'),('agent','schema_repair_attempt'),
                                    ('agent','declaration_correction_attempt'),('agent','admission_correction_attempt')])
def test_worker_and_correction_cannot_borrow_semantic_escalation(tmp_path,role,kind):
    store,root,recorded,client,kwargs,path,grant=setup(tmp_path,role=role,call_kind=kind)
    store.immutable_json(path,grant)
    with pytest.raises(ModelEscalationDenied): recorded.complete(**kwargs)
    assert not client.calls


def test_cheap_route_needs_no_escalation_or_evidence_reads(tmp_path):
    store,root,recorded,client,kwargs,path,grant=setup(tmp_path)
    kwargs['config']=dataclasses.replace(kwargs['config'],model_id='fixture-flash')
    recorded.complete(**kwargs)
    assert len(client.calls)==1 and not path.exists()


def test_provider_alias_cannot_bypass_max_policy(tmp_path):
    store,root,recorded,client,kwargs,path,grant=setup(tmp_path)
    kwargs['config']=dataclasses.replace(kwargs['config'],model_id=None)
    with pytest.raises(ModelEscalationDenied,match='CONCRETE_MODEL_BINDING_REQUIRED'):
        recorded.complete(**kwargs)
    assert not client.calls


def test_same_pending_recorded_request_cannot_race_into_second_dispatch(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from cgkn.providers.gateway_client import GatewayCompletionError
    entered,release=Event(),Event()
    class Pending(Client):
        def complete(self, **kwargs):
            self.calls.append(kwargs);entered.set()
            assert release.wait(5)
            return ProviderCompletion('{}','fixture-flash','one',{})
    store=FileRunStore(tmp_path);client=Pending()
    first=RecordedCompletionClient(client,store,'p','r')
    reopened=RecordedCompletionClient(client,store,'p','r')
    kwargs=dict(config=ModelRoleConfig('agent','fixture-flash'),system='',user='same request',schema=None,schema_name='x')
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(first.complete,**kwargs)
        try:
            assert entered.wait(5)
            with pytest.raises(GatewayCompletionError,match='prior_submission_unknown'):
                pool.submit(reopened.complete,**kwargs).result(timeout=5)
        finally: release.set()
        assert pending.result(timeout=5).request_id=='one'
    assert len(client.calls)==1
    assert len(list((store.run_dir('p','r')/'provider_calls').glob('*/request.json')))==1


def test_distinct_recorded_requests_are_not_serialized_by_admission_lock(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier=Barrier(2)
    class Parallel(Client):
        def complete(self, **kwargs):
            barrier.wait(timeout=5)
            return ProviderCompletion('{}','fixture-flash',kwargs['user'],{})
    recorded=RecordedCompletionClient(Parallel(),FileRunStore(tmp_path),'p','r')
    kwargs=dict(config=ModelRoleConfig('agent','fixture-flash'),system='',schema=None,schema_name='x')
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests=[pool.submit(recorded.complete,user=user,**kwargs) for user in ('a','b')]
        assert [r.result(timeout=10).request_id for r in requests]==['a','b']
