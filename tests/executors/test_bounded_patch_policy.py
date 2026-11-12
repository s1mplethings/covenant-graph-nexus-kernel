from tests.executor_authority_support import invoke_bound_executor
import hashlib
import json
from pathlib import Path
import pytest
from cgkn.executors.llm import plan_bounded_patches, ProposalError, LLMExecutor
from cgkn.execution import BlockExecutionRequest, TaskContext, BlockStatus
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from tests.executors.test_verified_dependency_inputs import setup


def fixture(tmp_path, raw=b'outside\r\nBEGIN\r\nvalue=1\r\nEND\r\noutside\r\n'):
    p=tmp_path/'file.py';p.write_bytes(raw)
    text=p.read_text(encoding='utf8')
    policy={'mode':'patch_only','files':{'file.py':{'source_sha256':hashlib.sha256(raw).hexdigest(),
        'ranges':[[text.index('BEGIN'),text.index('END')]],'max_changed_chars':100}}}
    return p,policy


def test_patch_has_bound_receipt_and_preserves_all_other_bytes(tmp_path):
    p,policy=fixture(tmp_path)
    outputs,receipts=plan_bounded_patches([{'action':'patch_file','path':'file.py','find':'value=1','replace':'value=2'}],tmp_path,policy)
    assert outputs['file.py']==p.read_bytes().replace(b'value=1',b'value=2')
    assert p.read_bytes()!=outputs['file.py']  # planner has no effects
    assert receipts[0]['before_sha256']!=receipts[0]['after_sha256']
    assert receipts[0]['changed_ranges'][0]['start_line']==3


@pytest.mark.parametrize('case,code',[('write','PATCH_SCOPE_EXCEEDED'),('outside','PATCH_SCOPE_EXCEEDED'),
    ('unchanged','NO_IMPLEMENTATION_DELTA'),('stale','OBJECT_VERSION_MISMATCH'),('budget','PATCH_SCOPE_EXCEEDED'),
    ('overlap','PATCH_SCOPE_EXCEEDED'),('traversal','path escapes'),('range','INVALID_PATCH_POLICY')])
def test_rejects_bad_patches_without_effect(tmp_path,case,code):
    p,policy=fixture(tmp_path);before=p.read_bytes()
    actions=[{'action':'patch_file','path':'file.py','find':'value=1','replace':'value=2'}]
    if case=='write':actions=[{'action':'write_file','path':'file.py','content':'replacement'}]
    if case=='outside':actions[0]['find']='END';actions[0]['replace']='OTHER'
    if case=='unchanged':actions[0]['replace']='value=1'
    if case=='stale':policy['files']['file.py']['source_sha256']='0'*64
    if case=='budget':policy['files']['file.py']['max_changed_chars']=1
    if case=='overlap':actions*=2
    if case=='traversal':actions[0]['path']='../file.py'
    if case=='range':policy['files']['file.py']['ranges']=[[True,900]]
    with pytest.raises((ProposalError,PermissionError),match=code):plan_bounded_patches(actions,tmp_path,policy)
    assert p.read_bytes()==before


def test_second_invalid_patch_does_not_apply_first(tmp_path):
    p,policy=fixture(tmp_path);before=p.read_bytes()
    with pytest.raises(ProposalError,match='PATCH_SCOPE_EXCEEDED'):
        plan_bounded_patches([{'action':'patch_file','path':'file.py','find':'value=1','replace':'value=2'},
            {'action':'patch_file','path':'file.py','find':'END','replace':'bad'}],tmp_path,policy)
    assert p.read_bytes()==before


def test_mixed_newlines_outside_patch_remain_byte_identical(tmp_path):
    p,policy=fixture(tmp_path,b'outside\r\r\nBEGIN\r\nvalue=1\nEND\rout\n')
    outputs,_=plan_bounded_patches([{'action':'patch_file','path':'file.py','find':'value=1','replace':'value=2'}],tmp_path,policy)
    assert outputs['file.py']==p.read_bytes().replace(b'value=1',b'value=2')


@pytest.mark.parametrize('limit,allowed',[(7,True),(6,False),(0,False),(True,False)])
def test_optional_anchor_budget_preserves_exact_match_and_atomicity(tmp_path,limit,allowed):
    p,policy=fixture(tmp_path);before=p.read_bytes()
    policy['files']['file.py']['max_anchor_chars']=limit
    actions=[{'action':'patch_file','path':'file.py','find':'value=1','replace':'value=2'}]
    if allowed:
        outputs,_=plan_bounded_patches(actions,tmp_path,policy)
        assert outputs['file.py']==before.replace(b'value=1',b'value=2')
    else:
        with pytest.raises(ProposalError,match='anchor'):
            plan_bounded_patches(actions,tmp_path,policy)
    assert p.read_bytes()==before


def test_stale_policy_stops_real_executor_before_client(tmp_path):
    req,dep,config=setup(tmp_path)
    target=config['leaf_contract']['target_scope'][0]
    p=tmp_path/target;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('value=1\n')
    class Never:
        def complete(self,**kw):raise AssertionError('must not dispatch')
    policy={'mode':'patch_only','files':{target:{'source_sha256':'0'*64,'ranges':[[0,7]],'max_changed_chars':100}}}
    result=invoke_bound_executor(LLMExecutor(tmp_path,Never(),ModelRoleConfig('worker','fake'),patch_policy=policy), req)
    assert result.status==BlockStatus.FAILED
    assert 'OBJECT_VERSION_MISMATCH' in result.error.message


@pytest.mark.parametrize('batch',[False,True])
def test_actual_semantic_worker_gets_patch_table_and_receipt(tmp_path,batch):
    req,dep,config=setup(tmp_path)
    target=config['leaf_contract']['target_scope'][0]
    p=tmp_path/target;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'value=1\r\nkeep=0\r\nother=2\r\n' if batch else b'value=1\r\n')
    config['repair_contract']={'strategy_semantics':{'full_file_write':True}}
    req=BlockExecutionRequest(project_id='p',run_id='r',node_id='n',attempt_id='a',component_ref='code',executor_ref='llm.cheap@1',task_context=TaskContext('Bounded patch',config))
    policy={'mode':'patch_only','files':{target:{'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'ranges':[[0,7],[15,22]] if batch else [[0,7]],'max_changed_chars':50}}}
    seen=[]
    class Client:
        def complete(self,**kw):
            from tests.generation_migration_support import semantic_submission
            submitted=semantic_submission(kw)
            if submitted is not None:return submitted
            packed=json.loads(kw['user'])
            def expand(v):
                if isinstance(v,dict):
                    if set(v)=={'$context_ref'}:return expand(packed['context_values'][v['$context_ref']])
                    return {k:expand(x) for k,x in v.items()}
                if isinstance(v,list):return [expand(x) for x in v]
                return v
            v=expand(packed);seen.append(v)
            assert v['tables']['allowed_write_operations']==[3]
            assert v['tables']['patch_batch_limit']==8
            assert v['context']['bounded_patch_policy']==policy
            row=next(x for x in v['tables']['paths'] if x['writable'])
            payload={'find':'value=1','replace':'value=2'}
            if batch:payload=[payload,{'find':'other=2','replace':'other=3'}]
            return ProviderCompletion(json.dumps({'op':3,'path':row['id'],'payload':payload}),'fake','fake',{})
    result=invoke_bound_executor(LLMExecutor(tmp_path,Client(),ModelRoleConfig('worker','fake'),semantic_protocol=True,protocol_trace=lambda e:None,patch_policy=policy), req)
    assert result.status==BlockStatus.SUCCEEDED
    assert p.read_bytes()==(b'value=2\r\nkeep=0\r\nother=3\r\n' if batch else b'value=2\r\n')
    assert result.metadata['bounded_patch_receipts'][0]['verdict']=='BOUNDED_PATCH_WITH_SOURCE_DELTA'
    assert len(result.metadata['bounded_patch_receipts'][0]['changed_ranges'])==(2 if batch else 1)

@pytest.mark.parametrize('case',['unqualified','too_many','bad_member','overlap','outside'])
def test_patch_batch_rejection_has_no_effect(tmp_path,case):
    from cgkn.protocol.compiler import TableSnapshot,compile_worker
    from cgkn.protocol.normalization import ContractError
    p,policy=fixture(tmp_path);before=p.read_bytes()
    table={'paths':[{'path':'file.py','readable':True,'writable':True}],'allowed_write_operations':[3],'patch_batch_limit':8}
    payload=[{'find':'value=1','replace':'value=2'}]
    if case=='unqualified':table.pop('patch_batch_limit')
    if case=='too_many':payload*=9
    if case=='bad_member':payload.append({'find':'BEGIN','replace':4})
    if case=='overlap':payload*=2
    if case=='outside':payload.append({'find':'END','replace':'OUTSIDE'})
    snapshot=TableSnapshot(table)
    with pytest.raises((ContractError,ProposalError)):
        result=compile_worker({'op':3,'path':0,'payload':payload},snapshot,bound_hash=snapshot.hash,node_id='n')
        plan_bounded_patches(result['actions'],tmp_path,policy)
    assert p.read_bytes()==before
