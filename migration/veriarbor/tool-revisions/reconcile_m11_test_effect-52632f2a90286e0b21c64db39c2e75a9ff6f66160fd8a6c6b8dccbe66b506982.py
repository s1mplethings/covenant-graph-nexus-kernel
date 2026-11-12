"""Inspect existing-file identity after the sole M11 attempt6 stream failure."""
from resume_promotion import H, P, read, sha, put
from cgkn.state import FileRunStore
from cgkn.state.provenance import put_evidence, reference
from cgkn.state.task_feedback import digest
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus

root=P/'promotion/run-05';project='iter132-promotion-studio';run='promotion-05';node='sem-node-0118'
store=FileRunStore(root/'state');base=store.run_dir(project,run)
prior=store.load_result(project,run,node)
assert prior.attempt_id=='attempt-0006' and prior.error.details['outcome_unknown']
request_dir=base/'provider_calls/c8869d683458438da406e37c8bf73d8d'
request=read(request_dir/'request.json');error=read(request_dir/'error.json')
execution=dict(project_id=project,run_id=run,node_id=node,attempt_id=prior.attempt_id)
assert request['execution_identity']==execution
assert error['outcome_unknown'] and not (request_dir/'response.json').exists()
calls=[p for p in (base/'provider_calls').glob('*/request.json') if read(p).get('execution_identity')==execution]
assert calls==[request_dir/'request.json']
leaf=next(n for n in read(base/'capability_tree.json')['nodes'] if n['id']==node)['config']['leaf_contract']
assert leaf['target_scope']==['tests/test_milestone_dbb8341c8910593063a8.py']
stage=base/'candidates'/node/prior.attempt_id
frozen=read(H/'migration/veriarbor/m11-generated-tests-350e97b9/receipt.json')['source_identities']
targets={p:sha(root/'candidate'/p) for p in leaf['target_scope']}
assert all(sha(stage/p)==value==frozen[p] for p,value in targets.items())
reads={p:sha(stage/p) for p in leaf['read_scope']}
assert all(sha(root/'candidate'/p)==v for p,v in reads.items())
assert not (base/'publication_intents'/node/(prior.attempt_id+'.json')).exists()
old={str(p.relative_to(base)):sha(p) for p in (base/'attempts').rglob('*.json')}
candidate={str(p.relative_to(root/'candidate')):sha(p) for p in (root/'candidate').rglob('*') if p.is_file()}
ledger=P.parents[1]/'CGKN-ITER-076/global-provider-budget.json';ledger_hash=sha(ledger)
proof={'kind':'LocalBoundedFileEffectInspection','disposition':'NOT_APPLIED',
 'source_receipt_sha256':digest(prior.as_dict()),'target_scope':leaf['target_scope'],
 'target_hashes_identical_to_stage_and_prior_frozen_test':targets,'read_dependencies_match_stage':reads,
 'sole_request_in_attempt':str(calls[0]),'publication_intent_absent':True,'complete_recorded_response_absent':True,
 'raw_error_ref':reference(store.root,request_dir/'error.json'),
 'scope':'Local bounded file effects only. Upstream outcome/tokens/cost remain UNKNOWN; no original request replay.'}
ref=put_evidence(store,project,run,proof)
checker=BlockExecutionResult(project_id=project,run_id=run,node_id='verify-veriarbor-m11-test-effects-118-a6',
 attempt_id='attempt-0001',executor_ref='verify.local-file-effects@1',status=BlockStatus.SUCCEEDED,
 outputs={'effect_reconciliation':{'source_receipt_hash':digest(prior.as_dict()),'disposition':'NOT_APPLIED','evidence_refs':[ref]}})
store.save_result(checker)
result=DAGRunner(ExecutorRegistry(),store,reconciliation_executors=('verify.local-file-effects@1',)).reconcile_effects(project,run,node,checker)
assert sha(ledger)==ledger_hash and all(sha(base/p)==v for p,v in old.items())
assert candidate=={str(p.relative_to(root/'candidate')):sha(p) for p in (root/'candidate').rglob('*') if p.is_file()}
put(H/'migration/veriarbor/M11_TEST_EFFECT_RECONCILIATION.json',{'proof':proof,'result':result.as_dict(),
 'ledger_unchanged':True,'old_attempts_unchanged':True,'candidate_unchanged':True,'host_business_patches':0})
print('M11 test attempt6 local effects NOT_APPLIED; upstream UNKNOWN preserved.')
