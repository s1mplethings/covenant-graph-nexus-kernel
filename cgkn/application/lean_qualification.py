"""Explicit offline application qualification using the existing Oracle executor."""
import copy
import re
import tempfile
import time
from pathlib import Path, PureWindowsPath
from cgkn.artifacts.hash import content_hash
from cgkn.application.verification import OracleExecutor, OracleStatus
from cgkn.telemetry.lean import OFFLINE_TRIAL, PROTECTED, environment_identity, read, source_identity, write

_TRIAL = OFFLINE_TRIAL

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

