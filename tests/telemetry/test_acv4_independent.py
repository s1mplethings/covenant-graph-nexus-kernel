from tests.qualification_support import probe_node
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import replace

import pytest

CONFIG={'actual_model':'fixture-model','model_version':'1','task_family':'fixture','difficulty':'fixed','tools':'local','context':'public','repair_protocol':'one-attempt'}

from cgkn.telemetry.effectiveness import beta_lower, effectiveness, task_cost, task_time, utility
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.orchestration.capability_tree import CapabilityTree


def measured_control(acceptance,template):
    """Execute a frozen aggregation control through actual Host Admission."""
    from cgkn.execution import BlockExecutionRequest,TaskContext
    from tests.governed_measurement_support import execute_measurement
    path=acceptance.root/'aggregation-controls'/template.node_id/(template.attempt_id+'.json')
    acceptance.store.immutable_json(path,template.as_dict()['outputs'])
    request=BlockExecutionRequest(project_id=template.project_id,run_id=template.run_id,
        node_id=template.node_id,attempt_id=template.attempt_id,executor_ref=template.executor_ref,
        component_ref='aggregation.measure@1',task_context=TaskContext('Read frozen aggregation control',{}))
    return execute_measurement(acceptance.store,request,path,
        lambda:replace(template,outputs=json.loads(path.read_text(encoding='utf-8'))))


def test_I0_retained_entrypoints():
    from cgkn.executors.measurement import FileMeasurementExecutor
    from cgkn.providers.gateway_client import GatewayCompletionClient
    from cgkn.runtime import DAGRunner
    assert FileMeasurementExecutor.descriptor.executor_ref == 'measure.file@1'
    assert callable(GatewayCompletionClient.recover_cached) and callable(DAGRunner.run)
    assert GatewayCompletionClient('http://127.0.0.1:8765','fixture-not-a-secret').base_url=='http://127.0.0.1:8765'
    from pathlib import Path
    config=json.loads((Path(__file__).resolve().parents[2]/'config/provider_profiles/domestic_model_routing.json').read_text(encoding='utf-8'))
    assert isinstance(config,dict) and config


def test_I1_original_denominator_and_empty_required(tmp_path):
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',{'R':{'must':True}}, {'checker':'check@1'})
    assert a.view()['uncovered_must']==['R'] and not a.view()['complete']
    assert a.view()['hard_verdict']=='INSUFFICIENT_EVIDENCE'
    with pytest.raises(ValueError):
        GoalAcceptance(FileRunStore(tmp_path),'p','other',{'R':{'must':True,'weight':float('nan')}},{})
    empty=GoalAcceptance(FileRunStore(tmp_path),'p','empty',{}, {})
    assert not empty.view()['complete'] and empty.view()['completion'] is None


@pytest.mark.parametrize('value,expected_status,expected_verdict',[(7,'SUCCEEDED','VERIFIED'),(8,'SUCCEEDED','FAILED')])
@pytest.mark.boundary
@pytest.mark.happy_path
def test_I2_real_file_predicate(tmp_path,value,expected_status,expected_verdict):
    from cgkn.executors.measurement import FileMeasurementExecutor
    from cgkn.execution import BlockExecutionRequest, TaskContext
    path=tmp_path/'object.json';path.write_text(json.dumps({'value':value}))
    contract={'goal_id':'g','version':'1','path':'object.json','field':'value','subject':'object',
              'artifact_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'predicate':{'operator':'equal','expected':7}}
    executor=FileMeasurementExecutor(tmp_path,{'c':contract})
    request=BlockExecutionRequest(project_id='p',run_id='r',node_id='check',attempt_id='a',
        component_ref='measure.file@1',executor_ref='measure.file@1',input_values={'contract_id':'c'},
        task_context=TaskContext(node_goal='measure'))
    from cgkn.executors import ExecutorRegistry
    registry=ExecutorRegistry();registry.register(executor)
    result=registry.resolve('measure.file@1','measure.file@1').execute(request)
    assert result.status.value==expected_status and result.outputs['goal_check']['verdict']==expected_verdict
    path.write_text('{"value":9}')
    assert executor.execute(request).outputs['goal_check']['verdict']=='INSUFFICIENT_EVIDENCE'
    path.write_text('invalid JSON')
    assert executor.execute(request).status.value=='FAILED'


def test_I3_requirement_weight_projection_and_reopen(tmp_path):
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',{str(i):{'must':True} for i in range(10)}, {'c':'check@1'})
    # Independent frozen evidence fixture, not a claimed executed business task.
    a.bind_subjects({'object':'v1'})
    goals=[{'id':str(i),'requirement_refs':[str(i)],'phase_id':'p','subject_refs':['object'],
            'checker':'c','acceptance':'predicate','task_refs':[]} for i in range(10)]
    a.commit(a.propose({'goals':goals,'phases':[{'id':'p','depends_on':[]}]},CapabilityTree('g',())))
    from cgkn.state.acceptance import identity
    for i in range(9):
        from cgkn.execution import BlockExecutionResult, BlockStatus
        receipt=BlockExecutionResult(project_id='p',run_id='r',node_id='check'+str(i),attempt_id='attempt-0001',executor_ref='check@1',status=BlockStatus.SUCCEEDED,
            outputs={'goal_check':{'goal_id':str(i),'subjects':{'object':'v1'},'condition_hash':identity('predicate'),
            'execution':'VALID','evidence_refs':['synthetic-observation-'+str(i)],'verdict':'VERIFIED' if i<8 else 'FAILED','observed':{'fixture':True}}})
        receipt=measured_control(a,receipt)
        a.store.save_result(receipt)
        a.record(str(i),receipt,executor_ref='check@1')
    a.save();view=a.view()
    assert view['completion']==.8 and view['evidence_coverage']==.9 and view['hard_verdict']=='FAILED'
    b=GoalAcceptance(a.store,'p','r',a.requirements,a.checkers)
    assert b.view()==view
    b.bind_subjects({'object':'v2'})
    assert b.view()['evidence_coverage']==0 and not b.view()['complete']


def test_I4_metering_identity_and_censoring():
    base={'currency':'CNY','price_version':'fixed-v1','cost_kind':'estimate','outcome':'KNOWN'}
    a=dict(base,call_id='a',amount='.2');b=dict(base,call_id='b',amount='.3')
    assert task_cost([a,a,b],currency='CNY',price_version='fixed-v1')['complete_total']=='0.5'
    unknown=dict(base,call_id='c',amount=None,outcome='UNKNOWN')
    assert task_cost([a,unknown],currency='CNY',price_version='fixed-v1')['complete_total'] is None
    retained=task_cost([a,dict(unknown,amount='.4')],currency='CNY',price_version='fixed-v1')
    assert retained['known_total']=='0.6' and retained['complete_total'] is None
    with pytest.raises(ValueError):task_cost([a,dict(a,amount='.4')],currency='CNY',price_version='fixed-v1')
    t=task_time(ready=0,ended=7,now=7,clock_id='clock',intervals=[{'start':0,'end':5,'clock_id':'clock'},{'start':2,'end':7,'clock_id':'clock'}])
    assert t['complete_duration']==7 and t['branch_execution_sum']==10
    assert task_time(ready=0,ended=None,now=5,clock_id='clock',intervals=[])['complete_duration'] is None


def test_I5_reference_math_and_cohort():
    assert beta_lower(0,0)==pytest.approx(.05)
    assert beta_lower(1,0)==pytest.approx(math.sqrt(.05))
    assert beta_lower(0,1)==pytest.approx(1-math.sqrt(.95))
    for t,c,want in [(10,1,45),(20,1,36),(10,2,36),(0,0,90)]:
        assert utility(.9,t,c,time_reference=10,cost_reference=1)==pytest.approx(want)
    sample={'task_id':'a','revision':1,'configuration':CONFIG,'model_confirmed':True,
            'delivery':1,'business':1,'acceptance_ref':'receipt','duration':10,'cost':1}
    kwargs={'task_ids':['a','b'],'configuration':sample['configuration'],'time_reference':10,'cost_reference':1}
    result=effectiveness([sample,sample],**kwargs)
    assert result['status']=='PROVISIONAL' and result['successes']==1 and result['settled_task_ids']==['a']
    revision=dict(sample,revision=2,supersedes=1,delivery=0,business=0)
    assert effectiveness([revision,sample],**kwargs)['failures']==1
    assert effectiveness([],**kwargs)['utility'] is None


@pytest.mark.parametrize('bad',[None,-1,float('nan'),float('inf')])
def test_I5_invalid_cost_not_zero(bad):
    with pytest.raises((ValueError,TypeError)):
        utility(.9,10,bad,time_reference=10,cost_reference=1)


def test_I6_actual_dependency_closure():
    from cgkn.orchestration.capability_tree import CapabilityNode
    from cgkn.orchestration.execution_dag import compile_tree
    from cgkn.orchestration.invalidation import invalidate_affected_subgraph
    tree=CapabilityTree('g',tuple(probe_node(n,capability_ref='c',depends_on=deps) for n,deps in
        [('money',()),('database',('money',)),('summary',('money',)),('syntax',())]))
    assert set(invalidate_affected_subgraph(compile_tree(tree),{'money'}))=={'money','database','summary'}


def test_I7_readonly_cli_does_not_change_source_or_configuration(tmp_path):
    frozen=tmp_path/'active.json';frozen.write_text('{"routing":"unchanged","knowledge":"frozen"}')
    source=tmp_path/'input.json';source.write_text(json.dumps({'ready':0,'ended':7,'now':7,'intervals':[],'clock_id':'c'}))
    before={p:p.read_bytes() for p in (frozen,source)}
    result=tmp_path/'result.json'
    subprocess.run([sys.executable,'-c',"import socket,runpy; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); runpy.run_module('scripts.task_metrics',run_name='__main__')",'time','--input',str(source),'--output',str(result)],check=True)
    assert json.loads(result.read_text())['complete_duration']==7
    assert all(p.read_bytes()==v for p,v in before.items())


def test_I3_explicit_recheck_and_late_independent_pass(tmp_path):
    from cgkn.execution import BlockExecutionResult,BlockStatus
    from cgkn.state.acceptance import identity
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',{'R':{'must':True}},{'c':'check@1'})
    a.bind_subjects({'object':'v1'})
    g={'id':'g','requirement_refs':['R'],'phase_id':'p','subject_refs':['object'],'checker':'c','acceptance':'predicate','task_refs':[]}
    a.commit(a.propose({'goals':[g],'phases':[{'id':'p','depends_on':[]}]},CapabilityTree('g',())))
    def add(node,verdict,supersedes=()):
        result=BlockExecutionResult(project_id='p',run_id='r',node_id=node,attempt_id='attempt-0001',executor_ref='check@1',status=BlockStatus.SUCCEEDED,
            outputs={'goal_check':{'goal_id':'g','subjects':{'object':'v1'},'condition_hash':identity('predicate'),'execution':'VALID',
            'evidence_refs':['controlled-observation'],'observed':{'value':verdict},'verdict':verdict,'supersedes_receipts':list(supersedes)}})
        result=measured_control(a,result)
        a.store.save_result(result);return a.record('g',result,executor_ref='check@1')
    failed=add('failed','FAILED');add('late_old_pass','VERIFIED')
    assert a.view()['hard_verdict']=='FAILED'
    add('verified_repair','VERIFIED',[failed['receipt_hash']])
    assert a.view()['complete'] and len(a.data['checks'])==3
    with pytest.raises(ValueError):add('wrong_supersession','VERIFIED',['another-goal'])


def test_I4_purpose_not_role_and_distinct_retries():
    from cgkn.telemetry.effectiveness import request_counts
    a={'request_id':'a','schema':'evaluation','role':'worker','logical_task_id':'t'}
    b=dict(a,request_id='b',schema='worker_proposal')
    result=request_counts([a,a,b])
    assert result['application_requests']==2 and result['logical_tasks']==1
    assert result['purposes']=={'evaluation':1,'worker_proposal':1}
    assert result['upstream_http_requests'] is None


def test_I5_fixed_cohort_same_set_and_invalid_parameters():
    base={'revision':1,'configuration':CONFIG,'model_confirmed':True,'business':1,'delivery':1,'acceptance_ref':'checked','duration':10,'cost':1}
    rows=[dict(base,task_id='ok'),dict(base,task_id='fail',business=None,delivery=0,duration=20,cost=2),
          dict(base,task_id='unknown',business=None,delivery=None,duration=None),dict(base,task_id='unpriced',cost=None)]
    report=effectiveness(rows,task_ids=['ok','fail','unknown','unpriced'],configuration=CONFIG,time_reference=10,cost_reference=1)
    assert report['settled_task_ids']==['ok','fail'] and report['mean_time']==15 and report['mean_cost']==1.5
    assert report['successes']==report['failures']==1 and len(report['pending'])==2 and report['status']=='PROVISIONAL'
    for kwargs in [dict(time_reference=0,cost_reference=1),dict(time_reference=1,cost_reference=1,time_weight=.8,cost_weight=.8)]:
        with pytest.raises(ValueError):utility(.9,1,1,**kwargs)
    assert utility(.9,600,100,time_reference=600,cost_reference=100)==utility(.9,10,1,time_reference=10,cost_reference=1)


def test_I1_parent_integration_cannot_be_outvoted_and_mapping_not_weakened(tmp_path):
    from cgkn.state.acceptance import identity
    from cgkn.execution import BlockExecutionResult,BlockStatus
    req={'parent':{'must':True,'children':['leaf'],'operator':'AND'},'leaf':{'must':True}}
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',req,{'c':'check@1'});a.bind_subjects({'object':'v1'})
    goals=[{'id':r,'requirement_refs':[r],'phase_id':'p','subject_refs':['object'],'checker':'c','acceptance':'frozen','task_refs':[]} for r in req]
    plan={'goals':goals,'phases':[{'id':'p','depends_on':[]}]};a.commit(a.propose(plan,CapabilityTree('g',())))
    for goal,verdict in [('parent','FAILED'),('leaf','VERIFIED')]:
        result=BlockExecutionResult(project_id='p',run_id='r',node_id=goal,attempt_id='a',executor_ref='check@1',status=BlockStatus.SUCCEEDED,
            outputs={'goal_check':{'goal_id':goal,'subjects':{'object':'v1'},'condition_hash':identity('frozen'),'execution':'VALID','evidence_refs':['fixture'],'observed':{'actual':verdict},'verdict':verdict}})
        result=measured_control(a,result)
        a.store.save_result(result);a.record(goal,result,executor_ref='check@1')
    assert a.view()['hard_verdict']=='FAILED'
    changed=json.loads(json.dumps(plan));changed['goals'][0]['acceptance']='easier'
    with pytest.raises(ValueError,match='weakened'):a.propose(changed,CapabilityTree('g',()))
    duplicate=json.loads(json.dumps(plan));duplicate['goals'][0]['requirement_refs']=['parent','parent']
    with pytest.raises(ValueError):a.propose(duplicate,CapabilityTree('g',()))


def test_I6_checker_change_requires_recheck_not_generation(tmp_path):
    from cgkn.orchestration.capability_tree import CapabilityNode
    from cgkn.orchestration.execution_dag import compile_tree
    tree=CapabilityTree('g',(probe_node('producer',capability_ref='c'),))
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',{'R':{'must':True}},{'c':'check@1'});a.bind_subjects({'object':'v1'})
    plan={'phases':[{'id':'p','depends_on':[]}],'goals':[{'id':'g','requirement_refs':['R'],'phase_id':'p','subject_refs':['object'],'checker':'c','acceptance':'fixed','task_refs':['producer']}]}
    a.commit(a.propose(plan,tree))
    impact=a.revalidation_scope(compile_tree(tree),changed_checkers=['c'])
    assert impact['affected_tasks']==[] and impact['recheck_goals']==['g']


def test_I5_properties_and_stable_presentation():
    from cgkn.telemetry.effectiveness import rank_reports
    assert utility(.93,12,.8,time_reference=10,cost_reference=1)==pytest.approx(46.5)
    assert utility(.91,6,1.2,time_reference=10,cost_reference=1)==pytest.approx(47.89473684210526)
    assert utility(.8,2,1,time_reference=10,cost_reference=1)<=utility(.9,2,1,time_reference=10,cost_reference=1)
    assert utility(.9,2,2,time_reference=10,cost_reference=1)<=utility(.9,2,1,time_reference=10,cost_reference=1)
    rows=[{'configuration':dict(CONFIG,actual_model=m),'utility':45} for m in ['b','a']]
    assert rank_reports(rows)==rank_reports(list(reversed(rows)))


def test_I1_or_and_frozen_original_contract(tmp_path):
    req={'root':{'must':True,'operator':'OR','children':['a','b'],'weight':0},
         'a':{'must':False,'weight':.5},'b':{'must':False,'weight':.5}}
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',req,{'c':'check@1'})
    a.bind_subjects({'object':'v1'})
    plan={'phases':[{'id':'p','depends_on':[]}],'goals':[
        {'id':k,'requirement_refs':[k],'phase_id':'p','subject_refs':['object'],'checker':'c','acceptance':'fixed','task_refs':[]} for k in ['a','b']]}
    a.commit(a.propose(plan,CapabilityTree('g',())))
    from cgkn.execution import BlockExecutionResult,BlockStatus
    from cgkn.state.acceptance import identity
    r=BlockExecutionResult(project_id='p',run_id='r',node_id='check',attempt_id='attempt-0001',executor_ref='check@1',status=BlockStatus.SUCCEEDED,
        outputs={'goal_check':{'goal_id':'a','subjects':{'object':'v1'},'condition_hash':identity('fixed'),'execution':'VALID','evidence_refs':['fixture'],'observed':{'value':True},'verdict':'VERIFIED'}})
    r=measured_control(a,r)
    a.store.save_result(r);a.record('a',r,executor_ref='check@1')
    assert a.view()['complete'] and a.view()['completion']==.5
    changed=json.loads(json.dumps(req));changed['root']['operator']='AND'
    with pytest.raises(ValueError,match='requirement change'):GoalAcceptance(a.store,'p','r',changed,a.checkers)
    with pytest.raises(ValueError,match='duplicate child'):
        GoalAcceptance(a.store,'p','duplicate',{'r':{'must':True,'children':['r','r']}},a.checkers)


@pytest.mark.parametrize('delivery,business,status',[(1,1,'COMPUTABLE'),(0,None,'COMPUTABLE'),(None,None,'NOT_COMPUTABLE')])
def test_I7_report_rebuild_all_verdicts_isolated(tmp_path,delivery,business,status):
    protected=tmp_path/'active.json'
    protected.write_text(json.dumps({'routing':'frozen','assigned_task':'original','published_knowledge':'v1'}))
    row={'task_id':'task','revision':1,'configuration':CONFIG,'model_confirmed':True,'delivery':delivery,
         'business':business,'acceptance_ref':'controlled-fixture','duration':7,'cost':.2}
    source=tmp_path/'input.json'
    source.write_text(json.dumps({'samples':[row],'task_ids':['task'],'configuration':CONFIG,'time_reference':10,'cost_reference':1}))
    frozen={p:p.read_bytes() for p in [protected,source]}
    launcher="import socket,sys,runpy; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(PermissionError('network forbidden')); sys.addaudithook(lambda event,args: (_ for _ in ()).throw(PermissionError('unexpected process')) if event in ('subprocess.Popen','os.system') else None); runpy.run_module('scripts.task_metrics',run_name='__main__')"
    reports=[]
    for name in ['first','rebuild']:
        output=tmp_path/(name+'.json')
        subprocess.run([sys.executable,'-c',launcher,'effectiveness','--input',str(source),'--output',str(output)],check=True)
        reports.append(json.loads(output.read_text()))
    assert reports[0]==reports[1] and reports[0]['status']==status
    assert all(p.read_bytes()==content for p,content in frozen.items())


@pytest.mark.parametrize('field,value',[('observed',{}),('execution','NOT_EXECUTED'),('checker_version','wrong'),('goal_id','wrong'),('subjects',{'object':'old'})])
@pytest.mark.boundary
@pytest.mark.negative
def test_I3_inapplicable_receipt_never_supersedes_failure(tmp_path,field,value):
    from cgkn.execution import BlockExecutionResult,BlockStatus
    from cgkn.state.acceptance import identity
    a=GoalAcceptance(FileRunStore(tmp_path),'p','r',{'R':{'must':True,'version':'1','source':'fixture','scope':'object'}},{'c':'check@1'})
    a.bind_subjects({'object':'v1'})
    goal={'id':'g','requirement_refs':['R'],'phase_id':'p','subject_refs':['object'],'checker':'c','checker_version':'1','acceptance':'fixed','task_refs':[]}
    a.commit(a.propose({'phases':[{'id':'p','depends_on':[]}],'goals':[goal]},CapabilityTree('g',())))
    check={'goal_id':'g','subjects':{'object':'v1'},'condition_hash':identity('fixed'),'execution':'VALID','checker_version':'1','evidence_refs':['fixture'],'observed':{'value':False},'verdict':'FAILED'}
    r=BlockExecutionResult(project_id='p',run_id='r',node_id='check',attempt_id='attempt-0001',executor_ref='check@1',status=BlockStatus.SUCCEEDED,outputs={'goal_check':check})
    r=measured_control(a,r)
    a.store.save_result(r);failed=a.record('g',r,executor_ref='check@1')
    bad=replace(r,node_id='bad',outputs={'goal_check':dict(check,verdict='VERIFIED',**{field:value})})
    bad=measured_control(a,bad)
    a.store.save_result(bad);a.record('g',bad,executor_ref='check@1')
    assert a.view()['hard_verdict']=='FAILED'
    bad2=replace(bad,node_id='bad2',outputs={'goal_check':dict(bad.outputs['goal_check'],supersedes_receipts=[failed['receipt_hash']])})
    bad2=measured_control(a,bad2)
    a.store.save_result(bad2)
    with pytest.raises(ValueError,match='invalid observation'):a.record('g',bad2,executor_ref='check@1')
