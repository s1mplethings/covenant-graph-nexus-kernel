"""Recover an owned controller interruption without redispatching its request."""
import json
import os
from resume_promotion import H, P, read, sha, put
from cgkn.state import FileRunStore
from cgkn.state.provenance import put_evidence, reference
from cgkn.state.task_feedback import digest
from cgkn.orchestration.capability_tree import CapabilityTree
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus
from cgkn.providers import GatewayCompletionClient
from scripts import provider_api_budget as budget

root = P / 'promotion/run-05'; project = 'iter132-promotion-studio'; run = 'promotion-05'; node = 'sem-node-0091'
store = FileRunStore(root / 'state'); base = store.run_dir(project, run)
key = '40aa69df42f2487a81263209c373c619'
identity = 'sha256:6e20392ae01e78bedf5b32553b36a70ef1ef994549c26d0d3fb84b6ca0b2d01f'
request_path = base / 'provider_calls' / key / 'request.json'
request = read(request_path)
assert request['execution_identity'] == {'project_id':project,'run_id':run,'node_id':node,'attempt_id':'attempt-0055'}
client = GatewayCompletionClient('http://127.0.0.1:1', 'unused-read-only')
response = client.recover_cached(request_identity=identity, schema=request['request'].get('schema'), cache_dir=H / '.cgkn/domestic-gateway/recovery-responses')
assert response is None, 'Complete cache appeared: retain and inspect before recovery'
ledger = P.parents[1] / 'CGKN-ITER-076/global-provider-budget.json'
before = read(ledger)
for k,v in before['limits'].items():
    if v is not None: os.environ['CGKN_PROVIDER_' + k.upper()] = str(v)
owner = next(x['owner_pid'] for x in before['calls'] if x['request_identity'] == identity)
after = budget.reconcile_incomplete_calls(ledger, process_alive=lambda pid: True if pid != owner else budget._process_alive(pid))
assert next(x for x in after['calls'] if x['request_identity'] == identity)['status'] == 'INTERRUPTED_UNKNOWN'
assert [x for x in before['calls'] if x['request_identity'] != identity] == [x for x in after['calls'] if x['request_identity'] != identity]
tree = CapabilityTree.from_dict(read(base / 'capability_tree.json'))
runner = DAGRunner(ExecutorRegistry(), store, reconciliation_executors=('verify.local-file-effects@1',))
runner.recover_interrupted(project, run, tree)
prior = store.load_result(project, run, node)
assert prior.attempt_id == 'attempt-0055' and prior.error.details['outcome_unknown']
stage = base / 'candidates' / node / prior.attempt_id
leaf = next(n for n in read(base / 'capability_tree.json')['nodes'] if n['id'] == node)['config']['leaf_contract']
origin_path = base / 'attempts' / node / 'attempt-0054.json'
origin = read(origin_path); assert origin['status'] == 'SUCCEEDED'
protected = origin['metadata']['deliverable_check']['subjects']
assert set(protected) == set(leaf['target_scope']) == {'early_main.py'}
assert all(sha(root/'candidate'/n) == sha(stage/n) == h for n,h in protected.items())
reads = {n:sha(stage/n) for n in leaf['read_scope']}
assert all(sha(root/'candidate'/n) == h for n,h in reads.items())
assert not (base/'publication_intents'/node/(prior.attempt_id+'.json')).exists()
old = {str(p.relative_to(base)):sha(p) for p in (base/'attempts').rglob('*.json')}
ledger_hash = sha(ledger)
proof = {'kind':'LocalBoundedFileEffectInspection','disposition':'NOT_APPLIED',
    'source_receipt_sha256':digest(prior.as_dict()), 'target_scope':leaf['target_scope'],
    'existing_targets_match_prior_successful_origin_stage_and_workspace':protected,
    'prior_successful_origin_ref':reference(store.root,origin_path), 'read_dependencies_match_stage':reads,
    'publication_intent_absent':True,'original_request_ref':reference(store.root,request_path),
    'controller_interruption_receipt_ref':reference(store.root,base/'attempts'/node/(prior.attempt_id+'.json')),
    'scope':'Local file effects only; interrupted upstream response/usage/cost UNKNOWN remains. Original request is not retried.'}
ref = put_evidence(store,project,run,proof)
checker = BlockExecutionResult(project_id=project,run_id=run,node_id='verify-veriarbor-controller-interruption',attempt_id='attempt-0001',executor_ref='verify.local-file-effects@1',status=BlockStatus.SUCCEEDED,outputs={'effect_reconciliation':{'source_receipt_hash':digest(prior.as_dict()),'disposition':'NOT_APPLIED','evidence_refs':[ref]}})
store.save_result(checker); result = runner.reconcile_effects(project,run,node,checker)
assert sha(ledger) == ledger_hash and all(sha(base/p) == h for p,h in old.items())
put(H/'migration/veriarbor/CONTROLLER_INTERRUPTION_RECOVERY.json',{'proof':proof,'result':result.as_dict(),'upstream_outcome':'UNKNOWN_RETAINED','complete_cache':'MISS','provider_calls':0,'host_business_patches':0,'old_attempts_unchanged':True,'other_ledger_rows_unchanged':True})
print('Interrupted call retained UNKNOWN; local files NOT_APPLIED; no redispatch')
