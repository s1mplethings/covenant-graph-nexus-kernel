"""Qualified configuration and bounded offline comparisons, not a workflow runner."""
from __future__ import annotations

import copy
from contextvars import ContextVar
import os
import re
from pathlib import Path, PureWindowsPath
import tempfile
import time

from cgkn.artifacts.hash import content_hash
from cgkn.application.verification import OracleExecutor, OracleStatus
from cgkn.telemetry.lean import ACTIVE, PROTECTED, environment_identity, read, source_identity, step, write
from cgkn.state.store import FileRunStore

TRANSITIONS = {'OBSERVE': {'CANDIDATE'}, 'CANDIDATE': {'ABLATION_PASS', 'REJECTED'},
    'ABLATION_PASS': {'CANARY', 'AUTO_SKIP', 'ROLLBACK'}, 'CANARY': {'AUTO_SKIP', 'ROLLBACK'},
    'AUTO_SKIP': {'CLEANUP_READY', 'ROLLBACK'}, 'ROLLBACK': {'CANDIDATE'}, 'REJECTED': {'CANDIDATE'}}
_TRIAL = ContextVar('cgkn_isolated_lean_trial',default=None)


def transition(state, target, *, qualified=False, structural_proof=False):
    if target not in TRANSITIONS.get(state, set()): raise ValueError('invalid LeanPolicy transition')
    if target in {'ABLATION_PASS', 'CANARY', 'AUTO_SKIP'} and not qualified: raise ValueError('qualification required')
    if target == 'CLEANUP_READY' and not structural_proof: raise ValueError('dynamic entry and compatibility proof required')
    return target


def aggregate(report_paths, *, limit=100):
    """Bounded projection over caller-selected Run/Corpus reports, no new database."""
    groups = {}
    for path in list(report_paths)[:limit]:
        report = read(path, {})
        for row in report.get('candidate_cuts', []):
            key = content_hash([report.get('task_profile'), row.get('semantic_identity')])
            group = groups.setdefault(key, {'task_profile':report.get('task_profile'), 'runs':[], 'candidates':[], 'rollback_runs':[]})
            group['runs'].append(report.get('run_id')); group['candidates'].append(row['candidate_id'])
            if report.get('rollback_events'): group['rollback_runs'].append(report.get('run_id'))
    return list(groups.values())


def evaluate(candidate, cases, run_case, evidence_dir, *, max_cases=12, max_seconds=120, cooldown_seconds=3600):
    """Call an EXISTING runner in isolated workspaces; existing Oracle owns quality.

    run_case(variant, case, workspace) materializes a local project. It cannot
    supply its own verdict. Cases carry frozen OracleSpec objects, including a
    separate holdout. No replay is performed in a user production workspace.
    """
    directory = Path(evidence_dir).resolve(); directory.mkdir(parents=True, exist_ok=True)
    identity = content_hash([candidate, [{'id':c['id'], 'input':c['input'], 'split':c['split'],
        'expected_pass':c['expected_pass'], 'subjects':c.get('subjects',[]), 'oracles':[o.as_dict() for o in c['oracles']]} for c in cases],
        environment_identity(), source_identity(run_case)])
    path = directory/(identity.split(':')[-1]+'.json'); previous = read(path)
    if previous and time.time() < previous.get('next_review_after', 0):
        return {**previous, 'reused_evaluation':True}
    started=time.perf_counter(); cpu=time.process_time(); trials=[]
    reason = None
    if candidate.get('protected') or set(candidate.get('protections', [])) & PROTECTED:
        reason='PROTECTED_RESPONSIBILITY'
    elif candidate.get('kind') != 'DUPLICATE_DETERMINISTIC' or not candidate.get('pure_inputs'):
        reason='INSUFFICIENT_EVIDENCE: only explicitly pure deterministic transforms qualify in V1'
    elif not all(isinstance(candidate.get(k),str) and re.fullmatch(r'sha256:[0-9a-f]{64}',candidate[k]) for k in ('implementation_hash','component_contract_hash')):
        reason='INSUFFICIENT_EVIDENCE: known source and contract hashes required'
    elif any(candidate.get(k) in (None,'','UNKNOWN','NOT_AVAILABLE') for k in ('task_profile','component_ref')):
        reason='INSUFFICIENT_EVIDENCE: known task and Component scope required'
    elif len(cases)>max_cases or len(cases)<4 or not all(c.get('oracles') for c in cases):
        reason='INSUFFICIENT_EVIDENCE: bounded positive/negative and held-out corpus required'
    elif not all(c.get('subjects') and all(not Path(n).anchor and not PureWindowsPath(n).drive and '..' not in Path(n).parts for n in c['subjects']) for c in cases):
        reason='INSUFFICIENT_EVIDENCE: workspace-contained subjects required'
    elif not {('qualification',True),('qualification',False),('holdout',True),('holdout',False)}.issubset({(c['split'], bool(c['expected_pass'])) for c in cases}):
        reason='INSUFFICIENT_EVIDENCE: each split needs positive and negative controls'
    status='BLOCKED' if reason else 'PASS'
    if not reason:
        for case in cases:
            pair=[]
            for variant in ('original', 'candidate'):
                if time.perf_counter()-started>max_seconds:
                    status='INCONCLUSIVE';reason='EXPERIMENT_BUDGET_EXHAUSTED';break
                with tempfile.TemporaryDirectory(prefix='lean-ablation-',dir=directory) as temp:
                    workspace=Path(temp); clock=time.perf_counter(); subjects={}
                    try:
                        token=_TRIAL.set({'root':workspace.resolve(),'candidate':candidate} if variant=='candidate' else None)
                        try: run_case(variant, copy.deepcopy(case), workspace)
                        finally: _TRIAL.reset(token)
                        for name in case['subjects']:
                            subject=(workspace/name).resolve()
                            if not subject.is_relative_to(workspace.resolve()): raise ValueError('subject escaped isolated workspace')
                            subjects[name]=content_hash(subject.read_text(encoding='utf-8')) if subject.is_file() else None
                        receipts=[OracleExecutor().execute(spec,workspace).as_dict() for spec in case['oracles']]
                        passed=all(r['status']==OracleStatus.PASS.value for r in receipts)
                        valid=all(r['status'] in {'PASS','FAIL'} for r in receipts)
                    except Exception as exc:
                        receipts=[];passed=False;valid=False
                        reason='HARNESS_'+type(exc).__name__
                    pair.append({'variant':variant, 'case_id':case['id'], 'split':case['split'],
                        'expected_pass':case['expected_pass'], 'oracle_pass':passed, 'valid_evaluation':valid,
                        'oracles':receipts, 'duration_ms':(time.perf_counter()-clock)*1000,
                        'actual_cost_cny':None, 'source_hash':source_identity(run_case),
                        'subject_hashes':subjects,
                        'lean_reports':[{'hash':content_hash(doc),'steps_executed':doc.get('steps_executed',0),
                            'cuts':doc.get('qualified_cuts_applied',[])} for doc in
                            (read(p,{}) for p in workspace.rglob('lean-report.json'))]})
            trials.extend(pair)
            if len(pair)!=2: break
            if any(not row['valid_evaluation'] for row in pair): status='INCONCLUSIVE'
            elif any(row['oracle_pass'] != case['expected_pass'] for row in pair): status='FAIL'
            elif pair[0]['subject_hashes'] != pair[1]['subject_hashes']: status='FAIL';reason='DETERMINISTIC_OUTPUT_MISMATCH'
            elif case['expected_pass'] and not any(r['cuts'] for r in pair[1]['lean_reports']):
                status='INCONCLUSIVE';reason='NO_ACTUAL_COUNTERFACTUAL_CUT'
    result={'schema_version':'1.0','candidate':candidate,'status':status,'reason':reason,
        'identity':identity,'trials':trials,'environment_hash':environment_identity(),
        'quality_tolerance':0,'deterministic_only':True,'extra_model_calls':0,'actual_cost_cny':None,
        'experiment_duration_ms':(time.perf_counter()-started)*1000,'experiment_cpu_ms':(time.process_time()-cpu)*1000,
        'created_at':time.time(),'next_review_after':time.time()+cooldown_seconds,
        'limitations':['A finite corpus is not universal purity proof; operator approval binds the audited source and input-only contract.']}
    result['receipt_hash']=content_hash(result);write(path,result)
    return {**result,'evidence_ref':str(path)}


def approve(receipt, policy_path, *, version, task_profile, component_ref, implementation_hash, max_age_seconds=604800):
    """Explicit local configuration operation; never called by an ordinary Run."""
    if not isinstance(implementation_hash,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',implementation_hash):
        raise ValueError('known implementation source required')
    path=Path(receipt['evidence_ref']); persisted=read(path, {})
    body={k:v for k,v in persisted.items() if k!='receipt_hash'}
    if persisted.get('receipt_hash')!=content_hash(body) or persisted.get('status')!='PASS': raise ValueError('qualified evidence required')
    if persisted.get('environment_hash')!=environment_identity(): raise ValueError('qualification environment mismatch')
    if persisted.get('candidate',{}).get('implementation_hash') != implementation_hash: raise ValueError('implementation binding mismatch')
    if persisted['candidate'].get('task_profile')!=task_profile or persisted['candidate'].get('component_ref')!=component_ref:
        raise ValueError('qualification task/component scope mismatch')
    policy={'schema_version':'1.0','version':version,'state':'AUTO_SKIP','approved':True,
        'task_profile':task_profile,'component_ref':component_ref,'implementation_hash':implementation_hash,
        'component_contract_hash':persisted['candidate']['component_contract_hash'],
        'environment_hash':environment_identity(),'evidence_ref':str(path.resolve()),'evidence_hash':persisted['receipt_hash'],
        'expires_at':time.time()+max_age_seconds,'rollback_target':'FULL_EXECUTION',
        'operation':'reuse_pure_transform','input_contract':'pure_inputs_v1','review_budget_ms':100,
        'structural_cleanup':'NOT_QUALIFIED'}
    write(policy_path,policy)
    return policy


def _revoke(path, expected_hash, reason):
    path=Path(path)
    if path.is_symlink(): return False
    path=path.resolve();store=FileRunStore(path.parent)
    with store.exclusive_file(path.with_suffix('.lock'),wait_seconds=1):
        current=read(path,{})
        if content_hash(current)!=expected_hash: return False
        write(path,{**current,'state':'ROLLBACK','rollback_reason':reason})
        return True


def rollback(scope, reason):
    scope.disabled=True
    scope.rollbacks.append({'reason':reason,'policy_hash':scope.policy_hash,'target':'FULL_EXECUTION_NEXT_RUN','irreversible_effects_undone':False})
    if scope.policy_path:
        scope.rollbacks[-1]['policy_revoked']=_revoke(scope.policy_path,scope.policy_hash,reason)


def eligible(scope, module, function):
    policy=scope.policy
    if scope.mode!='AUTO_QUALIFIED' or scope.disabled: return False
    ref=module['id']+'@'+str(module['version'])
    if policy.get('component_ref') != ref: return False
    if policy.get('state') not in {'AUTO_SKIP','CANARY'}: return False
    valid=(policy.get('approved') is True
        and policy.get('implementation_hash') not in {None,'UNKNOWN'}
        and policy.get('task_profile')==scope.profile
        and policy.get('operation')=='reuse_pure_transform' and policy.get('input_contract')=='pure_inputs_v1'
        and policy.get('environment_hash')==environment_identity()
        and policy.get('implementation_hash')==source_identity(function)
        and policy.get('component_contract_hash')==content_hash(module)
        and policy.get('expires_at',0)>time.time())
    if not valid:
        rollback(scope,'POLICY_SCOPE_SOURCE_ENVIRONMENT_OR_AGE_MISMATCH');return False
    receipt=read(policy.get('evidence_ref'),{})
    if receipt.get('status')!='PASS' or receipt.get('environment_hash')!=policy.get('environment_hash') or receipt.get('receipt_hash')!=policy.get('evidence_hash') or content_hash({k:v for k,v in receipt.items() if k!='receipt_hash'})!=policy.get('evidence_hash'):
        rollback(scope,'QUALIFICATION_EVIDENCE_INVALID');return False
    protections=set(module.get('metadata',{}).get('lean_protections',[]))
    pure=(module['implementation'].get('lean_input_only') is True and module['implementation']['kind']=='local_function'
          and not any(module.get('effects',{}).values()) and not protections & PROTECTED)
    if not pure: rollback(scope,'PROTECTED_OR_EFFECTFUL_COMPONENT')
    return pure


def artifact_identity(module, node, inputs, function, policy_ref, *, implementation_hash=None):
    return content_hash({'module':module,'config':node.get('config',{}),
        'inputs':{port:ref.content_hash for port,ref in inputs.items()},
        'implementation_hash':implementation_hash or source_identity(function),'environment':environment_identity(),'policy':policy_ref})


def artifact_reuse(runner, module, node, inputs, identity, function):
    scope=ACTIVE.get()
    if not scope: return None
    trial=_TRIAL.get()
    isolated=bool(trial and trial['root'] in runner.run_dir.parents
        and trial['candidate'].get('component_contract_hash')==content_hash(module)
        and trial['candidate'].get('implementation_hash')==source_identity(function)
        and module['implementation'].get('lean_input_only') is True
        and not any(module.get('effects',{}).values())
        and not set(module.get('metadata',{}).get('lean_protections',[])) & PROTECTED)
    if not isolated and not eligible(scope,module,function): return None
    # Existing node cache and ArtifactStore remain sole cache/lineage authority.
    for previous in reversed(scope.steps):
        # A native cache hit alone does not prove which implementation produced it.
        if previous.get('semantic_identity') != identity or previous['status'] != 'pass': continue
        try:
            refs=runner.cache.lookup(previous['step_id'],previous['execution_fingerprint'],runner.store)
            if not refs:
                rollback(scope,'CACHE_STALE_OR_MISSING');return None
            artifacts=[runner.store.resolve_artifact_ref(ref) for ref in refs]
            if (sorted(ref.content_hash for ref in refs)!=sorted(previous['output_hashes'])
                or any(a.producer.node_id!=previous['step_id'] for a in artifacts)):
                rollback(scope,'CACHE_LINEAGE_MISMATCH');return None
            contents={a.producer.output_port:a.content for a in artifacts}
            runner._validate_output_contents(module,contents)
            scope.applied.append({'step_id':node['id'],'source_step_id':previous['step_id'],
                'source_attempt_id':previous['attempt_id'],'input_hash':identity,'policy_hash':scope.policy_hash,
                'source_output_refs':[ref.as_dict() for ref in refs],
                'qualification':'ISOLATED_ABLATION_ONLY' if isolated else 'APPROVED'})
            return contents
        except (ValueError,OSError):
            rollback(scope,'CACHE_VALIDATION_FAILED');return None
    return None


def observe_artifact(runner, checkpoint, observation):
    scope=ACTIVE.get()
    if not scope or scope.mode=='OFF': return
    row=step(runner.run_dir.name,checkpoint['nodeId'],checkpoint['executionId'],'component',checkpoint['status'],
        duration_ms=checkpoint['durationMs'],
        input_hashes=[r['contentHash'] for r in checkpoint['inputArtifactRefs']],
        output_hashes=[r['contentHash'] for r in checkpoint['outputArtifactRefs']],
        effects=checkpoint['effectsSummary'], findings=[d.get('code','UNKNOWN') for d in checkpoint['diagnostics']],
        downstream_consumers=list(runner.graph.node_consumers.get(checkpoint['nodeId'],())),
        evidence_refs=[str(runner.run_dir/'checkpoints'/(checkpoint['nodeId']+'.json'))],
        reuse=checkpoint['cacheStatus']=='hit', execution_fingerprint=checkpoint['executionFingerprint'],
        semantic_identity=checkpoint['executionFingerprint'])
    row['component_ref']=checkpoint['componentRef']
    row.update(observation or {})
    scope.steps.append(row)


def review_oracle(evidence, workspace):
    """Consume the ORIGINAL Oracle verdict; never change it or rerun effects."""
    path=os.environ.get('CGKN_LEAN_POLICY')
    if not path or evidence.status is OracleStatus.PASS: return
    policy=read(path,{})
    if policy.get('state') not in {'AUTO_SKIP','CANARY'}: return
    root=Path(workspace).resolve()
    reports=[root/'lean-report.json',*list(root.glob('*/lean-report.json'))[:32]]
    for report_path in reports:
        report=read(report_path,{})
        if report.get('policy_hash')!=content_hash(policy) or not report.get('qualified_cuts_applied'): continue
        event={'reason':'INDEPENDENT_ORACLE_REGRESSION','oracle_id':evidence.oracle_id,
            'oracle_evidence_hash':content_hash(evidence.as_dict()),'target':'FULL_EXECUTION_NEXT_RUN','irreversible_effects_undone':False}
        event['policy_revoked']=_revoke(path,content_hash(policy),event['reason'])
        report.setdefault('rollback_events',[]).append(event)
        report.setdefault('quality_evidence_refs',[]).append({'oracle_id':evidence.oracle_id,'hash':event['oracle_evidence_hash']})
        write(report_path,report)
        if report_path.with_suffix('.md').is_symlink(): raise ValueError('report target must not be symlink')
        with report_path.with_suffix('.md').open('a',encoding='utf-8') as handle:
            handle.write('\nIndependent Oracle review: ROLLBACK to full execution for subsequent runs.\n')


def structural_candidates(inventory):
    required={'dynamic_entrypoints_reviewed','compatibility_preserved','behavior_equivalent','faults_passed','regression_passed','rollback_available','positive_deletion_benefit'}
    return [{**row,'state':'CANDIDATE','cleanup_gate':'SOURCE_BOUND_REVIEW_REQUIRED',
        'missing_proofs':sorted(required-set(row.get('proofs',[]))),
        'automatic_source_mutation':False} for row in inventory if row.get('duplicate_responsibility')]
