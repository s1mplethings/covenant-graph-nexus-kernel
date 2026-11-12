"""Read-only bounded local effect inspection, followed by canonical recovery."""
import time
import json
import sys
from resume_promotion import H, P, read, sha, put
from cgkn.state import FileRunStore
from cgkn.state.provenance import put_evidence, reference
from cgkn.state.task_feedback import digest
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus

root = P / 'promotion/run-05'
store = FileRunStore(root / 'state')
project, run, node = 'iter132-promotion-studio', 'promotion-05', 'sem-node-0091'
base = store.run_dir(project, run)
prior = store.load_result(project, run, node)
expected_attempt = sys.argv[1] if len(sys.argv) > 1 else 'attempt-0049'
assert expected_attempt in {'attempt-0049', 'attempt-0051'}
assert prior.attempt_id == expected_attempt and prior.error.details['outcome_unknown']
request_key = 'e749aafd846145bbaac6aced05ada2a3' if expected_attempt == 'attempt-0049' else 'aed9fdcaba9b4c4f81ba25c7c69cd38a'
leaf = next(x for x in read(base / 'capability_tree.json')['nodes'] if x['id'] == node)['config']['leaf_contract']
stage = base / 'candidates' / node / prior.attempt_id
origin_path = base / 'attempts' / node / 'attempt-0048.json'
origin = read(origin_path)
assert origin['status'] == 'SUCCEEDED'
protected = dict(origin['metadata']['deliverable_check']['subjects'])
assert set(protected) == set(leaf['target_scope']) == {'early_main.py'}
assert all(sha(root / 'candidate' / n) == sha(stage / n) == h for n, h in protected.items())
reads = {n: sha(stage / n) for n in leaf['read_scope']}
assert all(sha(root / 'candidate' / n) == h for n, h in reads.items())
assert not (base / 'publication_intents' / node / (prior.attempt_id + '.json')).exists()
if expected_attempt == 'attempt-0049':
    known = json.loads(read(base / 'provider_calls/fa619b9ad6b84693a05facb1af918466/response.json')['text'])
    assert known == {'op': 0, 'path': 0}
else:
    request = read(base / 'provider_calls' / request_key / 'request.json')
    assert request['execution_identity'] == {'attempt_id': expected_attempt, 'node_id': node, 'project_id': project, 'run_id': run}
    assert not (base / 'provider_calls' / request_key / 'response.json').exists()
    from cgkn.providers import GatewayCompletionClient
    transport = read(H / 'migration/veriarbor/WORKER_UNKNOWN06_TRANSPORT.json')
    assert any(e.get('status') == 503 for e in transport['events'])
    assert GatewayCompletionClient('http://127.0.0.1:1', 'unused-read-only').recover_cached(
        request_identity=transport['identities'][0], schema=request['request'].get('schema'),
        cache_dir=H / '.cgkn/domestic-gateway/recovery-responses') is None
    known = {'completed_actions': [], 'upstream_http_status': 503, 'complete_response_cache': 'MISS'}
candidate = {str(p.relative_to(root / 'candidate')): sha(p) for p in (root / 'candidate').rglob('*') if p.is_file()}
ledger = P.parents[1] / 'CGKN-ITER-076/global-provider-budget.json'
assert ledger.exists()
ledger_hash = sha(ledger)
old = {str(p.relative_to(base)): sha(p) for p in (base / 'attempts').rglob('*.json')}
proof = {'kind': 'LocalBoundedFileEffectInspection', 'created_at': time.time(),
    'disposition': 'NOT_APPLIED', 'target_scope': leaf['target_scope'],
    'existing_targets_match_prior_successful_origin_stage_and_workspace': protected,
    'prior_successful_origin_ref': reference(store.root, origin_path),
    'read_dependencies_match_stage': reads, 'publication_intent_absent': True,
    'known_completed_action': known, 'source_receipt_sha256': digest(prior.as_dict()),
    'raw_error_ref': reference(store.root, base / 'provider_calls' / request_key / 'error.json'),
    'scope': 'Bounded authoritative local file effects only. Upstream response, usage and cost UNKNOWN retained; original request never replayed.'}
ref = put_evidence(store, project, run, proof)
checker = BlockExecutionResult(project_id=project, run_id=run,
    node_id='verify-veriarbor-gui-file-effects-' + expected_attempt, attempt_id='attempt-0001',
    executor_ref='verify.local-file-effects@1', status=BlockStatus.SUCCEEDED,
    outputs={'effect_reconciliation': {'source_receipt_hash': digest(prior.as_dict()),
        'disposition': 'NOT_APPLIED', 'evidence_refs': [ref]}})
store.save_result(checker)
result = DAGRunner(ExecutorRegistry(), store, reconciliation_executors=('verify.local-file-effects@1',)).reconcile_effects(project, run, node, checker)
assert sha(ledger) == ledger_hash and all(sha(base / p) == h for p, h in old.items())
assert candidate == {str(p.relative_to(root / 'candidate')): sha(p) for p in (root / 'candidate').rglob('*') if p.is_file()}
put(H / ('migration/veriarbor/LOCAL_EFFECT_RECONCILIATION-' + expected_attempt + '.json'), {
    'proof': proof, 'evidence_ref': ref, 'result': result.as_dict(),
    'original_attempts_unchanged': True, 'candidate_unchanged': True,
    'ledger_unchanged': True, 'provider_outcome': 'UNKNOWN_RETAINED', 'host_business_patches': 0})
print('NOT_APPLIED local effects; original receipts, candidate and ledger unchanged; upstream UNKNOWN retained', flush=True)
