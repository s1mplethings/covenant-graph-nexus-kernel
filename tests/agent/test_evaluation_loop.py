import json
from tests.qualification_support import probe_node, probe_runner

from cgkn.agent.composer import AgentComposer
from cgkn.agent.project_loop import AgentProjectLoop
from cgkn.execution import BlockExecutionResult, BlockStatus, ExecutionError, ExecutionErrorCode
from cgkn.executors import ExecutorDescriptor, ExecutorRegistry
from cgkn.executors.task_evaluation import TaskEvaluationExecutor
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.runtime import DAGRunner
from cgkn.state import FileRunStore


def test_failure_evaluation_returns_to_real_planner_loop(tmp_path):
    sent = []

    class FailedWork:
        descriptor = ExecutorDescriptor('fixture@1', 'deterministic', ('work@1',))

        def execute(self, request):
            return BlockExecutionResult(project_id=request.project_id, run_id=request.run_id,
                node_id=request.node_id, attempt_id=request.attempt_id, executor_ref=request.executor_ref,
                status=BlockStatus.FAILED, error=ExecutionError(ExecutionErrorCode.INVALID_OUTPUT,
                    'current object mismatch'))

    class Client:
        def complete(self, **kwargs):
            prompt = json.loads(kwargs['user'])
            sent.append((kwargs['schema_name'], prompt))
            if kwargs['schema_name'] == 'cgkn_task_evaluation':
                value = dict(observations='receipt reports object mismatch',
                    evidence_refs=[prompt['facts']['receipt_ref']], hypothesis='identity selection may be wrong',
                    uncertainty='unconfirmed cause', required_capabilities=['work@1'],
                    candidate_lesson='Check object identity against current input', recommendation='m2')
            else:
                number = prompt['decision_number']
                edits = []
                if number == 1:
                    node, capability, config = 'work', 'work@1', {'executor_ref': 'fixture@1'}
                elif number == 2:
                    facts = prompt['task_feedback']['items'][0]
                    assert facts['status'] == 'FAILED'
                    node, capability, config = 'evaluate', 'task.evaluate@1', {
                        'executor_ref': 'task.evaluate@1', 'meta_operation': True,
                        'inputs': {'feedback_identity': facts['identity']}}
                else:
                    assert any(item['evaluation'] for item in prompt['task_feedback']['items'])
                if number < 3:
                    config=probe_node(node,capability_ref=capability,config=config).as_dict()['config']
                    edits = [dict(edit_id='e'+str(number), operation='add_node', node_id=node,
                        payload=dict(capability_ref=capability, parent_id='', depends_on=[], config=config),
                        provenance={'actor': 'agent'})]
                value = dict(schema_version='1.0', decision_id='d'+str(number), summary='controlled', reason='evidence',
                    edits=edits, request_run=number < 3, finish=number == 3,
                    needs_escalation=False, escalation_reason='')
            return ProviderCompletion(json.dumps(value), 'controlled-evaluator' if kwargs['schema_name']=='cgkn_task_evaluation' else 'controlled-planner')

    store = FileRunStore(tmp_path)
    client = Client()
    registry = ExecutorRegistry()
    registry.register(FailedWork())
    registry.register(TaskEvaluationExecutor(store, client, ModelRoleConfig('worker', 'fake'), allowed_models=['m2']))
    runner = probe_runner(registry, store, max_parallel=2)
    result = AgentProjectLoop(AgentComposer(client, ModelRoleConfig('agent', 'fake')), runner, store,
        known_capabilities={'work@1', 'task.evaluate@1'}, worker_model='fake').run(project_id='p', run_id='r', goal='fixture')
    assert result.status == 'FAILED'  # evaluation does not repair or verify work
    assert len([name for name, _ in sent if name == 'cgkn_task_evaluation']) == 1
    candidates = list((store.run_dir('p', 'r') / 'knowledge_candidates').glob('*.json'))
    assert len(candidates) == 1
    assert json.loads(candidates[0].read_text())['all_items'][0]['review_state'] == 'candidate'
