from tests.qualification_support import probe_node, probe_runner
import concurrent.futures
import copy
import json
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
import pytest
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.acceptance import identity
from cgkn.state.provenance import ProvenanceGate,put_evidence,reference,file_hash
from cgkn.telemetry.trusted_samples import trusted_effectiveness
from tests.fixtures.provenance import setup,check,sample,CONFIG


def test_I0_entry_and_original_contract(tmp_path):
    f=setup(tmp_path);r=check(f);assert r.executor_ref=='measure.file@1'
    with pytest.raises(ValueError):f['store'].immutable_json(f['store'].run_dir('p','r')/'provenance_contract.json',{})
    assert f['acceptance'].view()['complete']


@pytest.mark.boundary
@pytest.mark.happy_path
def test_I1_real_checker_trusted_chain(tmp_path):
    f=setup(tmp_path);check(f);g=ProvenanceGate(f['store'],'p','r')
    result=g.current(f['acceptance'])
    assert result['status']=='TRUSTED' and result['chains'][0]['verdict']=='VERIFIED'
    assert set(result['chains'][0]['requirements'])=={'R'}
    ref=sample(f);report=trusted_effectiveness(f['store'],'p','r',[ref])
    assert report['n_settled']==1 and report['successes']==1
    assert report['p_safe']<1 and report['posterior_mean']==pytest.approx(2/3)


@pytest.mark.parametrize('field',['acceptance_ref','candidate_hash','requirement_id','requirement_version','checker_ref','checker_hash','observation_hash','receipt_hash','input_hash','artifact_version'])
def test_I2_reference_tampering(tmp_path,field):
    f=setup(tmp_path);r=check(f);g=ProvenanceGate(f['store'],'p','r')
    if field in {'acceptance_ref','receipt_hash'}:
        ref=sample(f)
        if field=='acceptance_ref':ref=dict(ref,sha256='0'*64)
        else:
            p=f['store'].run_dir('p','r')/'attempts/checker/attempt-0001.json'
            body=json.loads(p.read_text());body['outputs']['goal_check']['verdict']='FAILED';p.write_text(json.dumps(body))
        out=trusted_effectiveness(f['store'],'p','r',[ref]);assert out['excluded'] and out['n_settled']==0;return
    witness=g.resolve(r.as_dict()['outputs']['goal_check']['provenance_ref'],'CheckWitness')
    if field=='candidate_hash':witness['candidate_ref']['sha256']='0'*64
    if field=='requirement_id':witness['requirement_hashes']={'other':'x'}
    if field=='requirement_version':witness['requirement_hashes']['R']='wrong-version'
    if field=='checker_ref':witness['checker_ref']='fake@1'
    if field=='checker_hash':witness['checker_source_ref']['sha256']='0'*64
    if field=='observation_hash':witness['observation_ref']['sha256']='0'*64
    if field=='input_hash':witness['input_ref']['sha256']='0'*64
    if field=='artifact_version':
        candidate=g.resolve(witness['candidate_ref'],'CandidateIdentity');candidate['version']='forged-nonempty-version'
        witness['candidate_ref']=put_evidence(f['store'],'p','r',candidate)
    changed=replace(r,node_id='tampered',outputs={'goal_check':dict(r.as_dict()['outputs']['goal_check'],provenance_ref=put_evidence(f['store'],'p','r',witness))})
    f['store'].save_result(changed)
    report=g.verify_check(changed,f['goal'],f['acceptance'].data['subjects'])
    assert report['status']!='TRUSTED' and report['reason']


@pytest.mark.parametrize('attack',['missing_ref','missing_receipt','missing_observation','pass_string','exit_zero','agent_completed','empty_observation','not_executed','unbound_candidate','unbound_requirement'])
@pytest.mark.boundary
@pytest.mark.negative
def test_I3_missing_or_fabricated(tmp_path,attack):
    f=setup(tmp_path);r=check(f);gate=ProvenanceGate(f['store'],'p','r')
    out=r.as_dict()['outputs']['goal_check'];w=gate.resolve(out['provenance_ref'],'CheckWitness')
    if attack=='missing_ref':out['provenance_ref']={'path':'p/r/missing','sha256':'0'*64}
    elif attack=='missing_receipt':
        path=f['store'].run_dir('p','r')/'attempts/checker/attempt-0001.json';path.unlink()
        assert gate.verify_check(r,f['goal'],f['acceptance'].data['subjects'])['status']!='TRUSTED';return
    elif attack=='missing_observation':w['observation_ref']={'path':'p/r/missing','sha256':'0'*64}
    elif attack in {'pass_string','exit_zero','agent_completed'}:out={'verdict':'VERIFIED','observed':{'claim':attack}}
    elif attack=='empty_observation':out['observed']={}
    elif attack=='not_executed':out['execution']='NOT_EXECUTED'
    elif attack=='unbound_candidate':w.pop('candidate_ref')
    elif attack=='unbound_requirement':w['requirement_hashes']={}
    if attack in {'missing_observation','unbound_candidate','unbound_requirement'}:out['provenance_ref']=put_evidence(f['store'],'p','r',w)
    bad=replace(r,node_id='bad',outputs={'goal_check':out});f['store'].save_result(bad)
    assert gate.verify_check(bad,f['goal'],f['acceptance'].data['subjects'])['status']!='TRUSTED'


def test_I4_revisions_old_failures_and_late_events(tmp_path):
    f=setup(tmp_path,8);old=check(f);assert f['acceptance'].view()['hard_verdict']=='FAILED'
    check(f,7,'attempt-0002');assert f['acceptance'].view()['complete']
    assert len(f['acceptance'].data['checks'])==2
    with pytest.raises(ValueError,match='current stored'):f['acceptance'].record('g',old,executor_ref='measure.file@1')
    # A new applicable counterexample cannot be erased by a late old successful candidate.
    check(f,9,'attempt-0003');assert f['acceptance'].view()['hard_verdict']=='FAILED'
    state=json.loads((f['store'].run_dir('p','r')/'goal_acceptance.json').read_text())
    assert len(state['checks'])==3


def test_I5_empty_zero_negative_and_split(tmp_path):
    f=setup(tmp_path);check(f);before=f['acceptance'].view()
    plan=copy.deepcopy(f['acceptance'].data['plans'][-1]);plan.pop('revision');plan['goals'].append(dict(plan['goals'][0],id='same-obligation'))
    from cgkn.orchestration.capability_tree import CapabilityTree
    f['acceptance'].commit(f['acceptance'].propose(plan,CapabilityTree('g',())))
    assert f['acceptance'].view()['completion']<=before['completion']
    for weight in [-1,float('nan')]:
        with pytest.raises(ValueError):GoalAcceptance(f['store'],'p','bad',{'R':{'must':True,'weight':weight}},{})
    assert not GoalAcceptance(f['store'],'p','zero',{'R':{'must':True,'weight':0}},{}).view()['complete']
    assert not GoalAcceptance(f['store'],'p','empty',{},{}).view()['complete']


@pytest.mark.parametrize('failure',['crash','timeout','bad_json','io','old','wrong_version','empty'])
def test_I6_checker_failures(tmp_path,failure):
    from cgkn.execution import BlockStatus,ExecutionError,ExecutionErrorCode
    f=setup(tmp_path);r=check(f);gate=ProvenanceGate(f['store'],'p','r')
    check_doc=dict(r.outputs['goal_check'])
    if failure=='wrong_version':check_doc['checker_version']='2'
    if failure=='empty':check_doc['observed']={}
    if failure=='old':check_doc['subjects']={'object':'old'}
    status=BlockStatus.TIMED_OUT if failure=='timeout' else BlockStatus.FAILED if failure in {'crash','bad_json','io'} else r.status
    error=ExecutionError(ExecutionErrorCode.TIMEOUT if failure=='timeout' else ExecutionErrorCode.EXECUTION_ERROR,failure) if status!=BlockStatus.SUCCEEDED else None
    bad=replace(r,node_id='bad',status=status,error=error,outputs={'goal_check':check_doc});f['store'].save_result(bad)
    assert gate.verify_check(bad,f['goal'],f['acceptance'].data['subjects'])['status']!='TRUSTED'


@pytest.mark.parametrize('script,timeout',[('raise RuntimeError("checker fault")',2),('import time;time.sleep(5)',.1),('print("not json")',2),('open("absent-file")',2)])
def test_I6_actual_checker_process_errors(tmp_path,script,timeout):
    try:
        p=subprocess.run([sys.executable,'-I','-c',script],cwd=tmp_path,capture_output=True,text=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        assert timeout==.1;return
    if p.returncode==0:
        with pytest.raises(json.JSONDecodeError):json.loads(p.stdout)
    else:assert p.stderr and p.returncode!=0


@pytest.mark.parametrize('expression,expected',[('0*7',0),('-7',-7),('7+1',8)],ids=['drop-to-zero','sign-reversal','off-by-one'])
def test_I7_running_semantic_mutations(tmp_path,expression,expected):
    good=setup(tmp_path/'good');check(good);assert good['acceptance'].view()['complete']
    program=tmp_path/'controlled_variant.py';program.write_text("import json\nprint(json.dumps({'value':"+expression+"}))\n",encoding='utf-8')
    executed=subprocess.run([sys.executable,'-I',str(program)],capture_output=True,text=True,check=True)
    value=json.loads(executed.stdout)['value'];assert value==expected
    f=setup(tmp_path,value);r=check(f)
    assert executed.returncode==0 and r.status.value=='SUCCEEDED' and r.outputs['goal_check']['observed']['value']==value
    report=ProvenanceGate(f['store'],'p','r').current(f['acceptance'])
    assert report['status']=='TRUSTED' and report['acceptance']['hard_verdict']=='FAILED'


def test_I8_time_categories(tmp_path):
    from cgkn.telemetry.effectiveness import task_time
    rows=[{'start':0,'end':5,'category':'provider_wait_time','clock_id':'c'},{'start':2,'end':7,'category':'repair_time','clock_id':'c'}]
    t=task_time(ready=0,ended=7,now=7,intervals=rows,clock_id='c')
    assert t['task_wall_time']==7 and t['active_execution_time']==10 and t['repair_time']==5
    assert task_time(ready=0,ended=None,now=7,intervals=rows,clock_id='c')['complete_duration'] is None
    for bad in [dict(ready=8,ended=7,now=9),dict(ready=0,ended=10,now=9)]:
        with pytest.raises(ValueError):task_time(**bad,intervals=[],clock_id='c')
    assert task_time(ready=0,ended=0,now=0,intervals=[],clock_id='c')['task_wall_time']==0
    repair=task_time(ready=0,ended=5,now=5,clock_id='c',intervals=[{'start':0,'end':5,'clock_id':'c','category':'provider_wait_time','phase':'repair'}])
    assert repair['provider_wait_time']==repair['repair_time']==repair['active_execution_time']==5


def test_I9_cost_late_usage_and_distinct_requests(tmp_path):
    from cgkn.telemetry.effectiveness import task_cost
    base={'currency':'CNY','price_version':'v1','cost_kind':'estimate','outcome':'KNOWN'}
    rows=[dict(base,call_id='a',amount='.2'),dict(base,call_id='b',amount='.3'),dict(base,call_id='c',amount='.4',outcome='UNKNOWN')]
    assert task_cost(rows+rows,currency='CNY',price_version='v1')['known_total']=='0.9'
    assert task_cost(rows,currency='CNY',price_version='v1')['complete_total'] is None
    with pytest.raises(ValueError):task_cost(rows+[dict(rows[2],amount='.1',outcome='KNOWN')],currency='CNY',price_version='v1')
    # Explicitly reconciled input is a separate revision, original remains.
    settled=rows[:2]+[dict(rows[2],amount='.1',outcome='KNOWN')]
    assert task_cost(settled,currency='CNY',price_version='v1')['complete_total']=='0.6'


def test_I10_math_reference_and_boundaries():
    from cgkn.telemetry.effectiveness import beta_lower,utility
    assert beta_lower(0,0)==pytest.approx(.05)
    assert beta_lower(4,0)==pytest.approx(.05**.2)
    assert beta_lower(0,4)==pytest.approx(1-.95**.2)
    assert beta_lower(20,20)>beta_lower(1,1)
    assert utility(.9,10,1,time_reference=10,cost_reference=1)==45
    assert utility(.9,20,1,time_reference=10,cost_reference=1)==36
    for bad in [0,-1,float('nan'),float('inf')]:
        with pytest.raises(ValueError):utility(.9,10,1,time_reference=bad,cost_reference=1)


def test_I11_pending_uses_same_subset(tmp_path):
    f=setup(tmp_path);check(f);ref=sample(f,unknown=True)
    report=trusted_effectiveness(f['store'],'p','r',[ref])
    assert report['status']=='NOT_COMPUTABLE' and report['n_pending']==1 and report['mean_cost'] is None
    assert report['history'][0]['cost_evidence']['unknown_call_ids']==['fixture-call']


def test_I12_one_task_revised_history(tmp_path):
    f=setup(tmp_path,8);check(f);r1=sample(f)
    check(f,7,'attempt-0002');r2=sample(f,2)
    report=trusted_effectiveness(f['store'],'p','r',[r2,r1,r2])
    assert report['n_settled']==1 and report['successes']==1 and len(report['history'])==2
    assert report['history'][0]['business'] in [0,1]


def test_I13_reopen_rebuild(tmp_path):
    f=setup(tmp_path);check(f);ref=sample(f)
    first=trusted_effectiveness(f['store'],'p','r',[ref])
    second=trusted_effectiveness(FileRunStore(f['store'].root),'p','r',[ref])
    assert first==second
    body=json.loads((f['store'].root/ref['path']).read_text(encoding='utf-8'))
    path=f['store'].root/body['time_ref']['path'];path.write_text('{}',encoding='utf-8')
    assert trusted_effectiveness(FileRunStore(f['store'].root),'p','r',[ref])['n_settled']==0


def test_I14_concurrent_immutable_and_acceptance(tmp_path):
    f=setup(tmp_path);check(f)
    def write(i):
        store=FileRunStore(f['store'].root)
        return put_evidence(store,'p','r',{'kind':'event','identity':i%5})
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:refs=list(pool.map(write,range(40)))
    assert len({r['path'] for r in refs})==5
    for ref in refs:assert ProvenanceGate(f['store'],'p','r').resolve(ref,'event')['identity'] in range(5)
    result=f['store'].load_result('p','r','checker')
    def notify(_):
        a=GoalAcceptance(FileRunStore(f['store'].root),'p','r',f['binding']['requirements'],{'c':'measure.file@1'})
        return a.record('g',result,executor_ref='measure.file@1')
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(notify,range(20)))
    f['acceptance']._reload();assert len(f['acceptance'].data['checks'])==1
    def independent(i):
        local=dict(f,acceptance=GoalAcceptance(FileRunStore(f['store'].root),'p','r',f['binding']['requirements'],{'c':'measure.file@1'}))
        return check(local,node='independent'+str(i))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(independent,range(3)))
    f['acceptance']._reload();assert len(f['acceptance'].data['checks'])==4 and f['acceptance'].view()['complete']


def test_I14_process_races_and_late_receipt(tmp_path):
    from cgkn.execution import BlockExecutionResult,BlockStatus
    f=setup(tmp_path);check(f)
    source="from cgkn.state import FileRunStore;from cgkn.state.provenance import put_evidence;import sys; s=FileRunStore(sys.argv[1]);[put_evidence(s,'p','r',{'kind':'RaceEvent','id':i}) for i in range(6)]"
    processes=[subprocess.Popen([sys.executable,'-c',source,str(f['store'].root)]) for _ in range(3)]
    assert all(p.wait(timeout=30)==0 for p in processes)
    for attempt in ['attempt-0002','attempt-0001']:
        f['store'].save_result(BlockExecutionResult(project_id='p',run_id='r',node_id='late',attempt_id=attempt,executor_ref='fixture',status=BlockStatus.SUCCEEDED))
    assert f['store'].load_result('p','r','late').attempt_id=='attempt-0002'


def test_I15_path_and_worker_isolation(tmp_path):
    from cgkn.executors.llm import BoundedFileActions
    f=setup(tmp_path);check(f);gate=ProvenanceGate(f['store'],'p','r')
    with pytest.raises(ValueError):gate.resolve({'path':'../oracle','sha256':'0'*64})
    worker=tmp_path/'worker';worker.mkdir();hidden=tmp_path/'hidden';hidden.write_text('private')
    with pytest.raises(PermissionError):BoundedFileActions(worker).apply({'action':'read_file','path':'../hidden'})


def test_I16_trusted_cli_readonly(tmp_path):
    f=setup(tmp_path);check(f);ref=sample(f)
    inputs=tmp_path/'input.json';inputs.write_text(json.dumps({'sample_refs':[ref]}))
    before={str(p):file_hash(p) for p in f['store'].root.rglob('*') if p.is_file()}
    outputs=[]
    launcher="import socket,runpy,sys; socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(PermissionError('network forbidden')); sys.addaudithook(lambda e,a: (_ for _ in ()).throw(PermissionError('process forbidden')) if e=='subprocess.Popen' else None); runpy.run_module('scripts.task_metrics',run_name='__main__')"
    for i in range(2):
        out=tmp_path/f'out{i}.json'
        subprocess.run([sys.executable,'-c',launcher,'trusted','--store',str(f['store'].root),'--project','p','--run','r','--input',str(inputs),'--output',str(out)],check=True)
        outputs.append(json.loads(out.read_text(encoding='utf-8')))
    assert outputs[0]==outputs[1]
    assert before=={str(p):file_hash(p) for p in f['store'].root.rglob('*') if p.is_file()}


def test_I17_dependency_not_composition():
    from cgkn.orchestration.capability_tree import CapabilityTree,CapabilityNode
    from cgkn.orchestration.execution_dag import compile_tree
    from cgkn.orchestration.invalidation import downstream_closure
    tree=CapabilityTree('g',tuple(probe_node(n,capability_ref='c',depends_on=d) for n,d in [('S',()),('A',('S',)),('B',('S',))]))
    dag=compile_tree(tree)
    assert set(downstream_closure(dag,{'A'}))=={'A'}
    assert set(downstream_closure(dag,{'S'}))=={'S','A','B'}


def test_I11_evaluator_correction_cannot_claim_clean_calibration(tmp_path):
    f=setup(tmp_path,continuation={'reason':'EVALUATOR_DEFECT'})
    check(f);ref=sample(f)
    report=trusted_effectiveness(f['store'],'p','r',[ref])
    assert report['n_settled']==1 and report['successes']==1
    assert report['status']=='PROVISIONAL'
    assert not report['eligible_for_clean_protocol_calibration']
    assert report['calibration']=='PROVISIONAL_EVALUATOR_CORRECTED_OBSERVATION'


def test_I18_unknown_alias_and_independent(tmp_path):
    from tests.runtime.test_graph_commit import test_unknown_operation_cannot_escape_by_adding_new_node_name
    test_unknown_operation_cannot_escape_by_adding_new_node_name(tmp_path,None)


def test_I5_existing_and_or_parent_negative(tmp_path):
    from tests.telemetry.test_acv4_independent import test_I1_parent_integration_cannot_be_outvoted_and_mapping_not_weakened,test_I1_or_and_frozen_original_contract
    test_I1_parent_integration_cannot_be_outvoted_and_mapping_not_weakened(tmp_path/'and')
    test_I1_or_and_frozen_original_contract(tmp_path/'or')


def test_I11_fixed_four_member_cohort():
    from tests.telemetry.test_acv4_independent import test_I5_fixed_cohort_same_set_and_invalid_parameters
    test_I5_fixed_cohort_same_set_and_invalid_parameters()


def test_I10_reference_properties():
    from tests.telemetry.test_acv4_independent import test_I5_properties_and_stable_presentation
    test_I5_properties_and_stable_presentation()


def test_I17_checker_recheck_only(tmp_path):
    from tests.telemetry.test_acv4_independent import test_I6_checker_change_requires_recheck_not_generation
    test_I6_checker_change_requires_recheck_not_generation(tmp_path)


@pytest.mark.parametrize('attack',['none','missing_call','current_candidate','model','timing','worker_output'])
def test_I11_production_lineage(tmp_path,attack):
    f=setup(tmp_path,production=True);check(f);ref=sample(f);store=f['store'];gate=ProvenanceGate(store,'p','r')
    row=gate.resolve(ref,'MetricRevision')
    if attack=='missing_call':
        store.immutable_json(store.run_dir('p','r')/'provider_calls/omitted/request.json',{'identity':'omitted','started_at':1})
    if attack=='current_candidate':f['artifact'].write_text('{"value":8}',encoding='utf-8')
    if attack in {'model','worker_output'}:
        witness=gate.resolve(row['provider_refs'][0],'ProviderWitness')
        if attack=='model':
            body=json.loads(gate.resolve(witness['response_ref']));body['routing']['actual_model']='wrong'
            path=store.run_dir('p','r')/'tampered-response.json';store.immutable_json(path,body);witness['response_ref']=reference(store.root,path)
        else:
            body=json.loads(gate.resolve(witness['execution_ref']));body['metadata']['artifact_hashes']['object']='0'*64
            path=store.run_dir('p','r')/'tampered-worker.json';store.immutable_json(path,body);witness['execution_ref']=reference(store.root,path)
        row['provider_refs']=[put_evidence(store,'p','r',witness)]
    if attack=='timing':
        body=gate.resolve(row['time_ref'],'TaskTiming');body['finished_unix']=2
        row['time_ref']=put_evidence(store,'p','r',body)
    if attack in {'model','worker_output','timing'}:ref=put_evidence(store,'p','r',row)
    report=trusted_effectiveness(store,'p','r',[ref])
    if attack=='none':assert report['status']=='COMPUTABLE' and report['n_settled']==1
    else:assert report['n_settled']==0 and report['excluded']


def test_I2_cross_run_requires_exact_authorized_import(tmp_path):
    f=setup(tmp_path);store=f['store'];outside=put_evidence(store,'p','prior',{'kind':'PriorFact','logical_task_id':'task'})
    gate=ProvenanceGate(store,'p','r')
    with pytest.raises(ValueError,match='cross-run'):gate.resolve(outside,'PriorFact')
    binding=dict(f['binding'],authorized_imports=[outside])
    store.immutable_json(store.run_dir('p','continuation')/'provenance_contract.json',binding)
    assert ProvenanceGate(store,'p','continuation').resolve(outside,'PriorFact')['logical_task_id']=='task'
    with pytest.raises(ValueError):ProvenanceGate(store,'p','continuation').resolve(dict(outside,sha256='0'*64),'PriorFact')


@pytest.mark.parametrize('mode',['same_operation','changed_executor','shared_resource','same_capability'])
def test_I18_unknown_effect_alias_matrix(tmp_path,mode):
    from tests.runtime.test_graph_commit import Recorder,run
    from cgkn.execution import ExecutionError,ExecutionErrorCode,BlockStatus
    from cgkn.orchestration.capability_tree import CapabilityTree,CapabilityNode
    from cgkn.executors import ExecutorRegistry,ExecutorDescriptor
    from cgkn.runtime import DAGRunner
    class Unknown(Recorder):
        def execute(self,request):
            r=super().execute(request)
            if request.node_id=='a':return replace(r,status=BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'unknown',{'outcome_unknown':True}))
            return r
    executor=Unknown();other=Recorder();other.descriptor=ExecutorDescriptor('other@1','deterministic',('*',))
    registry=ExecutorRegistry();registry.register(executor);registry.register(other)
    runner=probe_runner(registry,FileRunStore(tmp_path),execution_mode='GOVERNED')
    config={'executor_ref':'record@1'}
    if mode in {'same_operation','changed_executor'}:config['operation_id']='business-operation'
    if mode=='shared_resource':config['resources']={'business-state':'write'}
    original=probe_node('a',capability_ref='capability@1',config=config);tree=CapabilityTree('g',(original,));run(runner,tree)
    newconfig=dict(config)
    if mode=='changed_executor':newconfig['executor_ref']='other@1'
    alternate=probe_node('alias',capability_ref='different@1' if mode=='shared_resource' else 'capability@1',config=newconfig)
    with pytest.raises(ValueError,match='UNRESOLVED_OPERATION'):run(runner,CapabilityTree('g',(original,alternate)),resume=True,accept_edits=True)
    unrelated=probe_node('unrelated',capability_ref='unrelated@1',config={'executor_ref':'other@1'})
    run(runner,CapabilityTree('g',(original,unrelated)),resume=True,accept_edits=True)
    assert runner.store.load_result('p','r','unrelated').status==BlockStatus.SUCCEEDED
