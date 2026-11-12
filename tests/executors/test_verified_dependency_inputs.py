from tests.executor_authority_support import invoke_bound_executor
import hashlib,json
import pytest
from cgkn.agent.composer import AgentComposer
from cgkn.protocol.compiler import compile_planner
from cgkn.protocol.repair import plain
from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus
from cgkn.executors.llm import LLMExecutor
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from tests.agent.test_milestone_dependency_reads import context

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def setup(tmp_path,raw=b'value = 7\r\n# \xe6\xb5\xb7'):
    ctx,dep,_=context();ctx.goal_acceptance['subject_identities'][dep]=hashlib.sha256(raw).hexdigest()
    t=AgentComposer._milestone_snapshot(ctx);p=dict(action=1,task_kind=2,target=0,scope=[0],deps=[],goal='Implement next',expected=['public source'],accept=['public source'])
    config=plain(compile_planner(p,t,bound_hash=t.hash,tree=ctx.tree,context_identity='fixture')['edits'][0].payload['config'])
    (tmp_path/dep).write_bytes(raw)
    req=BlockExecutionRequest(project_id='p',run_id='r',node_id='n',attempt_id='a',component_ref='code',executor_ref='llm.cheap@1',task_context=TaskContext('Implement next',config))
    return req,dep,config

def test_verified_input_bytes_reach_actual_semantic_worker_prompt_and_receipt(tmp_path):
    req,dep,config=setup(tmp_path);raw=(tmp_path/dep).read_bytes();seen=[]
    class Client:
        def complete(self,**kw):
            from tests.generation_migration_support import semantic_submission
            submitted=semantic_submission(kw)
            if submitted is not None:return submitted
            request=json.loads(kw['user']);seen.append(request)
            obs=request['context']['observations'][0]
            assert obs['path']==dep and obs['content']==raw.decode('utf8')
            assert obs['sha256']==hashlib.sha256(raw).hexdigest()
            assert obs['input_origin']=='verified_milestone_dependency'
            row=next(x for x in request['tables']['paths'] if x['path']==dep)
            assert row['readable'] and not row['writable']
            target=next(x for x in request['tables']['paths'] if x['writable'])
            return ProviderCompletion(json.dumps({'op':2,'path':target['id'],'payload':'value = 7\n'}),'fake','fake',{})
    result=invoke_bound_executor(LLMExecutor(tmp_path,Client(),ModelRoleConfig('worker','fake'),semantic_protocol=True,protocol_trace=lambda e:None), req)
    assert result.status==BlockStatus.SUCCEEDED and len(seen)==1
    assert result.outputs['action_results'][0]['content']==raw.decode('utf8')
    assert (tmp_path/dep).read_bytes()==raw

@pytest.mark.parametrize('case',['changed','unscoped','writable','binary'])
def test_invalid_bound_dependency_fails_before_model_call(tmp_path,case):
    req,dep,config=setup(tmp_path,b'\xff' if case=='binary' else b'value = 7\n')
    if case=='changed':(tmp_path/dep).write_bytes(b'changed')
    if case=='unscoped':config['leaf_contract']['read_scope']=[]
    if case=='writable':config['leaf_contract']['target_scope'].append(dep)
    req=BlockExecutionRequest(project_id='p',run_id='r',node_id='n',attempt_id='a',component_ref='code',executor_ref='llm.cheap@1',task_context=TaskContext('Implement next',config))
    class Never:
        def complete(self,**kw):raise AssertionError('invalid input must not dispatch model')
    result=LLMExecutor(tmp_path,Never(),ModelRoleConfig('worker','fake')).execute(req)
    assert result.status==BlockStatus.FAILED and result.error.code.value=='POLICY_BLOCKED'
    assert not result.usage


@pytest.mark.parametrize('existing',[True,False])
def test_full_file_repair_provides_existing_target_without_a_model_read(tmp_path,existing):
    req,dep,config=setup(tmp_path)
    config['repair_contract']={'strategy_semantics':{'full_file_write':True}}
    target=config['leaf_contract']['target_scope'][0]
    if existing:
        (tmp_path/target).parent.mkdir(parents=True,exist_ok=True)
        (tmp_path/target).write_bytes(b'value = 3\r\n')
    req=BlockExecutionRequest(project_id='p',run_id='r',node_id='n',attempt_id='a',component_ref='code',executor_ref='llm.cheap@1',task_context=TaskContext('Repair existing file',config))
    seen=[]
    class Client:
        def complete(self,**kw):
            from tests.generation_migration_support import semantic_submission
            submitted=semantic_submission(kw)
            if submitted is not None:return submitted
            packed=json.loads(kw['user'])
            def expand(value):
                if isinstance(value,dict):
                    if set(value)=={'$context_ref'}:
                        return expand(packed['context_values'][value['$context_ref']])
                    return {k:expand(v) for k,v in value.items()}
                if isinstance(value,list):return [expand(v) for v in value]
                return value
            request=expand(packed);seen.append(request)
            observations=request['context']['observations']
            current=[x for x in observations if x['path']==target]
            assert bool(current)==existing
            if existing:
                assert current[0]['content']=='value = 3\r\n'
                assert current[0]['input_origin']=='existing_repair_target'
                assert current[0]['sha256']==hashlib.sha256(b'value = 3\r\n').hexdigest()
            assert any(x['path']==dep for x in observations)
            row=next(x for x in request['tables']['paths'] if x['path']==target)
            assert ('observed_content_sha256' in row)==existing
            return ProviderCompletion(json.dumps({'op':2,'path':row['id'],'payload':'value = 8\n'}),'fake','fake',{})
    result=invoke_bound_executor(LLMExecutor(tmp_path,Client(),ModelRoleConfig('worker','fake'),semantic_protocol=True,protocol_trace=lambda e:None), req)
    assert result.status==BlockStatus.SUCCEEDED and len(seen)==1
    assert (tmp_path/target).read_text()=='value = 8\n'
