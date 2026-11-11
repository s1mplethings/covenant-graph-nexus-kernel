import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from cgkn.execution.check_evidence import evaluate, StagnationGuard
from cgkn.agent.action_composer import ActionComposer
from cgkn.agent.composer import AgentDecisionContext
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from experiments.product_dev_113.budget_policy import BoundedClient

def test_evidence_conditions_and_invalid_injection():
    r=dict(requirement_ref='R1',requirement_version='v1',artifact_hash='a',checker='x',check_version='1',environment_hash='e',expected=1,observed=1,evidence_ref='raw',check_execution='VALID',verdict='VERIFIED')
    args=dict(artifact_hash='a',requirement_version='v1',environment_hash='e')
    assert evaluate(r,**args)['verdict']=='VERIFIED'
    assert evaluate(r,**{**args,'artifact_hash':'b'})['verdict']=='INSUFFICIENT_EVIDENCE'
    assert evaluate({**r,'check_execution':'INVALID','verdict':'FAILED'},**args)['verdict']=='INSUFFICIENT_EVIDENCE'
    assert evaluate({**r,'verdict':'FAILED'},**args)['next_action']=='REPAIR'

def test_stagnation_requires_same_bound_evidence():
    g=StagnationGuard();kw=dict(issue='i',artifact_hash='a',assertion='x',evidence_hash='raw',strategy='s')
    assert g.observe(**kw)=='CONTINUE'
    assert g.observe(**kw)=='CHANGE_STRATEGY'
    assert g.observe(**kw)=='BLOCK_REPETITION'
    assert g.observe(**{**kw,'artifact_hash':'changed'})=='CONTINUE'

def test_switch_retains_full_goal_and_success_failure():
    class Fake:
        def complete(self,**kw):
            self.payload=json.loads(kw['user'])
            return ProviderCompletion(json.dumps(dict(summary='select alternative',operation='switch_model',capability='',config={'model':'grok'},depends_on=[],node_id='')),'qwen','r')
    f=Fake();c=ActionComposer(f,ModelRoleConfig('agent','qwen'))
    c.set_runtime_context(lambda:{'notes':'model authored plan','budget':7},['qwen','deepseek','grok'])
    context=AgentDecisionContext('p','r','entire goal',1,CapabilityTree('entire goal',()),(),{}, {}, {'failure':'raw'}, {'n1':{'status':'SUCCEEDED','outputs':{'stdout':'saved'}}})
    d=c.decide(context)
    assert c.config.model=='grok' and not d.request_run and not d.edits
    assert f.payload['goal']=='entire goal' and f.payload['durable_state']['budget']==7
    assert f.payload['execution_results']['n1']['outputs']['stdout']=='saved'

def test_shared_transport_admission_is_serial_even_with_two_submitters():
    import time,threading
    client=object.__new__(BoundedClient);client.count=0;client.active=0;client.peak=0;client.unavailable=set()
    def call(**kwargs):
        client.active+=1;client.peak=max(client.active,client.peak)
        if client.count>=1:
            client.active-=1;return 'LIMIT'
        client.count+=1;time.sleep(.03);client.active-=1;return 'SENT'
    client._complete=call
    with ThreadPoolExecutor(2) as pool:values=list(pool.map(lambda _:client.complete(config=ModelRoleConfig("agent","deepseek")),range(2)))
    assert sorted(values)==['LIMIT','SENT'] and client.peak==1

def test_actual_composer_repeat_switch_block_and_artifact_invalidation():
    import pytest
    from cgkn.agent.composer import AgentDecisionValidationError
    class Fake:
        def complete(self, **kw):
            return ProviderCompletion(json.dumps(dict(summary='observe',operation='execute',capability='file',config={'action':'read_file','path':'a'},depends_on=[],node_id='')),kw['config'].model,'r')
    c=ActionComposer(Fake(),ModelRoleConfig('agent','deepseek'))
    version=['one']
    c.set_runtime_context(lambda:{'raw_state':{'stdout':json.dumps({'artifact_hash':version[0]})}},['deepseek','grok'])
    base=AgentDecisionContext('p','r','goal',1,CapabilityTree('goal',()),('file',),{'file':{'executor_ref':'isolated.file'}},{},{},{})
    c.decide(base)
    observed=replace(base,run_summary={'actual_executions':['n']},execution_results={'n':{'status':'SUCCEEDED','outputs':{'stdout_hash':'same','stdout':'data'}}})
    c.decide(observed)
    c.decide(observed)
    assert c.config.model=='grok'
    with pytest.raises(AgentDecisionValidationError,match='STAGNATION_BRANCH_BLOCKED'):
        c.decide(observed)
    version[0]='two'
    assert c.decide(observed).request_run
