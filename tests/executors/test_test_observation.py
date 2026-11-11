from pathlib import Path
from tests.executor_authority_support import invoke_bound_executor
from tests.calibration_admission import run_calibration
import pytest
from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus
from cgkn.executors import PythonTestExecutor,ExecutorRegistry
from cgkn.state import FileRunStore
from cgkn.runtime import DAGRunner
from cgkn.orchestration import CapabilityTree,CapabilityNode,compile_tree
from cgkn.application.software_project.qualification import install,new_contract

pytestmark=[pytest.mark.boundary,pytest.mark.negative]

def request(args=()):
    return BlockExecutionRequest(project_id='p',run_id='r',node_id='test',attempt_id='a',
        executor_ref='local.python-test@1',component_ref='tests@1',
        task_context=TaskContext('execute tests',{'pytest_args':['-q',*args]}),timeout_seconds=30)


def test_actual_collected_tests_have_source_hashes_and_structured_receipt(tmp_path):
    (tmp_path/'test_value.py').write_text('def test_value(): assert 2 + 2 == 4\n')
    result=invoke_bound_executor(PythonTestExecutor(tmp_path),request())
    observed=result.outputs['test_observation']
    assert result.succeeded and observed['passed']==observed['executed']==1
    assert observed['files'][0]['path']=='test_value.py' and observed['report_sha256']
    assert '<testcase' in observed['raw_report']


@pytest.mark.parametrize('kind',['empty','failed','skipped','collection_only'])
def test_console_pass_and_zero_exit_cannot_forge_product_tests(tmp_path,kind):
    (tmp_path/'conftest.py').write_text("def pytest_sessionfinish(session,exitstatus):\n print('999 passed')\n session.exitstatus=0\n")
    if kind!='empty':
        content='def test_bad(): assert False\n' if kind=='failed' else 'import pytest\ndef test_skip(): pytest.skip("fixture")\n' if kind=='skipped' else 'def test_value(): assert True\n'
        (tmp_path/'test_value.py').write_text(content)
    result=invoke_bound_executor(PythonTestExecutor(tmp_path),request(['--collect-only'] if kind=='collection_only' else []))
    assert result.status is BlockStatus.FAILED and result.outputs['returncode']==0
    assert result.outputs['test_observation']['status']!='PASS'
    assert '999 passed' in result.outputs['stdout']


def test_external_test_fixture_does_not_verify_current_candidate(tmp_path):
    project=tmp_path/'candidate';project.mkdir();other=tmp_path/'outside';other.mkdir()
    test=other/'test_external.py';test.write_text('def test_other(): assert True\n')
    result=invoke_bound_executor(PythonTestExecutor(project),request([str(test)]))
    assert result.status is BlockStatus.FAILED
    assert result.outputs['test_observation']['status']=='INVALID'


def test_empty_test_spoof_never_becomes_verified_deliverable(tmp_path):
    work=tmp_path/'candidate';work.mkdir()
    (work/'conftest.py').write_text("def pytest_sessionfinish(session,exitstatus):\n print('1 passed')\n session.exitstatus=0\n")
    registry=ExecutorRegistry();registry.register(PythonTestExecutor(work));store=FileRunStore(tmp_path/'state')
    acceptance,checkers=install(registry,store,work,'p','r','must have real tests')
    cfg={'executor_ref':'local.python-test@1','goal':'execute focused product tests'};cfg['leaf_contract']=new_contract('test',cfg)
    tree=CapabilityTree('must have real tests',(CapabilityNode('test',capability_ref='project.python.pytest@1',config=cfg),))
    result=run_calibration(DAGRunner(registry,store,deliverable_checkers=checkers),project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    assert result.status=='FAILED' and not acceptance.view()['complete']
    assert store.load_result('p','r','test').metadata.get('deliverable_verdict')!='VERIFIED'
