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
from cgkn.telemetry.lean import ACTIVE, OFFLINE_TRIAL, artifact_identity, observe_artifact, PROTECTED, environment_identity, read, source_identity, step, write
from cgkn.state.store import FileRunStore

TRANSITIONS = {'OBSERVE': {'CANDIDATE'}, 'CANDIDATE': {'ABLATION_PASS', 'REJECTED'},
    'ABLATION_PASS': {'CANARY', 'AUTO_SKIP', 'ROLLBACK'}, 'CANARY': {'AUTO_SKIP', 'ROLLBACK'},
    'AUTO_SKIP': {'CLEANUP_READY', 'ROLLBACK'}, 'ROLLBACK': {'CANDIDATE'}, 'REJECTED': {'CANDIDATE'}}
_TRIAL = OFFLINE_TRIAL


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
        # This function is an explicitly invoked offline reader. Preserve the
        # original run report rather than rewriting historical observations.
        from cgkn.telemetry.lean import discover
        candidates = (discover(report.get('steps', []))
                      if report.get('discovery_status') == 'NOT_RUN_OFFLINE_ONLY'
                      else report.get('candidate_cuts', []))
        for row in candidates:
            key = content_hash([report.get('task_profile'), row.get('semantic_identity')])
            group = groups.setdefault(key, {'task_profile':report.get('task_profile'), 'runs':[], 'candidates':[], 'rollback_runs':[]})
            group['runs'].append(report.get('run_id')); group['candidates'].append(row['candidate_id'])
            if report.get('rollback_events'): group['rollback_runs'].append(report.get('run_id'))
    return list(groups.values())




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
    valid=(policy.get('state') in {'AUTO_SKIP','CANARY'} and policy.get('approved') is True
        and policy.get('implementation_hash') not in {None,'UNKNOWN'}
        and policy.get('component_ref')==ref and policy.get('task_profile')==scope.profile
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


def review_oracle(evidence, workspace):
    """Consume the ORIGINAL Oracle verdict; never change it or rerun effects."""
    path=os.environ.get('CGKN_LEAN_POLICY')
    if not path or evidence.status.value == 'PASS': return
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
