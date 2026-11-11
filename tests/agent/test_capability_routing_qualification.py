from tests.executor_authority_support import invoke_bound_executor
import json
from dataclasses import asdict
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest
from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode, BlockExecutionRequest, TaskContext
from cgkn.executors.task_evaluation import TaskEvaluationExecutor
from cgkn.executors.llm import LLMExecutor
from cgkn.providers import ModelRoleConfig,ProviderCompletion
from cgkn.state import FileRunStore
from cgkn.state.task_feedback import TaskFeedback,digest
from cgkn.state.capability_ledger import CapabilityLedger,deterministic_facts
from cgkn.state.acceptance import GoalAcceptance,identity
from cgkn.orchestration.capability_tree import CapabilityNode,CapabilityTree
from cgkn.orchestration.leaf_contract import build_leaf_contract
SCOPE={"artifact_domain":"json-document","environment":"local-test","tool_identity":"llm.cheap@1"}


def attempt(store,run,config,domain='NONE',task_class='json',meta=False):
    f=TaskFeedback(store,'p',run)
    error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'controlled',{'failure_domain':domain,'outcome_unknown':domain=='UNKNOWN'}) if domain in {'TRANSPORT','HARNESS','UNKNOWN'} else None
    result=BlockExecutionResult(project_id='p',run_id=run,node_id='work',attempt_id='attempt-0001',executor_ref='fixture@1',
        status=BlockStatus.FAILED if error else BlockStatus.SUCCEEDED,error=error,
        usage={'model':config.model_id,'config_hash':digest(asdict(config)),'routing':{'provider_id':config.model,'requested_model':config.model_id,'bound_model':config.model_id,'actual_model':config.model_id,'identity_status':'MATCH'}},outputs={'private':'HIDDEN CHECKER CONTENT'})
    store.save_result(result)
    node=CapabilityNode('work',capability_ref=task_class,config={'task_class':task_class,'meta_operation':meta,'operation':'inspect',**SCOPE})
    fact=f.terminal(result,node)
    a=GoalAcceptance(store,'p',run,{'R':{'must':True}},{'c':'fixture@1'});a.bind_subjects({'object':'v1'})
    a.commit(a.propose({'phases':[{'id':'phase','depends_on':[]}],'goals':[{'id':'g','phase_id':'phase','requirement_refs':['R'],'acceptance':'fixture','subject_refs':['object'],'checker':'c','task_refs':['work']}]},CapabilityTree('g',(node,))))
    if domain in {'NONE','BUSINESS'}:
        checked=BlockExecutionResult(project_id='p',run_id=run,node_id='check',attempt_id='attempt-0001',executor_ref='fixture@1',status=BlockStatus.SUCCEEDED,
            outputs={'goal_check':{'goal_id':'g','condition_hash':identity('fixture'),'subjects':{'object':'v1'},'execution':'VALID','evidence_refs':['actual-fixture-check'],
                'observed':'controlled qualification only','verdict':'VERIFIED' if domain=='NONE' else 'FAILED','task_receipts':[digest(result.as_dict())]}})
        from tests.governed_measurement_support import execute_measurement
        control=store.run_dir('p',run)/'routing-control.json'
        store.immutable_json(control,{'verdict': 'VERIFIED' if domain=='NONE' else 'FAILED'})
        request=BlockExecutionRequest(project_id='p',run_id=run,node_id='check',attempt_id='attempt-0001',
            executor_ref='fixture@1',component_ref='routing.measurement@1',task_context=TaskContext('Measure fixture control',{}))
        def observe():
            assert checked.outputs['goal_check']['verdict']==json.loads(control.read_text())['verdict']
            return checked
        checked=execute_measurement(store,request,control,observe)
        store.save_result(checked);a.record('g',checked,executor_ref='fixture@1')
    return f,fact,a


class Evaluator:
    def __init__(self,wrong=False):self.calls=[];self.wrong=wrong
    def complete(self,**kw):
        self.calls.append(kw);p=json.loads(kw['user']);f=p['receipt'];assert 'HIDDEN CHECKER CONTENT' not in kw['user']
        value=dict(observations='public receipt',evidence_refs=f['evidence_refs'],hypothesis='UNKNOWN',uncertainty='bounded evidence only',required_capabilities=[f['task_class']],candidate_lesson='Respect the public contract',recommendation='',
            evaluation_id=kw['schema']['properties']['evaluation_id']['const'],source_attempt_id=f['attempt_id'],capability_tags=[f['task_class']],outcome_interpretation=f['acceptance_result'],failure_domain='BUSINESS' if self.wrong else f['failure_domain'],failure_reason_summary='UNKNOWN',confidence=.6,informative_for_routing=f['failure_domain'] in {'BUSINESS','NONE'},why_this_recommendation='Only independently checked facts support routing',unresolved_questions=['root cause unknown'])
        return ProviderCompletion(json.dumps(value),'small-evaluator',usage={'input_tokens':10,'output_tokens':20})


def evaluate(store,f,fact,a,client=None,revision=1):
    client=client or Evaluator();ex=TaskEvaluationExecutor(store,client,ModelRoleConfig('worker','fake'),acceptance=a)
    req=SimpleNamespace(project_id='p',run_id=f.run_id,node_id='evaluate',attempt_id='attempt-0001',executor_ref='task.evaluate@1',input_values={'feedback_identity':fact['identity'],'evaluation_contract':'2','evaluation_revision':revision})
    return invoke_bound_executor(ex, req),client


def test_evaluation_changes_next_real_executor_route_only_for_supported_class(tmp_path):
    store=FileRunStore(tmp_path/'state');ledger=CapabilityLedger(store,'p')
    configs={'default':ModelRoleConfig('worker','P',model_id='M1'),'supported':ModelRoleConfig('worker','P',model_id='M2')}
    assert ledger.route('json',configs,'default',operation='inspect',capability_scope=SCOPE)['selected_config']=='default'
    for i in range(3):
        f,fact,a=attempt(store,'r'+str(i),configs['supported']);r,c=evaluate(store,f,fact,a);assert r.status==BlockStatus.SUCCEEDED
        again,_=evaluate(store,f,fact,a,c);assert again.status==BlockStatus.SUCCEEDED and len(c.calls)==1
        if i<2:assert ledger.route('json',configs,'default',operation='inspect',capability_scope=SCOPE)['selected_config']=='default'
    assert ledger.route('json',configs,'default',operation='inspect',capability_scope=SCOPE)['selected_config']=='supported'
    assert ledger.route('sql',configs,'default',operation='inspect',capability_scope=SCOPE)['selected_config']=='default'
    calls=[]
    class Worker:
        def complete(self,**kw):
            calls.append(kw);p=json.loads(kw['user']);return ProviderCompletion(json.dumps(dict(schema_version='1.0',node_id=p['node_id'],summary='fixture',actions=[],expected_outputs=[],confidence=.5,needs_escalation=False,escalation_reason='')),kw['config'].model_id)
    ex=LLMExecutor(tmp_path,Worker(),configs['default'],capability_ledger=ledger);ex.model_configs=configs
    request=BlockExecutionRequest(project_id='p',run_id='next',node_id='next',attempt_id='attempt-0001',executor_ref='llm.cheap@1',component_ref='json',task_context=TaskContext(node_goal='bounded',node_config={'model_config_id':'default','task_class':'json','operation':'inspect',**SCOPE,'leaf_contract':build_leaf_contract(goal='Inspect a bounded JSON document',kind='INSPECTION',scope=['document.json'],acceptance=['document-shape'],checker='fixture.document',output_identity='document',effect_domains=['json'],executor='llm.cheap@1',subject='document.json',expected_observation='document fields',pass_fail_rule='independent schema inspection')}))
    result=invoke_bound_executor(ex, request);assert result.status==BlockStatus.SUCCEEDED and calls[0]['config'].model_id=='M2'
    assert result.usage['route_decision']['evidence_refs']
    f,fact,a=attempt(store,'contradiction',configs['supported'],domain='BUSINESS');assert evaluate(store,f,fact,a)[0].status==BlockStatus.SUCCEEDED
    assert ledger.route('json',configs,'default',operation='inspect',capability_scope=SCOPE)['selected_config']=='default'


@pytest.mark.parametrize('domain',['UNKNOWN','TRANSPORT','HARNESS'])
@pytest.mark.boundary
@pytest.mark.negative
def test_nonbusiness_not_charged_to_model_ability_and_evaluator_cannot_override(tmp_path,domain):
    store=FileRunStore(tmp_path);config=ModelRoleConfig('worker','P',model_id='M');f,fact,a=attempt(store,'r',config,domain)
    before=(f.root/fact['receipt_ref']).read_bytes()
    assert evaluate(store,f,fact,a,Evaluator(wrong=True))[0].status==BlockStatus.FAILED
    assert (f.root/fact['receipt_ref']).read_bytes()==before
    # Invalid response retained; explicit new revision must not silently replay it.
    assert f.attempt(fact['identity'])['evaluation'] is None
    f2,fact2,a2=attempt(store,'new-r',config,domain);assert evaluate(store,f2,fact2,a2)[0].status==BlockStatus.SUCCEEDED
    g=CapabilityLedger(store,'p').view()['records'][0]
    assert g['failed_business']==g['accepted']==g['qualified_attempts']==0
    assert g[{'UNKNOWN':'unknown','TRANSPORT':'transport_failed','HARNESS':'harness_invalid'}[domain]]==1


@pytest.mark.boundary
@pytest.mark.happy_path
def test_concurrent_ledger_publication_and_revision_history(tmp_path):
    store=FileRunStore(tmp_path);config=ModelRoleConfig('worker','P',model_id='M')
    fixtures=[attempt(store,'r'+str(i),config) for i in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda f:evaluate(store,*f)[0],fixtures))
    assert all(r.status==BlockStatus.SUCCEEDED for r in results)
    ledger=CapabilityLedger(store,'p');assert ledger.view()['records'][0]['attempts']==8
    f,fact,a=fixtures[0];assert evaluate(store,f,fact,a,revision=2)[0].status==BlockStatus.SUCCEEDED
    assert evaluate(store,f,fact,a,revision=1)[0].status==BlockStatus.SUCCEEDED
    assert ledger.view()['records'][0]['attempts']==8
    assert len(list((ledger.root/fact['identity']).glob('*.json')))==2
    assert next(r for r in ledger.records() if r['facts']['source_identity']==fact['identity'])['revision']==2
    f,fact,a=attempt(store,'meta',config,meta=True);assert evaluate(store,f,fact,a)[0].status==BlockStatus.FAILED
