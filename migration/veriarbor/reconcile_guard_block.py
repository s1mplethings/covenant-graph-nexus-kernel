"""Prove a recorded pre-dispatch UNKNOWN latch made no new local effects."""
from resume_promotion import H, P, read, sha, put
from cgkn.state import FileRunStore
from cgkn.state.provenance import put_evidence, reference
from cgkn.state.task_feedback import digest
from cgkn.runtime import DAGRunner
from cgkn.executors import ExecutorRegistry
from cgkn.execution import BlockExecutionResult, BlockStatus

root=P/'promotion/run-05';project='iter132-promotion-studio';run='promotion-05';node='sem-node-0091'
store=FileRunStore(root/'state');base=store.run_dir(project,run)
prior=store.load_result(project,run,node)
assert prior.attempt_id=='attempt-0057' and prior.error.details.get('category')=='prior_submission_unknown'
assert not prior.usage.get('completion_calls')
matches=[]
for path in (base/'provider_calls').glob('*/request.json'):
    with path.open('rb') as f:head=f.read(8192)
    if b'attempt-0057' in head:
        identity=read(path).get('execution_identity')
        if identity and identity.get('node_id')==node and identity.get('attempt_id')==prior.attempt_id:matches.append(str(path))
assert not matches
origin_path=base/'attempts/sem-node-0092/attempt-0040.json';origin=read(origin_path)
assert origin['status']=='SUCCEEDED'
protected=origin['metadata']['deliverable_check']['subjects'];assert set(protected)=={'early_main.py'}
stage=base/'candidates'/node/prior.attempt_id
assert all(sha(root/'candidate'/n)==sha(stage/n)==h for n,h in protected.items())
leaf=next(n for n in read(base/'capability_tree.json')['nodes'] if n['id']==node)['config']['leaf_contract']
assert set(leaf['target_scope'])==set(protected)
reads={n:sha(stage/n) for n in leaf['read_scope']};assert all(sha(root/'candidate'/n)==h for n,h in reads.items())
assert not (base/'publication_intents'/node/(prior.attempt_id+'.json')).exists()
old={str(p.relative_to(base)):sha(p) for p in (base/'attempts').rglob('*.json')}
ledger=P.parents[1]/'CGKN-ITER-076/global-provider-budget.json';ledger_hash=sha(ledger)
proof={'kind':'LocalBoundedFileEffectInspection','disposition':'NOT_APPLIED','source_receipt_sha256':digest(prior.as_dict()),'target_scope':leaf['target_scope'],
    'current_targets_match_staged_and_successful_dependency_origin':protected,'prior_successful_origin_ref':reference(store.root,origin_path),'read_dependencies_match_stage':reads,
    'publication_intent_absent':True,'new_recorded_requests_for_attempt':matches,'guard_receipt_ref':reference(store.root,base/'attempts'/node/(prior.attempt_id+'.json')),
    'scope':'The admission latch prevented any new Provider request. Original interrupted request remains unresolved and cannot be replayed. No business acceptance inferred.'}
ref=put_evidence(store,project,run,proof)
checker=BlockExecutionResult(project_id=project,run_id=run,node_id='verify-veriarbor-guard-block57',attempt_id='attempt-0001',executor_ref='verify.local-file-effects@1',status=BlockStatus.SUCCEEDED,outputs={'effect_reconciliation':{'source_receipt_hash':digest(prior.as_dict()),'disposition':'NOT_APPLIED','evidence_refs':[ref]}})
store.save_result(checker);result=DAGRunner(ExecutorRegistry(),store,reconciliation_executors=('verify.local-file-effects@1',)).reconcile_effects(project,run,node,checker)
assert sha(ledger)==ledger_hash and all(sha(base/p)==h for p,h in old.items())
put(H/'migration/veriarbor/GUARD_BLOCK57_RECONCILIATION.json',{'proof':proof,'result':result.as_dict(),'ledger_unchanged':True,'old_attempts_unchanged':True,'provider_calls':0,'host_business_patches':0})
print('Pre-dispatch guard block NOT_APPLIED; old UNKNOWN still retained')
