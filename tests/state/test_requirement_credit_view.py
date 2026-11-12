import hashlib
import json
import shutil

import pytest

from cgkn.telemetry.trusted_samples import trusted_requirement_credit
from tests.fixtures.provenance import setup, check


def hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


@pytest.mark.happy_path
@pytest.mark.boundary
def test_credit_is_read_only_and_repeated_reads_do_not_award_again(tmp_path):
    fixture = setup(tmp_path)
    check(fixture)
    before = hashes(fixture['store'].root)
    first = trusted_requirement_credit(fixture['store'], 'task')
    second = trusted_requirement_credit(fixture['store'], 'task')
    assert first == second
    assert first['credited_keys'] == [['task', 'R']]
    assert first['credited_requirement_count'] == 1
    assert hashes(fixture['store'].root) == before


@pytest.mark.negative
@pytest.mark.boundary
def test_invalid_alias_cannot_reuse_old_success_or_multiply_credit(tmp_path):
    fixture = setup(tmp_path)
    check(fixture)
    store = fixture['store']
    shutil.copytree(store.root/'p/r', store.root/'p/alias')
    before = hashes(store.root)
    view = trusted_requirement_credit(store, 'task')
    assert view['status'] == 'PAUSED'
    assert view['credited_requirement_count'] == 0 and view['excluded']
    assert hashes(store.root) == before


@pytest.mark.happy_path
@pytest.mark.boundary
def test_authentic_run_aliases_and_repair_credit_one_root_requirement(tmp_path):
    original = setup(tmp_path/'original')
    check(original)
    alias = setup(tmp_path/'alias', store=original['store'], run_id='alias')
    check(alias)
    store = original['store']
    view = trusted_requirement_credit(store, 'task')
    assert len(view['runs']) == 2
    assert view['credited_keys'] == [['task', 'R']]
    check(alias, value=8, attempt='attempt-0002')
    assert trusted_requirement_credit(store, 'task')['credited_requirement_count'] == 0
    check(alias, value=7, attempt='attempt-0003')
    repaired = trusted_requirement_credit(store, 'task')
    assert repaired['credited_keys'] == [['task', 'R']]
    assert repaired['credited_requirement_count'] == 1


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize('change', ['failed_check', 'stale_subject', 'model_score'])
def test_counterevidence_and_model_scores_never_grant_credit(tmp_path, change):
    fixture = setup(tmp_path)
    check(fixture)
    if change == 'failed_check':
        check(fixture, value=8, attempt='attempt-0002')
    elif change == 'stale_subject':
        fixture['acceptance'].bind_subjects({'object': '0'*64})
    else:
        path = fixture['store'].root/'p/r/attempts/checker/attempt-0001.json'
        row = json.loads(path.read_text())
        row['outputs']['goal_check'] = {'verdict': 'VERIFIED', 'reward': 100, 'confidence': 1}
        path.write_text(json.dumps(row), encoding='utf-8')
    view = trusted_requirement_credit(fixture['store'], 'task')
    assert view['credited_requirement_count'] == 0
