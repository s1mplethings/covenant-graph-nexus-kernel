import pytest
from tests.qualification_support import probe_node, measurement_runner

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.executors import ExecutorRegistry, ExecutorDescriptor
from cgkn.orchestration.capability_tree import CapabilityNode, CapabilityTree
from cgkn.orchestration.execution_dag import compile_tree
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore
from cgkn.runtime.acceptance import open_goal_acceptance as GoalAcceptance
from cgkn.state.acceptance import identity
from cgkn.state.task_feedback import TaskFeedback, digest


def test_trusted_recheck_replaces_contribution_and_late_success_cannot_restore_it(tmp_path):
    store = FileRunStore(tmp_path)
    acceptance = GoalAcceptance(store, 'p', 'r', {'R': {'must': True}}, {'check':'fixture@1'})
    acceptance.bind_subjects({'input':'v1'})
    tree = CapabilityTree('g', (
        probe_node('work', capability_ref='fixture@1', config={'executor_ref':'fixture@1'}),
        probe_node('check', capability_ref='fixture@1', depends_on=('work',), config={'executor_ref':'fixture@1'})))
    plan = {'phases':[{'id':'p','outcome':'checked','depends_on':[]}],
        'goals':[{'id':'g','phase_id':'p','requirement_refs':['R'],'acceptance':'current object is correct',
                  'subject_refs':['input'],'checker':'check','task_refs':['work']}]}
    acceptance.commit(acceptance.propose(plan, tree))

    class Executor:
        descriptor = ExecutorDescriptor('fixture@1','deterministic',('*',))
        verdict = 'VERIFIED'

        def execute(self, request):
            outputs = {'object':'v1'}
            if request.node_id == 'check':
                outputs = {'goal_check': {'goal_id':'g','condition_hash':identity('current object is correct'),
                    'subjects':{'input':'v1'},'execution':'VALID','evidence_refs':['fixture-measurement'],
                    'observed':'controlled fixture','verdict':self.verdict,
                    'task_receipts':[digest(store.load_result('p','r','work').as_dict())]}}
            return BlockExecutionResult(project_id='p',run_id='r',node_id=request.node_id,
                attempt_id=request.attempt_id,executor_ref='fixture@1',status=BlockStatus.SUCCEEDED,
                outputs=outputs,usage={'model':'controlled-model','routing':{'identity_status':'MATCH'}})

    executor = Executor();registry = ExecutorRegistry();registry.register(executor)
    runner = measurement_runner(registry,store,{
        'work':lambda o:o=={'object':'v1'},
        'check':lambda o:o.get('goal_check',{}).get('subjects')=={'input':'v1'} and
            o['goal_check']['condition_hash']==identity('current object is correct') and
            o['goal_check']['verdict'] in {'VERIFIED','FAILED'} and bool(o['goal_check'].get('observed'))},execution_mode='GOVERNED')
    from tests.governed_measurement_support import admit_fixture_tree
    tree=admit_fixture_tree(store,tree)
    runner.run(project_id='p',run_id='r',tree=tree,dag=compile_tree(tree))
    old = store.load_result('p','r','check')
    acceptance.record('g',old,executor_ref='fixture@1')
    feedback = TaskFeedback(store,'p','r')
    current = lambda: next(row for row in feedback.statistics(acceptance)['contributions'] if row['node_id']=='work')
    assert current()['confirmed_model_success']
    executor.verdict = 'FAILED'
    from tests.calibration_admission import run_calibration
    run_calibration(runner,project_id='p',run_id='r',tree=tree,dag=compile_tree(tree),retry_node='check')
    acceptance.record('g',store.load_result('p','r','check'),executor_ref='fixture@1')
    assert current()['acceptance']=='FAILED' and not current()['confirmed_model_success']
    with pytest.raises(ValueError,match='current stored'):
        acceptance.record('g',old,executor_ref='fixture@1')
    assert current()['acceptance']=='FAILED'
    assert len(acceptance.data['checks'])==2
