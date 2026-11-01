"""Derived subtraction reports over existing receipts; never execution authority."""
from __future__ import annotations

from contextvars import ContextVar
from functools import wraps, lru_cache
from contextlib import contextmanager
import hashlib
import inspect
import json
import os
from pathlib import Path
import time
import logging
import marshal

from cgkn.artifacts.hash import content_hash
from cgkn.state.store import FileRunStore

ACTIVE = ContextVar('cgkn_lean_report', default=None)
MODES = {'OFF', 'OBSERVE', 'AUTO_QUALIFIED'}
PROTECTED = {'budget', 'unknown', 'permission', 'approval', 'oracle', 'delivery', 'evidence', 'cancel', 'recovery', 'required'}


def read(path, default=None):
    try:
        if path is None or Path(path).is_symlink(): return default
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write(path, value):
    if Path(path).is_symlink(): raise ValueError('derived report target must not be a symlink')
    path = Path(path).resolve()
    FileRunStore(path.parent).atomic_json(path, value)


@lru_cache(maxsize=1)
def environment_identity():
    import platform
    import sys
    from importlib.metadata import distributions
    root=Path(__file__).resolve().parents[1]
    execution_sources=('runtime/runner.py','runtime/cache.py','runtime/fingerprint.py','runtime/effects.py',
        'runtime/context.py','compiler/artifact_graph.py','artifacts/store.py','artifacts/models.py',
        'component/adapter.py','component/execution.py','component/spec.py','state/store.py',
        'application/verification/executor.py','application/verification/contracts.py',
        'telemetry/lean.py','telemetry/lean_policy.py')
    return content_hash({'python': sys.version, 'platform': platform.platform(),
        'execution_sources':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in execution_sources},
        'packages':sorted((d.metadata.get('Name',''),d.version) for d in distributions())})


def source_identity(function):
    path = inspect.getsourcefile(function)
    if not path or not Path(path).is_file():
        return 'UNKNOWN'
    code=getattr(function,'__code__',None)
    if code is None: return 'UNKNOWN'
    return content_hash([hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        hashlib.sha256(marshal.dumps(code,0)).hexdigest(),function.__module__,function.__qualname__])


def discover(steps):
    """Suggestions only. Similarity or silence never authorizes a cut."""
    seen = {}; candidates = []
    for row in steps:
        identity = row.get('semantic_identity')
        if identity and identity in seen:
            previous = seen[identity]
            protected = bool(set(row.get('protections', ())) & PROTECTED)
            candidates.append({'candidate_id': content_hash([previous['step_id'], row['step_id'], identity]),
                'kind': 'DUPLICATE_DETERMINISTIC' if row.get('pure_inputs') else {
                    'agent_turn':'REDUNDANT_AGENT_TURN','provider':'REDUNDANT_MODEL_CALL',
                    'communication':'REDUNDANT_COMMUNICATION','verification':'OPTIONAL_VERIFICATION',
                    'recovery':'NO_PROGRESS_RETRY'}.get(row['step_kind'],'REPEATED_WORK'),
                'state': 'REJECTED' if protected else 'CANDIDATE', 'step_id': row['step_id'],
                'replacement_step': previous['step_id'], 'semantic_identity': identity,
                'effects': row['effects'], 'downstream_consumers': row['downstream_consumers'],
                'protected': protected, 'historical_defects_found': 'UNKNOWN',
                'pure_inputs':row.get('pure_inputs',False),'protections':row.get('protections',[]),
                'implementation_hash':row.get('implementation_hash','UNKNOWN'),
                'component_contract_hash':row.get('component_contract_hash','UNKNOWN'),
                'task_profile':row['task_profile'],'component_ref':row.get('component_ref','UNKNOWN'),
                'expected_savings_ms': row.get('duration_ms'), 'confirmed_savings_cny': None,
                'risk': 'LOW' if row.get('pure_inputs') and not protected else 'UNQUALIFIED',
                'required_validation': ['same inputs/source/environment', 'independent Oracle', 'negative controls', 'held-out cases', 'bounded combination test'],
                'reason': 'protected responsibility' if protected else 'counterfactual required; repeated output is not causal proof'})
        if identity:
            seen[identity] = row
    return candidates


def step(run_id, step_id, attempt_id, kind, status, **values):
    row = dict(run_id=run_id, step_id=step_id, attempt_id=attempt_id, task_profile='UNKNOWN',
        step_kind=kind, status=status, input_hashes=[], output_hashes=[], duration_ms=None,
        provider_request_ids=[], actual_cost_cny=None, effects=[], findings=[],
        downstream_consumers=[], evidence_refs=[], policy_version='observe-v1',
        executor_version='UNKNOWN', environment_hash=environment_identity(), reuse=False,
        protections=[], semantic_identity=None)
    row.update(values)
    return row


def project_steps(directory, run_id):
    """Read attempts, not merely the latest per-node result; never copy prompts."""
    rows = []
    graph = read(directory/'execution_dag.json', {})
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    seen=set()
    paths=sorted((directory/'execution_receipts').glob('*/*.json'))+sorted((directory/'node_results').glob('*.json'))
    for path in paths:
        doc = read(path, {})
        identity=(doc.get('node_id'),doc.get('attempt_id'))
        if identity in seen: continue
        seen.add(identity)
        node = nodes.get(doc.get('node_id'), {})
        config = node.get('config', {})
        checked_path=directory/'node_results'/(str(doc.get('node_id','unknown'))+'.json')
        checked=read(checked_path,{})
        usage=doc.get('usage',{})
        calls=usage.get('completion_calls',[])
        rows.append(step(run_id, doc.get('node_id', 'UNKNOWN'), doc.get('attempt_id', 'UNKNOWN'),
            'block', doc.get('status', 'UNKNOWN'), duration_ms=doc.get('duration_ms'),
            input_hashes=[content_hash(config.get('inputs', {}))],
            output_hashes=[content_hash(doc.get('outputs', {}))], effects=list(config.get('effects', [])),
            executor_version=doc.get('executor_ref', 'UNKNOWN'),
            provider_request_ids=sorted({str(c['request_id']) for c in calls if c.get('request_id')} | ({str(usage['request_id'])} if usage.get('request_id') else set())),
            input_tokens=usage.get('prompt_tokens'),output_tokens=usage.get('completion_tokens'),
            downstream_consumers=[n['id'] for n in nodes.values() if doc.get('node_id') in n.get('depends_on', [])],
            evidence_refs=[str(path)], protections=['required'],
            quality_evidence_refs=[str(checked_path)] if checked.get('attempt_id')==doc.get('attempt_id') and checked.get('metadata',{}).get('checker_receipt') else [],
            semantic_identity=content_hash([doc.get('executor_ref'), config.get('inputs'), config.get('action'), doc.get('outputs')]) ))
    return rows


def checkpoint_steps(directory, run_id):
    rows=[]
    for path in sorted((directory/'checkpoints').glob('*.json')):
        doc=read(path,{})
        if not isinstance(doc,dict) or not doc.get('executionId'): continue
        rows.append(step(run_id,doc['nodeId'],doc['executionId'],'component',doc.get('status','UNKNOWN'),
            input_hashes=[r['contentHash'] for r in doc.get('inputArtifactRefs',[])],
            output_hashes=[r['contentHash'] for r in doc.get('outputArtifactRefs',[])],
            duration_ms=doc.get('durationMs'),effects=doc.get('effectsSummary',{}),
            evidence_refs=[str(path)],reuse=doc.get('cacheStatus')=='hit',
            semantic_identity=doc.get('executionFingerprint')))
    return rows


def phase_steps(directory, run_id):
    path=directory/'provider_phase_log.jsonl';rows=[]
    if not path.is_file(): return rows
    for number,line in enumerate(path.read_text(encoding='utf-8').splitlines()):
        try: doc=json.loads(line)
        except ValueError: continue
        rows.append(step(run_id,str(doc.get('phase','UNKNOWN')),str(doc.get('attempt_id','NOT_AVAILABLE')),
            'provider',str(doc.get('status','UNKNOWN')),duration_ms=doc['elapsed_seconds']*1000 if doc.get('elapsed_seconds') is not None else None,
            evidence_refs=[str(path)+':'+str(number+1)],protections=['required']))
    return rows


def agent_steps(directory, run_id):
    path=directory/'events.jsonl';rows=[]
    if not path.is_file(): return rows
    for number,line in enumerate(path.read_text(encoding='utf-8').splitlines()):
        try: event=json.loads(line)
        except ValueError: continue
        if event.get('event_type') not in {'AGENT_DECISION','AGENT_DECISION_REJECTED'}: continue
        data=event.get('data',{})
        rows.append(step(run_id,str(data.get('decision_id',event.get('event_id','UNKNOWN'))),
            str(data.get('attempt_id','NOT_AVAILABLE')),'agent_turn',event['event_type'],
            input_hashes=[data['context_hash']] if data.get('context_hash') else [],
            semantic_identity=content_hash([data.get('context_hash'),data.get('request_run'),data.get('finish')]),
            evidence_refs=[str(path)+':'+str(number+1)],protections=['required']))
    return rows


def session_steps(path, run_id):
    rows = []; previous = None
    if not path or not Path(path).is_file():
        return rows
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines()):
        try: event = json.loads(line)
        except ValueError: continue
        if event.get('kind') == 'assistant':
            fingerprint = content_hash(event.get('actions', []))
            rows.append(step(run_id, 'turn-'+str(event.get('turn', number)), event.get('attempt_id','NOT_AVAILABLE'), 'agent_turn',
                'OBSERVED', semantic_identity=fingerprint,
                findings=['REPEATED_ACTION_PROPOSAL'] if fingerprint == previous else [],
                evidence_refs=[str(path)+':'+str(number+1)]))
            previous = fingerprint
        if event.get('kind') == 'tool_result' and 'result' in event:
            action = event.get('action', {})
            rows.append(step(run_id, 'action-'+str(number), event.get('attempt_id','NOT_AVAILABLE'), 'action',
                'SUCCESS_CLAIM' if event['result'].get('ok') else 'FAILED',
                input_hashes=[content_hash(action)], output_hashes=[content_hash(event['result'])],
                semantic_identity=content_hash([action, event['result']]), effects=['UNKNOWN'],
                protections=['required'], evidence_refs=[str(path)+':'+str(number+1)]))
    return rows


class LeanRun:
    """Ephemeral projection and frozen configuration; persistent authority stays put."""
    def __init__(self, directory, profile, *, mode=None, policy_path=None, inherited=None, fresh=False):
        setup_wall=time.perf_counter();setup_cpu=time.process_time()
        self.directory = Path(directory).resolve(); self.profile = profile
        self.run_id=self.directory.name
        self.mode = mode or os.environ.get('CGKN_LEAN_MODE', 'OBSERVE')
        if self.mode not in MODES: raise ValueError('invalid LeanLoop mode')
        self.policy_path = Path(policy_path or os.environ['CGKN_LEAN_POLICY']).absolute() if policy_path or os.environ.get('CGKN_LEAN_POLICY') else None
        self.policy = read(self.policy_path, {}) if self.policy_path else {}
        if inherited:
            self.policy=json.loads(json.dumps(inherited.policy));self.mode=inherited.mode
            self.policy_path=inherited.policy_path
        self.steps = []; self.rollbacks = []; self.applied = []; self.disabled = self.policy.get('state')=='ROLLBACK'
        self.started = time.perf_counter()
        snapshot = self.directory/'lean-policy-snapshot.json'
        previous = read(snapshot) if not fresh else None
        if not fresh and snapshot.exists() and (not isinstance(previous,dict) or not isinstance(previous.get('policy'),dict) or previous.get('policy_hash')!=content_hash(previous['policy'])):
            self.policy={};self.mode='OBSERVE';self.disabled=True
            self.rollbacks.append({'reason':'INVALID_FROZEN_POLICY','target':'FULL_EXECUTION','irreversible_effects_undone':False})
        elif previous:
            self.policy = previous['policy']
            if self.mode != 'OFF': self.mode = previous['mode']
        else:
            write(snapshot, {'schema_version':'1.0', 'mode':self.mode, 'policy':self.policy,
                'policy_hash':content_hash(self.policy), 'task_profile':profile})
        self.policy_hash = content_hash(self.policy)
        self.analysis_seconds=time.perf_counter()-setup_wall
        self.cpu_seconds=time.process_time()-setup_cpu

    def finish(self, status, *, incomplete=False, session_path=None):
        wall = time.perf_counter(); cpu = time.process_time()
        rows = self.steps if self.mode != 'OFF' else []
        if self.mode != 'OFF':
            rows = rows + project_steps(self.directory, self.run_id) + phase_steps(self.directory,self.run_id) + agent_steps(self.directory,self.run_id) + session_steps(session_path, self.run_id)
            if not self.steps: rows += checkpoint_steps(self.directory,self.run_id)
        rows=list({content_hash([r['run_id'],r['step_id'],r['attempt_id'],r['evidence_refs']]):r for r in rows}.values())
        for row in rows:
            if row['task_profile']=='UNKNOWN': row['task_profile'] = self.profile
            if 'policy_hash' not in row:
                row['policy_version'] = self.policy.get('version', 'observe-v1')
                row['policy_hash'] = self.policy_hash
        candidates = discover(rows) if self.mode != 'OFF' else []
        report = {'schema_version':'1.0', 'run_id':self.run_id, 'task_profile':self.profile,
            'mode':self.mode, 'policy_version':self.policy.get('version', 'observe-v1'), 'policy_hash':self.policy_hash,
            'report_status':'INCOMPLETE' if incomplete else 'COMPLETE', 'observed_task_status':status,
            'steps_observed':len(rows), 'steps_executed':sum(not r['reuse'] for r in rows),
            'steps_skipped':0, 'steps_reused':sum(bool(r['reuse']) for r in rows),
            'candidates_found':len(candidates), 'qualified_cuts_applied':self.applied,
            'candidate_cuts':candidates, 'steps':rows, 'actual_cost_cny':None, 'confirmed_savings_cny':None,
            'optimization_memory_bytes':'NOT_AVAILABLE', 'extra_model_calls':0, 'extra_tokens':0,
            'optimization_api_cost_cny':0, 'ablation_cost':'NOT_PERFORMED_IN_BUSINESS_RUN',
            'quality_evidence_refs':sorted({r for row in rows for r in row.get('quality_evidence_refs',[])}),
            'rollback_events':self.rollbacks,
            'limitations':['Costs unavailable unless reconciled by the original ledger; unknown is not zero.',
                'Execution success is not independent business acceptance.',
                'No candidates' if not candidates else 'Candidates do not authorize deletion.',
                'OFF: only disabled report envelope' if self.mode == 'OFF' else 'Only existing receipts and bounded observations are projected.']}
        text = ('# CGKN LeanLoop\n\n'+f"Mode: {self.mode}; report: {report['report_status']}; task: {status}\n\n"
            +f"Observed: {len(rows)}; executed: {report['steps_executed']}; reused: {report['steps_reused']}; candidates: {len(candidates)}\n\n"
            +f"Actual cost: UNKNOWN; confirmed money savings: UNKNOWN; rollback events: {len(self.rollbacks)}\n\n"
            +f"Policy: {report['policy_version']} ({self.policy_hash})\n\n"
            +'\n'.join('- '+item for item in report['limitations'])+'\n')
        markdown=self.directory/'lean-report.md'
        try:
            if markdown.is_symlink(): raise ValueError('derived report target must not be a symlink')
            markdown.write_text(text, encoding='utf-8')
        finally:
            report['optimization_overhead_ms']=(time.perf_counter()-wall+self.analysis_seconds)*1000
            report['optimization_cpu_ms']=(time.process_time()-cpu+self.cpu_seconds)*1000
            report['limitations'].append('Overhead includes Markdown writing; final JSON persistence is excluded.')
            try:
                if self.applied and self.policy and report['optimization_overhead_ms']>self.policy.get('review_budget_ms',100):
                    from cgkn.telemetry.lean_policy import rollback
                    rollback(self,'OPTIMIZER_OVERHEAD_BUDGET_EXCEEDED')
            finally: write(self.directory/'lean-report.json', report)
        return report

    def relocate(self, directory):
        """Adopt the actual Run's existing frozen snapshot for final reporting."""
        frozen=LeanRun(directory,self.profile,inherited=self)
        self.directory=frozen.directory;self.mode=frozen.mode
        self.policy=frozen.policy;self.policy_hash=frozen.policy_hash
        self.disabled=self.disabled or frozen.disabled
        self.rollbacks.extend(frozen.rollbacks)
        self.analysis_seconds+=frozen.analysis_seconds;self.cpu_seconds+=frozen.cpu_seconds


@contextmanager
def analysis_cost():
    """Measure optional analysis only; its failure must restore full execution."""
    scope=ACTIVE.get();wall=time.perf_counter();cpu=time.process_time()
    try: yield
    except Exception as exc:
        logging.getLogger(__name__).error('LEAN_OPTIONAL_ANALYSIS_FAILED: %s',type(exc).__name__)
        if scope:
            scope.disabled=True
            event={'reason':'OPTIONAL_ANALYSIS_'+type(exc).__name__,'target':'FULL_EXECUTION',
                'policy_hash':scope.policy_hash,'irreversible_effects_undone':False,'policy_revoked':False}
            scope.rollbacks.append(event)
            try:
                from cgkn.telemetry.lean_policy import _revoke
                if scope.policy_path: event['policy_revoked']=_revoke(scope.policy_path,scope.policy_hash,event['reason'])
            except Exception:
                logging.getLogger(__name__).error('LEAN_POLICY_REVOCATION_UNAVAILABLE; current run uses full execution')
    finally:
        if scope:
            scope.analysis_seconds+=time.perf_counter()-wall
            scope.cpu_seconds+=time.process_time()-cpu


def observed(profile, locate, *, session=None, expose=False, receipt=None):
    """Finalization adapter only: executes the original callable exactly once."""
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        def wrapper(*args, **kwargs):
            bound = signature.bind(*args, **kwargs); bound.apply_defaults(); values = bound.arguments
            scope = None; token = None; status = 'UNKNOWN'; incomplete = True
            result = None; parent = ACTIVE.get()
            try:
                directory = Path(locate(values)).resolve()
                if not (parent and parent.directory == directory):
                    if (directory/'lean-policy-snapshot.json').exists() and not (directory/'lean-report.json').exists():
                        recovered = LeanRun(directory, profile(values) if callable(profile) else profile).finish('INTERRUPTED', incomplete=True)
                        write(directory/'lean-report.recovered.json', recovered)
                    scope = LeanRun(directory, profile(values) if callable(profile) else profile,
                        inherited=parent,fresh=profile=='formal_project')
                    token = ACTIVE.set(scope)
            except Exception as exc:
                logging.getLogger(__name__).error('LEAN_REPORT_SETUP_FAILED: %s',type(exc).__name__)
            try:
                result = function(*args, **kwargs)
            except BaseException as exc:
                status = type(exc).__name__
                raise
            else:
                incomplete = False
                try:
                    status = str(result.get('status', result.get('runManifest',{}).get('status','UNKNOWN')) if isinstance(result, dict) else getattr(result, 'status', 'UNKNOWN'))
                    if scope and isinstance(result,dict) and profile=='formal_project':
                        if result.get('run_id'): scope.run_id=str(result['run_id'])
                        if result.get('run_dir'): scope.relocate(result['run_dir'])
                except Exception as exc:
                    logging.getLogger(__name__).error('LEAN_REPORT_METADATA_FAILED: %s',type(exc).__name__)
                return result
            finally:
                if scope:
                    try:
                        if receipt:
                            final=receipt(values)
                            if final.get('provider_run_dir'): scope.relocate(final['provider_run_dir'])
                            if final.get('run_id'): scope.run_id=str(final['run_id'])
                            if not incomplete: status=str(final.get('status',status))
                        report=scope.finish(status, incomplete=incomplete, session_path=session(values) if session else None)
                        if parent and parent.directory != scope.directory:
                            parent.steps.extend(report['steps'])
                            parent.applied.extend(report['qualified_cuts_applied'])
                            parent.rollbacks.extend(report['rollback_events'])
                            parent.analysis_seconds+=report['optimization_overhead_ms']/1000
                            parent.cpu_seconds+=report['optimization_cpu_ms']/1000
                        if expose and isinstance(result,dict):
                            result['lean_report']={'json':str(scope.directory/'lean-report.json'),'markdown':str(scope.directory/'lean-report.md')}
                    except Exception as exc:
                        logging.getLogger(__name__).error('LEAN_REPORT_WRITE_FAILED: %s',type(exc).__name__)
                    finally:
                        if token is not None: ACTIVE.reset(token)
        return wrapper
    return decorate
