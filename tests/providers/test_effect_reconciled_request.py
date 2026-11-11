from tests.executor_authority_support import invoke_bound_executor
import json
from types import SimpleNamespace
import pytest
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.providers.recording import RecordedCompletionClient,recorded_execution
from cgkn.providers.gateway_client import GatewayCompletionError
from cgkn.state import FileRunStore,RunState,NodeExecutionRecord
from cgkn.state.task_feedback import digest
from cgkn.state.provenance import put_evidence,reference
from cgkn.execution import BlockExecutionResult,BlockStatus,ExecutionError,ExecutionErrorCode
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.orchestration import CapabilityTree
from tests.qualification_support import probe_node

class Client:
    def __init__(self):self.calls=[]
    def complete(self,**kwargs):
        self.calls.append(kwargs)
        if len(self.calls)==1:raise GatewayCompletionError('provider_outcome_unknown','controlled partial response',outcome_unknown=True)
        return ProviderCompletion('{}','fixture','response',{})

def fixture(tmp_path,reconcile=True,legacy=False):
    store=FileRunStore(tmp_path/'state');client=Client();recorded=RecordedCompletionClient(client,store,'p','r')
    req=SimpleNamespace(project_id='p',run_id='r',node_id='A',attempt_id='attempt-0001')
    kwargs=dict(system='bounded',user='identical prompt',schema_name='worker',schema={},config=ModelRoleConfig('worker','fixture'))
    with pytest.raises(GatewayCompletionError):
        if legacy:recorded.complete(**kwargs)
        else:
            with recorded_execution(req):recorded.complete(**kwargs)
    first=next(recorded.root.glob('*/request.json'));before={str(p):p.read_bytes() for p in first.parent.glob('*.json')}
    root=store.run_dir('p','r');tree=CapabilityTree('goal',(probe_node('A',capability_ref='work@1',config={'executor_ref':'witness@1'}),));store.immutable_json(root/'capability_tree.json',tree.as_dict())
    old=BlockExecutionResult(project_id='p',run_id='r',node_id='A',attempt_id='attempt-0001',executor_ref='witness@1',status=BlockStatus.BLOCKED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'unknown',{'outcome_unknown':True}))
    store.save_result(old);store.save_run(RunState('p','r',nodes={'A':NodeExecutionRecord('A','BLOCKED',['attempt-0001'])}))
    if reconcile:
        ref=put_evidence(store,'p','r',{'kind':'LocalBoundedFileEffectInspection','disposition':'NOT_APPLIED','source_receipt_sha256':digest(old.as_dict()),'raw_error_ref':reference(store.root,first.with_name('error.json'))})
        checker=BlockExecutionResult(project_id='p',run_id='r',node_id='verify',attempt_id='attempt-0001',executor_ref='verify.effect@1',status=BlockStatus.SUCCEEDED,outputs={'effect_reconciliation':{'source_receipt_hash':digest(old.as_dict()),'disposition':'NOT_APPLIED','evidence_refs':[ref]}})
        store.save_result(checker);DAGRunner(ExecutorRegistry(),store,reconciliation_executors=('verify.effect@1',)).reconcile_effects('p','r','A',checker)
    state=store.load_run('p','r');state.nodes['A'].status='RUNNING';store.save_run(state)
    req.attempt_id=f"attempt-{len(state.nodes['A'].attempts)+1:04d}"
    return store,client,recorded,req,kwargs,first,before

@pytest.mark.parametrize('legacy',[False,True])
def test_verified_not_applied_permits_new_attempt_without_reset(tmp_path,legacy):
    store,client,recorded,req,kwargs,first,before=fixture(tmp_path,legacy=legacy)
    with recorded_execution(req):assert recorded.complete(**kwargs).text=='{}'
    assert len(client.calls)==2
    assert all(__import__('pathlib').Path(p).read_bytes()==v for p,v in before.items())
    new=next(p for p in recorded.root.glob('*/request.json') if p!=first);row=json.loads(new.read_text())
    assert row['request']==json.loads(first.read_text())['request']
    assert row['execution_identity']['attempt_id']=='attempt-0003'
    assert row['reconciled_retry_admissions'][0]['upstream_usage_and_cost']=='UNKNOWN_UNCHANGED'
    assert json.loads(first.with_name('error.json').read_text())['outcome_unknown']

@pytest.mark.parametrize('attack',['no_reconciliation','no_scope','wrong_node','wrong_attempt','not_running','missing_event','changed_error','changed_checker','changed_inspection'])
def test_unqualified_retry_stays_blocked(tmp_path,attack):
    store,client,recorded,req,kwargs,first,before=fixture(tmp_path,reconcile=attack!='no_reconciliation')
    root=store.run_dir('p','r')
    if attack=='wrong_node':req.node_id='B'
    if attack=='wrong_attempt':req.attempt_id='attempt-0001'
    if attack=='not_running':
        state=store.load_run('p','r');state.nodes['A'].status='BLOCKED';store.save_run(state)
    if attack=='missing_event':(root/'events.jsonl').write_text('')
    if attack=='changed_error':first.with_name('error.json').write_text('{"outcome_unknown":true,"changed":true}')
    if attack=='changed_checker':(root/'attempts/verify/attempt-0001.json').write_text('{}')
    if attack=='changed_inspection':
        row=json.loads((root/'attempts/A/attempt-0002.json').read_text());ref=row['metadata']['reconciliation']['evidence_refs'][0];(store.root/ref['path']).write_text('{}')
    with pytest.raises(GatewayCompletionError,match='prior_submission_unknown'):
        if attack=='no_scope':recorded.complete(**kwargs)
        else:
            with recorded_execution(req):recorded.complete(**kwargs)
    assert len(client.calls)==1 and len(list(recorded.root.glob('*/request.json')))==1

def test_actual_semantic_executor_records_identity_without_model_fields(tmp_path):
    from cgkn.executors.llm import LLMExecutor
    from tests.protocol.test_semantic_integration import request
    class Complete:
        def complete(self,**kwargs):return ProviderCompletion(json.dumps({'op':2,'path':0,'payload':'value=7\n'}),'fixture','r',{})
    store=FileRunStore(tmp_path/'state');rec=RecordedCompletionClient(Complete(),store,'p','r');events=[]
    result=invoke_bound_executor(LLMExecutor(tmp_path/'candidate',rec,ModelRoleConfig('worker','fixture'),semantic_protocol=True,protocol_trace=events.append), request())
    assert result.status==BlockStatus.SUCCEEDED
    row=json.loads(next(rec.root.glob('*/request.json')).read_text())
    assert row['execution_identity']=={'project_id':'p','run_id':'r','node_id':'n','attempt_id':'a'}
    assert 'execution_identity' not in row['request']

def test_old_reconciliation_cannot_authorize_new_unknown(tmp_path):
    store,client,recorded,req,kwargs,first,before=fixture(tmp_path)
    def unknown(**kwargs):
        client.calls.append(kwargs)
        raise GatewayCompletionError('provider_outcome_unknown','second unknown',outcome_unknown=True)
    client.complete=unknown
    with pytest.raises(GatewayCompletionError,match='provider_outcome_unknown'):
        with recorded_execution(req):recorded.complete(**kwargs)
    with pytest.raises(GatewayCompletionError,match='prior_submission_unknown'):
        with recorded_execution(req):recorded.complete(**kwargs)
    assert len(client.calls)==2
    assert len(list(recorded.root.glob('*/request.json')))==2


def test_execution_scope_thread_local_and_reset():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from cgkn.providers.recording import _EXECUTION
    barrier=Barrier(2)
    def worker(node):
        assert _EXECUTION.get() is None
        request=SimpleNamespace(project_id='p',run_id='r',node_id=node,attempt_id='a')
        with recorded_execution(request):
            barrier.wait(timeout=5)
            assert _EXECUTION.get()['node_id']==node
        assert _EXECUTION.get() is None
        return node
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert set(pool.map(worker,['A','B']))=={'A','B'}
    assert _EXECUTION.get() is None
