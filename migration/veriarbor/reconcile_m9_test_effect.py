"""Reconcile only bounded local files after the recorded M9 stream failure."""
from resume_promotion import H, P, read, sha, put
from cgkn.state import FileRunStore
from cgkn.state.provenance import put_evidence, reference
from cgkn.state.task_feedback import digest
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus

root=P/'promotion/run-05';project='iter132-promotion-studio';run='promotion-05';node='sem-node-0109'
store=FileRunStore(root/'state');base=store.run_dir(project,run)
prior=store.load_result(project,run,node)
assert prior.attempt_id=='attempt-0001' and prior.error.details['outcome_unknown']
request_dir=base/'provider_calls/82d2fdd58a01481ca634c21a9a38098e'
request=read(request_dir/'request.json');error=read(request_dir/'error.json')
assert request['execution_identity']==dict(project_id=project,run_id=run,node_id=node,attempt_id=prior.attempt_id)
assert error['outcome_unknown'] and not (request_dir/'response.json').exists()
leaf=next(n for n in read(base/'capability_tree.json')['nodes'] if n['id']==node)['config']['leaf_contract']
assert leaf['target_scope']==['tests/test_milestone_c511a8ebd29978f5ba97.py']
stage=base/'candidates'/node/prior.attempt_id
assert all(not (root/'candidate'/p).exists() and not (stage/p).exists() for p in leaf['target_scope'])
reads={p:sha(stage/p) for p in leaf['read_scope']}
assert all(sha(root/'candidate'/p)==v for p,v in reads.items())
assert not (base/'publication_intents'/node/(prior.attempt_id+'.json')).exists()
old={str(p.relative_to(base)):sha(p) for p in (base/'attempts').rglob('*.json')}
candidate={str(p.relative_to(root/'candidate')):sha(p) for p in (root/'candidate').rglob('*') if p.is_file()}
ledger=P.parents[1]/'CGKN-ITER-076/global-provider-budget.json';ledger_hash=sha(ledger)
proof={'kind':'LocalBoundedFileEffectInspection','disposition':'NOT_APPLIED',
    'source_receipt_sha256':digest(prior.as_dict()),'target_scope':leaf['target_scope'],
    'targets_absent_in_stage_and_workspace':True,'read_dependencies_match_stage':reads,
    'publication_intent_absent':True,'complete_recorded_response_absent':True,
    'raw_error_ref':reference(store.root,request_dir/'error.json'),
    'scope':'Local bounded file effects only. Upstream streaming outcome, tokens and cost remain UNKNOWN. Original request must not be replayed.'}
ref=put_evidence(store,project,run,proof)
checker=BlockExecutionResult(project_id=project,run_id=run,node_id='verify-veriarbor-m9-test-effects-109',
    attempt_id='attempt-0001',executor_ref='verify.local-file-effects@1',status=BlockStatus.SUCCEEDED,
    outputs={'effect_reconciliation':{'source_receipt_hash':digest(prior.as_dict()),'disposition':'NOT_APPLIED','evidence_refs':[ref]}})
store.save_result(checker)
result=DAGRunner(ExecutorRegistry(),store,reconciliation_executors=('verify.local-file-effects@1',)).reconcile_effects(project,run,node,checker)
assert sha(ledger)==ledger_hash and all(sha(base/p)==v for p,v in old.items())
assert candidate=={str(p.relative_to(root/'candidate')):sha(p) for p in (root/'candidate').rglob('*') if p.is_file()}
put(H/'migration/veriarbor/M9_TEST_EFFECT_RECONCILIATION.json',{'proof':proof,'result':result.as_dict(),
    'ledger_unchanged':True,'old_attempts_unchanged':True,'candidate_unchanged':True,'host_business_patches':0})
print('M9 local effects NOT_APPLIED; original upstream UNKNOWN retained unchanged.')
