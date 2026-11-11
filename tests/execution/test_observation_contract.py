from tests.qualification_support import probe_node, measurement_runner
import json,sys
from dataclasses import replace
import pytest
from cgkn.execution import BlockExecutionRequest,BlockExecutionResult,BlockStatus,ExecutionError,ExecutionErrorCode,TaskContext
from cgkn.execution.observations import Observations,ObservationError,repair_request,failure_domain
from cgkn.executors.local import CommandExecutor
from cgkn.executors.observation import ObservationExecutor
from cgkn.executors import ExecutorRegistry
from cgkn.orchestration.capability_tree import CapabilityNode,CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore,EventRecord

@pytest.mark.parametrize('kind,raw,encoding,structured',[
 ('process_result','process output','utf-8',{'returncode':0}),('command_result','command output','utf-8',{'returncode':0}),
 ('stdout_text','{"looks":"json"}','utf-8',{}),('stderr_text','{"error":"quoted text"}','utf-8',{}),
 ('file_bytes',b'\x00\xff\x01','binary',{}),('file_text','{malformed','utf-8',{}),
 ('state_snapshot','7b2261223a317d','utf-8',{}),('json_document','{"state":"running"}','utf-8',{}),
 ('http_result','body','utf-8',{'http_status':200}),('database_result','row','utf-8',{'count':1}),
 ('checker_result','assertion','utf-8',{'verdict':'FAILED'}),('artifact_result','artifact','utf-8',{'exists':True}),
 ('alien_type','{not-json','utf-8',{}),('stdout_text','','utf-8',{}),('stdout_text','中文\r\nnext\n','utf-8',{}),
 ('file_text','x'*20000,'utf-8',{})])
def test_explicit_types_no_content_guess(tmp_path,kind,raw,encoding,structured):
    obs=Observations(FileRunStore(tmp_path),'p','r');ref=obs.record(raw,observation_type=kind,producer='test',subject={'object':'sha'},encoding=encoding,structured=structured)
    value=obs.resolve(ref);assert 'argv' not in value and not value['normalization_error']
    assert ('document' in value['structured'])==(kind=='json_document')
    assert (tmp_path/value['raw_ref']['path']).read_bytes()==(raw if isinstance(raw,bytes) else raw.encode(encoding))
    if len(raw)>1024:assert value['preview_truncated'] and len(value['preview'])<len(raw)
    if kind=='alien_type':assert value['observation_type']=='unknown_observation'

def test_malformed_declared_json_fails_closed_with_raw_ref(tmp_path):
    obs=Observations(FileRunStore(tmp_path),'p','r');ref=obs.record('{bad',observation_type='json_document',producer='test',subject={'object':'sha'})
    with pytest.raises(ObservationError) as e:obs.public_feedback([ref],requirement_id='R',goal='g',current_object={'object':'sha'},expected='public',public_fields=['state'])
    assert e.value.raw_ref and obs.resolve(ref)['normalization_error']['classification']=='HARNESS'

def test_argv_is_optional_and_public_projection_cannot_read_oracle(tmp_path):
    obs=Observations(FileRunStore(tmp_path),'p','r');ref=obs.record('private contents',observation_type='command_result',producer='test',subject={'object':'sha'},argv=['python','app.py'],structured={'exit_code':2,'state':'running','hidden_answer':'DO NOT LEAK'})
    feedback=obs.public_feedback([ref],requirement_id='R',goal='g',current_object={'object':'sha'},expected='idempotent',public_fields=['exit_code','state'],failure_domain='BUSINESS')
    assert 'DO NOT LEAK' not in json.dumps(feedback) and 'private contents' not in json.dumps(feedback)
    assert repair_request(feedback,{'R':'public'})['feedback']==feedback
    with pytest.raises(ValueError):obs.public_feedback([ref],requirement_id='R',goal='g',current_object={'object':'sha'},expected='x',public_fields=['hidden_answer'])
    with pytest.raises(ValueError):obs.record('x',observation_type='state_snapshot',producer='p',subject={'o':'h'},argv=[])
    with pytest.raises(ObservationError):obs.public_feedback([ref],requirement_id='R',goal='g',current_object={'object':'old'},expected='x',public_fields=[])

@pytest.mark.parametrize('domain',['HARNESS','TRANSPORT','UNKNOWN','NONE'])
def test_non_business_feedback_never_requests_business_repair(tmp_path,domain):
    obs=Observations(FileRunStore(tmp_path),'p','r');ref=obs.record('',observation_type='unknown_observation',producer='test',subject={'o':'h'})
    feedback=obs.public_feedback([ref],requirement_id='R',goal='g',current_object={'o':'h'},expected='x',public_fields=[],failure_domain=domain)
    assert feedback['actual'][0]['fact_status']=='UNKNOWN'
    with pytest.raises(ObservationError):repair_request(feedback,{})

def test_domains_preserve_transport_harness_unknown():
    base=BlockExecutionResult(project_id='p',run_id='r',node_id='n',attempt_id='a',executor_ref='test',status=BlockStatus.SUCCEEDED)
    assert failure_domain(base)=='UNKNOWN'
    for domain in ['HARNESS','TRANSPORT']:
        bad=replace(base,status=BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'x',{'failure_domain':domain}))
        assert failure_domain(bad)==domain
    bad=replace(base,status=BlockStatus.FAILED,error=ExecutionError(ExecutionErrorCode.EXECUTION_ERROR,'x',{'outcome_unknown':True}))
    assert failure_domain(bad)=='UNKNOWN'
    for verdict,domain in [('FAILED','BUSINESS'),('VERIFIED','NONE')]:
        checker=replace(base,outputs={'goal_check':{'execution':'VALID','verdict':verdict}});assert failure_domain(base,checker)==domain
    assert failure_domain(base,bad)=='HARNESS'

@pytest.mark.boundary
@pytest.mark.happy_path
def test_real_process_to_typed_feedback_fake_repair_checker_statistics_audit(tmp_path):
    from tests.fixtures.provenance import setup,check
    from cgkn.state.task_feedback import TaskFeedback
    from cgkn.telemetry.effectiveness import task_cost,task_time
    f=setup(tmp_path/'checked',value=8);failed=check(f);assert failed.outputs['goal_check']['verdict']=='FAILED'
    # The independent checker and process observation have distinct execution
    # runs; feedback captures the exact checker result as an observation.
    store=f['store'];obs=Observations(store,'p','observation')
    # Actual process stdout is a hex state snapshot with no argv observation field.
    delegate=CommandExecutor(tmp_path);wrapped=ObservationExecutor(delegate,store,[{'field':'stdout','type':'state_snapshot','public_fields':['returncode']}],{'object':'candidate-v1'})
    registry=ExecutorRegistry();registry.register(wrapped)
    tree=CapabilityTree('typed feedback chain',(probe_node('observe',capability_ref='process@1',config={'executor_ref':'local.command@1','command':[sys.executable,'-c','print("7b2261223a317d")']}),))
    document=tree.as_dict()
    document['nodes'][0]['config']['leaf_contract']['effect_domains']=['local_process']
    tree=CapabilityTree.from_dict(document)
    from tests.calibration_admission import run_calibration
    runner=measurement_runner(registry,store,{'observe':lambda o:o.get('stdout','').strip()=='7b2261223a317d'},execution_mode='GOVERNED');summary=run_calibration(runner,project_id='p',run_id='observation',tree=tree,dag=compile_tree(tree));assert summary.status=='SUCCEEDED'
    fact=TaskFeedback(store,'p','observation').context()['items'][0];refs=fact['typed_observation_refs'];doc=obs.resolve(refs[0]);assert 'document' not in doc['structured'] and 'argv' not in doc
    checker_ref=obs.record(json.dumps(failed.as_dict()),observation_type='checker_result',producer='independent-checker',subject={'object':'candidate-v1'},structured={'actual_value':8,'verdict':'FAILED'})
    feedback=obs.public_feedback([checker_ref,*refs],requirement_id='R',goal='value=7',current_object={'object':'candidate-v1'},expected='value must equal 7',public_fields=['actual_value','verdict','returncode'],failure_domain=failure_domain(store.load_result('p','observation','observe'),failed))
    request=repair_request(feedback,{'R':'value must equal 7'});assert request['feedback']['failure_domain']=='BUSINESS'
    # Controlled fake repair, explicitly not a model-produced business artifact.
    repaired=check(f,value=7,attempt='attempt-0002');assert repaired.outputs['goal_check']['verdict']=='VERIFIED'
    cost=task_cost([],currency='CNY',price_version='fixture');assert float(cost['known_total'])==0
    timing=task_time(ready=0,ended=2,now=2,clock_id='fixture',intervals=[{'start':0,'end':2,'clock_id':'fixture','category':'tool_time'}]);assert timing['complete_duration']==2
    store.append_event(EventRecord('chain-complete','p','r','QUALIFICATION_CHAIN',data={'feedback_id':feedback['feedback_id'],'repair':'fake','checker':'VERIFIED','cost':cost}))
    assert store.load_events('p','r')[-1].event_type=='QUALIFICATION_CHAIN'

@pytest.mark.boundary
@pytest.mark.negative
def test_tampering_never_projects_public_feedback(tmp_path):
    obs=Observations(FileRunStore(tmp_path),'p','r');ref=obs.record(b'binary',observation_type='file_bytes',encoding='binary',producer='p',subject={'o':'h'})
    doc=obs.resolve(ref);(tmp_path/doc['raw_ref']['path']).write_bytes(b'changed')
    with pytest.raises(ObservationError):obs.resolve(ref)
