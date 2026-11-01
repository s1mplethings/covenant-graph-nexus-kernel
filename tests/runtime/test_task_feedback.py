import json
import pytest

from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.orchestration.capability_tree import CapabilityNode
from cgkn.state import FileRunStore
from cgkn.state.task_feedback import TaskFeedback


def record(tmp_path, *, meta=False):
    store = FileRunStore(tmp_path)
    feedback = TaskFeedback(store, 'p', 'r')
    result = BlockExecutionResult(project_id='p', run_id='r', node_id='work',
        attempt_id='attempt-0001', executor_ref='fixture@1', status=BlockStatus.SUCCEEDED,
        outputs={'ok': True})
    store.save_result(result)
    node = CapabilityNode('work', capability_ref='fixture@1', config={'meta_operation': meta})
    fact = feedback.terminal(result, node)
    return feedback, result, node, fact


def advisory(fact, hypothesis='unknown'):
    return dict(observations='tool completed; business outcome unchecked',
        evidence_refs=[fact['receipt_ref']], hypothesis=hypothesis, uncertainty='high',
        required_capabilities=[], candidate_lesson=None, recommendation=None, model='controlled')


def test_terminal_and_revision_idempotence(tmp_path):
    f, result, node, fact = record(tmp_path)
    assert f.terminal(result, node) == fact
    one = f.revise(fact['identity'], 1, advisory(fact))
    f.revise(fact['identity'], 2, advisory(fact, 'later counterexample'), supersedes=1)
    assert f.revise(fact['identity'], 1, advisory(fact)) == one
    current = f.context()
    assert current['items'][0]['evaluation']['revision'] == 2
    assert current['business_successes'] == 0  # producer ok is not acceptance
    with pytest.raises(ValueError, match='conflicting'):
        f.revise(fact['identity'], 1, advisory(fact, 'different'))


def test_private_reference_and_recursive_meta_rejected(tmp_path):
    f, _, _, fact = record(tmp_path / 'normal')
    value = advisory(fact)
    value['evidence_refs'] = ['../../private/oracle.json']
    with pytest.raises(ValueError, match='exact public'):
        f.revise(fact['identity'], 1, value)
    f, _, _, fact = record(tmp_path / 'meta', meta=True)
    with pytest.raises(ValueError, match='recursively'):
        f.revise(fact['identity'], 1, advisory(fact))


def test_missing_predecessor_rejected(tmp_path):
    f, _, _, fact = record(tmp_path)
    with pytest.raises(ValueError, match='predecessor missing'):
        f.revise(fact['identity'], 2, advisory(fact), supersedes=1)
