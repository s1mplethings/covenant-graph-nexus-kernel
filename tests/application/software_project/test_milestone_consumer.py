from tests.governed_measurement_support import execute_external_measurement as measure
import hashlib
import json

import pytest

from cgkn.application.software_project.acceptance import ExternalAcceptanceExecutor
from cgkn.execution import BlockExecutionRequest, TaskContext
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance


def setup(tmp_path, program, *, value=7, public_fields=None):
    workspace=tmp_path/'candidate';workspace.mkdir()
    (workspace/'module.py').write_text('def value():\n    return '+str(value)+'\n')
    source=tmp_path/'independent.py';source.write_text(program)
    store=FileRunStore(tmp_path/'state')
    acceptance=GoalAcceptance(store,'p','r',{'R':{'must':True}}, {'independent':'project.acceptance@1'})
    acceptance.bind_subjects({'module.py':hashlib.sha256((workspace/'module.py').read_bytes()).hexdigest()})
    plan={'phases':[{'id':'one','depends_on':[]}], 'goals':[{'id':'g','phase_id':'one','requirement_refs':['R'],
        'acceptance':'value() returns 7','subject_refs':['module.py'],'checker':'independent','task_refs':[],
        'milestone_contract':{'design':{'artifacts':[{'path':'module.py'}]}}}]}
    acceptance.commit(acceptance.propose(plan,CapabilityTree('g',())))
    consumer={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'public_fields':public_fields or ['value','actual']}
    executor=ExternalAcceptanceExecutor(workspace,tmp_path,session_acceptance=acceptance,consumer=consumer)
    request=BlockExecutionRequest(project_id='p',run_id='r',node_id='check',attempt_id='a1',
        component_ref='project.acceptance.external@1',executor_ref='project.acceptance@1',
        task_context=TaskContext('check',{'goal_id':'g'}))
    return executor,request,acceptance,workspace


CONSUMER="""import json,sys,pathlib,runpy
request=json.loads(pathlib.Path(sys.argv[2]).read_text(encoding='utf-8'))
actual=runpy.run_path(str(pathlib.Path(request['workspace'])/'module.py'))['value']()
print(json.dumps({'execution':'VALID','observed':{'value':actual==7,'actual':actual,'hidden_answer':'PRIVATE-CHECKER-MARKER'}}))
"""


@pytest.mark.parametrize('value,verdict',[(7,'VERIFIED'),(6,'FAILED')])
def test_frozen_external_consumer_measures_actual_file_without_private_leak(tmp_path,value,verdict):
    executor,request,acceptance,workspace=setup(tmp_path,CONSUMER,value=value)
    result=measure(executor,request)
    assert result.succeeded and result.outputs['goal_check']['verdict']==verdict
    assert result.outputs['goal_check']['observed']['actual']==value
    assert 'PRIVATE-CHECKER-MARKER' not in json.dumps(result.as_dict())
    assert len(result.metadata['raw_observation_refs'])==4
    assert all((acceptance.store.root/r['path']).is_file() for r in result.metadata['raw_observation_refs'])
    acceptance.store.save_result(result)
    acceptance.record('g',result,executor_ref='project.acceptance@1')
    assert acceptance.view()['goals'][0]['verdict']==verdict


@pytest.mark.parametrize('program',[
    'print("OK")',
    'print(\'{"execution":"VALID","observed":{"value":"true"}}\')',
    'import sys;print(\'{"execution":"VALID","observed":{"value":true}}\');sys.exit(1)',
    CONSUMER+"\n(pathlib.Path(request['workspace'])/'module.py').write_text('changed')\n",
])
def test_exit_zero_or_invalid_harness_cannot_verify_a_candidate(tmp_path,program):
    executor,request,acceptance,workspace=setup(tmp_path,program)
    result=measure(executor,request)
    assert not result.succeeded and result.outputs['status']=='INVALID_EVALUATOR'
    assert result.error.details['failure_domain']=='HARNESS'
    assert result.metadata['raw_observation_refs']
    assert not acceptance.view()['complete']


def test_frozen_consumer_tamper_fails_before_measurement_with_raw_ref(tmp_path):
    executor,request,acceptance,workspace=setup(tmp_path,CONSUMER)
    executor.consumer_path.write_text('print("forged")')
    result=measure(executor,request)
    assert not result.succeeded and result.outputs['status']=='INVALID_EVALUATOR'
    assert result.metadata['raw_observation_refs']
    assert not acceptance.data['checks']
