import hashlib
import json

import pytest

from cgkn.adapters.veriarbor.run_store_adapter import RunEvidenceStore
from cgkn.runtime.node_authority import ExecutionAuthority
from tests.fixtures.provenance import setup, check


def evidence(tmp_path):
    fixture = setup(tmp_path)
    result = check(fixture)
    store = fixture['store']
    reader = RunEvidenceStore(store, 'p', 'r', authority=ExecutionAuthority(store, 'p', 'r'))
    path = store.root/'p/r/attempts/checker/attempt-0001.json'
    ref = {'node_id': 'checker', 'attempt_id': 'attempt-0001',
           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
           'receipt_id': result.metadata['node_commit_receipt_id']}
    return fixture, reader, path, ref, result


@pytest.mark.happy_path
@pytest.mark.boundary
def test_exact_attempt_ignores_tampered_latest_projection(tmp_path):
    fixture, reader, _, ref, result = evidence(tmp_path)
    latest = fixture['store'].root/'p/r/node_results/checker.json'
    latest.write_text('{"status":"SUCCEEDED","outputs":{"model_claim":"PASS"}}')
    assert reader.evidence(ref) == result.as_dict()


@pytest.mark.negative
@pytest.mark.boundary
@pytest.mark.parametrize('attack', ['latest', 'hash', 'receipt', 'attempt', 'authority', 'stale'])
def test_evidence_consumer_rejects_missing_or_wrong_identity(tmp_path, attack):
    fixture, reader, path, ref, _ = evidence(tmp_path)
    if attack == 'latest':
        ref = 'checker'
    elif attack == 'hash':
        row = json.loads(path.read_text())
        row['outputs']['forged'] = True
        path.write_text(json.dumps(row))
    elif attack == 'receipt':
        ref['receipt_id'] = 'unrelated'
    elif attack == 'attempt':
        ref['attempt_id'] = '../attempt-0001'
    elif attack == 'authority':
        reader.authority = None
    elif attack == 'stale':
        check(fixture, attempt='attempt-0002')
    with pytest.raises((ValueError, OSError)):
        reader.evidence(ref)
