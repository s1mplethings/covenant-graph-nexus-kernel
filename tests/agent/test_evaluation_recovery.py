from tests.executor_authority_support import invoke_bound_executor
import json
import dataclasses
from types import SimpleNamespace
import pytest
from cgkn.executors.task_evaluation import TaskEvaluationExecutor
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from cgkn.execution import BlockStatus
from cgkn.state.task_feedback import TaskFeedback
from tests.runtime.test_task_feedback import record


def test_late_evaluation_uses_exact_attempt_after_retry(tmp_path):
    feedback, first, node, fact = record(tmp_path)
    second = dataclasses.replace(first, attempt_id='attempt-0002', outputs={'new': True})
    feedback.store.save_result(second)
    latest = feedback.terminal(second, node)
    calls = []

    class Client:
        def complete(self, **kwargs):
            prompt = json.loads(kwargs['user'])
            calls.append(prompt)
            assert prompt['facts']['identity'] == fact['identity']
            assert prompt['receipt']['attempt_id'] == first.attempt_id
            value = dict(observations='old attempt', evidence_refs=[fact['receipt_ref']],
                         hypothesis='unknown', uncertainty='high', required_capabilities=[],
                         candidate_lesson='check attempt identity', recommendation='')
            return ProviderCompletion(json.dumps(value), 'fixture-model')

    executor = TaskEvaluationExecutor(feedback.store, Client(), ModelRoleConfig('worker', 'fixture'))
    request = SimpleNamespace(project_id='p', run_id='r', node_id='evaluate',
        attempt_id='attempt-0001', executor_ref='task.evaluate@1',
        input_values={'feedback_identity': fact['identity']})
    result = invoke_bound_executor(executor, request)
    assert result.status == BlockStatus.SUCCEEDED
    assert len(calls) == 1
    assert result.outputs['evaluation']['identity'] == fact['identity']
    current = feedback.context()['items'][0]
    assert current['identity'] == latest['identity']
    assert current['evaluation'] is None


@pytest.mark.parametrize('mutation', ['reference', 'hash', 'identity'])
@pytest.mark.boundary
@pytest.mark.negative
def test_evaluation_rejects_changed_receipt_binding_before_call(tmp_path, mutation):
    feedback, result, node, fact = record(tmp_path)
    path = feedback.root / 'feedback' / (fact['identity'] + '.json')
    damaged = dict(fact)
    if mutation == 'reference':
        damaged['receipt_ref'] = '../../private/receipt.json'
    elif mutation == 'hash':
        damaged['receipt_sha256'] = 'invalid'
    else:
        damaged['identity'] = 'wrong'
    path.write_text(json.dumps(damaged), encoding='utf-8')
    calls = []
    class Client:
        def complete(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError('must reject before model dispatch')
    executor = TaskEvaluationExecutor(feedback.store, Client(), ModelRoleConfig('worker', 'fixture'))
    request = SimpleNamespace(project_id='p', run_id='r', node_id='evaluate',
        attempt_id='attempt-0001', executor_ref='task.evaluate@1',
        input_values={'feedback_identity': fact['identity']})
    assert invoke_bound_executor(executor, request).status == BlockStatus.FAILED
    assert calls == []

@pytest.mark.parametrize('mode', ['commit_failure', 'no_response', 'invalid_response'])
@pytest.mark.boundary
@pytest.mark.happy_path
def test_evaluation_recovery_never_repeats_generation(tmp_path, monkeypatch, mode):
    feedback, _, _, fact = record(tmp_path)
    calls=[]
    class Client:
        def complete(self, **kwargs):
            calls.append(kwargs)
            if mode=='no_response': raise RuntimeError('controlled unknown submission')
            value=dict(observations='receipt only', evidence_refs=[fact['receipt_ref']], hypothesis='unconfirmed', uncertainty='high', required_capabilities=[], candidate_lesson='verify the current object', recommendation='')
            if mode=='invalid_response': value['observations']=42
            return ProviderCompletion(json.dumps(value), 'fixture-model', 'fixture-id', {'prompt_tokens':10,'completion_tokens':20})
    executor=TaskEvaluationExecutor(feedback.store,Client(),ModelRoleConfig('worker','fixture'))
    request=SimpleNamespace(project_id='p',run_id='r',node_id='evaluate',attempt_id='attempt-0001',executor_ref='task.evaluate@1',input_values={'feedback_identity':fact['identity']})
    original=TaskFeedback.revise
    def fail_commit(*args,**kwargs): raise OSError('controlled disk commit failure')
    if mode=='commit_failure': monkeypatch.setattr(TaskFeedback,'revise',fail_commit)
    first=invoke_bound_executor(executor, request)
    assert first.status==BlockStatus.FAILED
    monkeypatch.setattr(TaskFeedback,'revise',original)
    request.attempt_id='attempt-0002'
    second=invoke_bound_executor(executor, request)
    assert len(calls)==1
    if mode=='commit_failure':
        assert second.status==BlockStatus.SUCCEEDED
        assert second.outputs['recovered_response'] is True
        assert 'prompt_tokens' not in second.usage
        assert feedback.context()['items'][0]['evaluation']['acceptance_authority'] is False
    else:
        assert second.status==BlockStatus.FAILED
        assert feedback.context()['items'][0]['evaluation'] is None
    assert feedback.context()['business_successes']==0
