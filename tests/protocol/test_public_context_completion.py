import copy
import json
import pytest

from cgkn.protocol.adaptive_context import public_context_view,ContextPacker
from cgkn.protocol.exchange import complete_with_context
from cgkn.protocol.normalization import ContractError,digest
from cgkn.providers import ModelRoleConfig,ProviderCompletion


def document():
    return {'goal':'Keep the original whole goal','requirements':{'R':'exact public behavior'},
        'failure_details':{'node':'actual failure'},'execution_results':{'node':{
            'status':'FAILED','attempt_id':'a1','error':{'message':'actual failure'},
            'outputs':{'observed':'large raw data '*100},'metadata':{'receipt':'immutable'}}},
        'task_feedback':{'items':[{'identity':'identity','node_id':'node','attempt_id':'a1',
            'status':'FAILED','goal':'public behavior','receipt_ref':'attempts/node/a1.json',
            'receipt_sha256':'a'*64,'implementation_progress':{'raw':'public observation '*100}}]}}


def test_projection_preserves_goal_failure_and_exact_resolvable_observations():
    source=document();before=copy.deepcopy(source);view,resolver=public_context_view(source)
    assert source==before
    for key in ('goal','requirements','failure_details'):assert view[key]==source[key]
    item=view['execution_results']['node']
    assert item['status']=='FAILED' and item['error']==source['execution_results']['node']['error']
    full=resolver.resolve({'context_operation':'fetch_dependency_result','ref':item['result_ref'],'reason':'inspect exact failure'})
    assert full['value']==source['execution_results']['node'] and full['sha256']==item['result_sha256']
    feedback=view['task_feedback']['items'][0]
    assert feedback['receipt_sha256']=='a'*64 and feedback['identity']=='identity'
    full=resolver.resolve({'context_operation':'fetch_evidence','ref':feedback['detail_ref'],'reason':'inspect current public observations'})
    assert full['value']==source['task_feedback']['items']
    with pytest.raises(ContractError,match='CONTEXT_REF_NOT_AUTHORIZED'):
        resolver.resolve({'context_operation':'fetch_artifact','ref':'../../private','reason':'read'})


@pytest.mark.parametrize('role',['agent','worker'])
def test_acquisition_preserves_business_schema_and_accumulates_usage(role):
    view,resolver=public_context_view(document());calls=[]
    schema={'type':'object','required':['ok'],'properties':{'ok':{'type':'boolean'}},'additionalProperties':False}
    class Client:
        def complete(self,**request):
            calls.append(request);prompt=ContextPacker.restore(json.loads(request['user']))
            assert request['schema']['anyOf'][0]==schema
            if len(calls)==1:
                result={'context_operation':'fetch_dependency_result','ref':view['execution_results']['node']['result_ref'],'reason':'read complete observation'}
            else:
                evidence=next(iter(prompt['fetched_context'].values()))
                assert evidence['value']==document()['execution_results']['node']
                assert evidence['sha256']==digest(evidence['value'])
                result={'ok':True}
            return ProviderCompletion(json.dumps(result),'fixture','call-'+str(len(calls)),{'input_tokens':2,'output_tokens':1},1)
    result=complete_with_context(Client(),resolver=resolver,system='bounded',user=json.dumps(view),
        schema_name='original',schema=schema,config=ModelRoleConfig(role,'fixture'))
    assert json.loads(result.text)=={'ok':True} and len(calls)==2
    assert result.usage=={'input_tokens':4,'output_tokens':2} and result.attempts==2


@pytest.mark.parametrize('limit,expected,calls_expected',[(0,'BUDGET_EXHAUSTED',1),(3,'REPEATED',2)])
def test_fetch_cannot_repeat_or_exceed_its_call_bound(limit,expected,calls_expected):
    view,resolver=public_context_view(document());calls=[]
    class Client:
        def complete(self,**request):
            calls.append(request)
            return ProviderCompletion(json.dumps({'context_operation':'fetch_dependency_result',
                'ref':view['execution_results']['node']['result_ref'],'reason':'read'}),'fixture')
    with pytest.raises(ContractError,match=expected):
        complete_with_context(Client(),resolver=resolver,max_context_expansions=limit,system='bounded',
            user=json.dumps(view),schema_name='original',schema={'type':'object'},config=ModelRoleConfig('agent','fixture'))
    assert len(calls)==calls_expected


def test_missing_usage_in_context_fetch_is_not_reported_as_complete_total():
    view,resolver=public_context_view(document());calls=[]
    class Client:
        def complete(self,**request):
            calls.append(request)
            value=({'context_operation':'fetch_dependency_result',
                'ref':view['execution_results']['node']['result_ref'],'reason':'inspect'}
                if len(calls)==1 else {'ok':True})
            usage={} if len(calls)==1 else {'input_tokens':8,'output_tokens':2}
            return ProviderCompletion(json.dumps(value),'fixture',usage=usage)
    result=complete_with_context(Client(),resolver=resolver,system='bounded',
        user=json.dumps(view),schema_name='original',schema={'type':'object'},
        config=ModelRoleConfig('agent','fixture'))
    assert len(calls)==2
    assert result.usage=={'input_tokens':None,'output_tokens':None}


def test_action_composer_keeps_full_failures_and_fetches_exact_prior_result():
    from cgkn.agent.action_composer import ActionComposer
    from cgkn.agent.composer import AgentDecisionContext
    from cgkn.orchestration import CapabilityTree
    failure={'error':{'message':'failure details '*1000},'evidence':'must remain visible'}
    result={'status':'FAILED','error':failure['error'],'outputs':{'raw':'observed '*6000}}
    context=AgentDecisionContext('p','r','Original goal',1,CapabilityTree('Original goal',()),(),
        capability_catalog={},run_summary={},failure_details={'n':failure},execution_results={'n':result})
    requests=[]
    class Client:
        def complete(self,**request):
            prompt=ContextPacker.restore(json.loads(request['user']));requests.append(prompt)
            assert prompt['goal']=='Original goal'
            assert prompt['failure_details']['n']==failure
            if len(requests)==1:
                value={'context_operation':'fetch_dependency_result',
                    'ref':prompt['execution_results']['n']['result_ref'],'reason':'inspect full output'}
            else:
                assert next(iter(prompt['fetched_context'].values()))['value']==result
                value=dict(summary='inspected',operation='finish',capability='',config={},depends_on=[],node_id='')
            return ProviderCompletion(json.dumps(value),'fixture')
    decision=ActionComposer(Client(),ModelRoleConfig('agent','fixture')).decide(context)
    assert decision.finish and len(requests)==2
