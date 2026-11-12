from test_project_loop_boundaries import Composer,decision,policy
from tests.qualification_support import probe_node,probe_runner
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.orchestration.tree_edits import TreeEdit
from cgkn.state import FileRunStore
from cgkn.executors import ExecutorRegistry
from cgkn.executors.protocol import ExecutorDescriptor
from cgkn.execution import BlockExecutionResult,BlockStatus,ExecutionError,ExecutionErrorCode


def test_continuation_requirements_survive_execution_refresh(tmp_path):
    contexts=[]
    class Observe(Composer):
        def decide(self,context):
            contexts.append(context)
            return super().decide(context)
    class Worker:
        descriptor=ExecutorDescriptor('worker@1','bounded_llm',('c@1',))
        def execute(self,r):
            return BlockExecutionResult(project_id=r.project_id,run_id=r.run_id,node_id=r.node_id,
                attempt_id=r.attempt_id,executor_ref=r.executor_ref,status=BlockStatus.FAILED,
                error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,'NO_IMPLEMENTATION_PROGRESS'),
                metadata={'implementation_progress':{'verdict':'NO_IMPLEMENTATION_PROGRESS','evidence_refs':['raw.json']},
                          'private_response':'must not enter context'})
    registry=ExecutorRegistry();registry.register(Worker());store=FileRunStore(tmp_path)
    config=probe_node('n',capability_ref='c@1',config={'executor_ref':'worker@1'}).as_dict()['config']
    edit=TreeEdit('e','add_node','n',{'capability_ref':'c@1','parent_id':'','depends_on':[],'config':config},{'actor':'agent'})
    loop=AgentProjectLoop(Observe([decision(edits=[edit],run=True),decision(escalation=True)]),probe_runner(registry,store,execution_mode='GOVERNED'),store,known_capabilities={'c@1'},worker_model='worker',admission_policy=policy())
    loop.run(project_id='p',run_id='r',goal='bounded repair evidence',continuation_feedback={'instruction':'Preserve public failure focus through M12','evidence_refs':['public-observation.json']})
    result=contexts[-1].execution_results['n']
    assert result['attempt_id']=='attempt-0001'
    assert result['metadata']['implementation_progress']['verdict']=='NO_IMPLEMENTATION_PROGRESS'
    assert 'private_response' not in result['metadata']

    assert contexts[0].failure_details['continuation_requirements']==contexts[-1].failure_details['continuation_requirements']
    assert contexts[-1].failure_details['continuation_requirements']['instruction']=='Preserve public failure focus through M12'
