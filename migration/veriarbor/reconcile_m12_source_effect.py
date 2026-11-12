"""Inspect absent new-file effects after the first M12 stream failure."""
from resume_promotion import H, P, read, sha, put
from cgkn.state import FileRunStore
from cgkn.state.provenance import put_evidence, reference
from cgkn.state.task_feedback import digest
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus

root=P/'promotion/run-05';project='iter132-promotion-studio';run='promotion-05';node='sem-node-0141'
store=FileRunStore(root/'state');base=store.run_dir(project,run)
prior=store.load_result(project,run,node)
assert prior.attempt_id=='attempt-0001' and prior.error.details['outcome_unknown']
request_dir=base/'provider_calls/2327705b29644985b36918eedb208464'
execution=dict(project_id=project,run_id=run,node_id=node,attempt_id=prior.attempt_id)
assert read(request_dir/'request.json')['execution_identity']==execution
assert read(request_dir/'error.json')['outcome_unknown'] and not (request_dir/'response.json').exists()
assert read(root/'continuations/veriarbor-48/cache-recovery-observation.json')['complete_valid_response_found'] is False
calls=[p for p in (base/'provider_calls').glob('*/request.json') if read(p).get('execution_identity')==execution]
assert calls==[request_dir/'request.json']
leaf=next(n for n in read(base/'capability_tree.json')['nodes'] if n['id']==node)['config']['leaf_contract']
assert leaf['target_scope']==['main.py']
stage=base/'candidates'/node/prior.attempt_id
assert not (stage/'main.py').exists() and not (root/'candidate/main.py').exists()
reads={p:sha(stage/p) for p in leaf['read_scope']}
assert all(sha(root/'candidate'/p)==v for p,v in reads.items())
assert not (base/'publication_intents'/node/(prior.attempt_id+'.json')).exists()
old={str(p.relative_to(base)):sha(p) for p in (base/'attempts').rglob('*.json')}
candidate={str(p.relative_to(root/'candidate')):sha(p) for p in (root/'candidate').rglob('*') if p.is_file()}
ledger=P.parents[1]/'CGKN-ITER-076/global-provider-budget.json';ledger_hash=sha(ledger)
proof={'kind':'LocalBoundedFileEffectInspection','disposition':'NOT_APPLIED',
 'source_receipt_sha256':digest(prior.as_dict()),'target_scope':leaf['target_scope'],
 'target_absent_in_stage_and_candidate':True,'read_dependencies_match_stage':reads,
 'failed_request':str(request_dir),'publication_intent_absent':True,
 'failed_request_complete_response_absent':True,
 'cache_recovery_ref':str(root/'continuations/veriarbor-48/cache-recovery-observation.json'),
 'raw_error_ref':reference(store.root,request_dir/'error.json'),
 'scope':'Local bounded file effects only. Upstream outcome/tokens/cost remain UNKNOWN; no original request replay.'}
ref=put_evidence(store,project,run,proof)
checker=BlockExecutionResult(project_id=project,run_id=run,node_id='verify-veriarbor-m12-source-effects-141-a1',
 attempt_id='attempt-0001',executor_ref='verify.local-file-effects@1',status=BlockStatus.SUCCEEDED,
 outputs={'effect_reconciliation':{'source_receipt_hash':digest(prior.as_dict()),'disposition':'NOT_APPLIED','evidence_refs':[ref]}})
store.save_result(checker)
result=DAGRunner(ExecutorRegistry(),store,reconciliation_executors=('verify.local-file-effects@1',)).reconcile_effects(project,run,node,checker)
assert sha(ledger)==ledger_hash and all(sha(base/p)==v for p,v in old.items())
assert candidate=={str(p.relative_to(root/'candidate')):sha(p) for p in (root/'candidate').rglob('*') if p.is_file()}
put(H/'migration/veriarbor/M12_SOURCE_EFFECT_RECONCILIATION.json',{'proof':proof,'result':result.as_dict(),
 'ledger_unchanged':True,'old_attempts_unchanged':True,'candidate_unchanged':True,'host_business_patches':0})
print('M12 source attempt1 local effects NOT_APPLIED; upstream UNKNOWN preserved.')
