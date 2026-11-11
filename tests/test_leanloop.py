from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
import time

import pytest

from cgkn.telemetry.lean import LeanRun, observed, read, step, discover, content_hash, source_identity
from cgkn.telemetry.lean_policy import approve, evaluate, transition, aggregate
from tests.leanloop_support import run_csv, cases, normalize_python, FLOW, COMPONENT


def run_case(variant, case, workspace):
    run_csv(workspace,fault=case['input']['fault'])


@pytest.fixture
def qualified(tmp_path, monkeypatch):
    monkeypatch.setenv('CGKN_LEAN_MODE','OBSERVE');monkeypatch.delenv('CGKN_LEAN_POLICY',raising=False)
    initial=tmp_path/'observed';initial.mkdir()
    runner,_=run_csv(initial)
    report=read(initial/'run/lean-report.json')
    assert report['steps_executed']==2
    assert report['candidate_cuts']==[]
    assert report['discovery_status']=='NOT_RUN_OFFLINE_ONLY'
    candidate=discover(report['steps'])[0]
    assert candidate['kind']=='DUPLICATE_DETERMINISTIC'
    receipt=evaluate(candidate,cases(),run_case,tmp_path/'ablation')
    assert receipt['status']=='PASS',receipt
    policy_path=tmp_path/'policy.json'
    policy=approve(receipt,policy_path,version='lean-csv-v1',task_profile=FLOW,
        component_ref=COMPONENT,implementation_hash=source_identity(normalize_python))
    assert policy['review_budget_ms']==100
    # Isolate semantic/Oracle faults from noisy filesystem timing. The separate
    # overhead test exercises revocation; the production default is unchanged.
    policy['review_budget_ms']=1000
    policy_path.write_text(json.dumps(policy),encoding='utf-8')
    return candidate,receipt,policy_path,policy


@pytest.mark.boundary
@pytest.mark.happy_path
def test_discovery_ablation_real_runtime_reuse_and_independent_oracle(tmp_path,monkeypatch,qualified):
    candidate,receipt,path,policy=qualified
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    project=tmp_path/'optimized';project.mkdir()
    runner,result=run_csv(project)
    report=read(project/'run/lean-report.json')
    assert report['steps_executed']==1 and report['steps_reused']==1
    assert report['actual_cost_cny'] is None and report['confirmed_savings_cny'] is None
    assert report['extra_model_calls']==0 and len(report['qualified_cuts_applied'])==1
    refs=result['outputs'];assert refs['left'].artifact_instance_id != refs['right'].artifact_instance_id
    assert runner.store.resolve_artifact_ref(refs['left']).producer.node_id != runner.store.resolve_artifact_ref(refs['right']).producer.node_id
    from cgkn.application.verification import OracleExecutor,OracleStatus
    assert OracleExecutor().execute(cases()[0]['oracles'][0],project).status is OracleStatus.PASS
    assert len(receipt['trials'])==8 and all(t['valid_evaluation'] for t in receipt['trials'])
    assert all(t['oracle_pass']==t['expected_pass'] for t in receipt['trials'])
    assert aggregate([project/'run/lean-report.json'])


@pytest.mark.parametrize('fault',['source','profile','age','evidence','contract','environment'])
def test_invalid_policy_restores_full_execution(tmp_path,monkeypatch,qualified,fault):
    _,_,path,policy=qualified
    if fault=='source': policy['implementation_hash']='changed'
    if fault=='profile': policy['task_profile']='different-task'
    if fault=='age': policy['expires_at']=0
    if fault=='evidence': policy['evidence_hash']='forged'
    if fault=='contract': policy['component_contract_hash']='changed'
    if fault=='environment': policy['environment_hash']='changed'
    path.write_text(json.dumps(policy),encoding='utf-8')
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    workspace=tmp_path/'next';workspace.mkdir();run_csv(workspace)
    report=read(workspace/'run/lean-report.json')
    assert report['steps_executed']==2 and report['steps_reused']==0
    assert report['rollback_events'] and read(path)['state']=='ROLLBACK'


def test_unqualified_and_disabled_run_do_not_reuse(tmp_path,monkeypatch):
    for mode in ('OFF','OBSERVE','AUTO_QUALIFIED'):
        monkeypatch.setenv('CGKN_LEAN_MODE',mode);monkeypatch.delenv('CGKN_LEAN_POLICY',raising=False)
        workspace=tmp_path/mode;workspace.mkdir();runner,_=run_csv(workspace)
        assert [r.cache_status for r in runner.component_executions]==['miss','miss']
        report=read(workspace/'run/lean-report.json')
        assert report['steps_reused']==0
        assert report['steps_observed']==(0 if mode=='OFF' else 2)


@pytest.mark.boundary
@pytest.mark.negative
def test_old_environment_receipt_cannot_be_promoted_or_rebound(tmp_path,monkeypatch,qualified):
    _,receipt,path,policy=qualified
    changed='sha256:'+'0'*64
    monkeypatch.setattr('cgkn.telemetry.lean_policy.environment_identity',lambda:changed)
    with pytest.raises(ValueError,match='qualification environment mismatch'):
        approve(receipt,tmp_path/'invalid-policy.json',version='new',task_profile=FLOW,
            component_ref=COMPONENT,implementation_hash=source_identity(normalize_python))
    assert not (tmp_path/'invalid-policy.json').exists()
    # Editing a configuration hash cannot transfer its old independent evidence.
    policy['environment_hash']=changed
    path.write_text(json.dumps(policy),encoding='utf-8')
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    workspace=tmp_path/'next';workspace.mkdir();run_csv(workspace)
    report=read(workspace/'run/lean-report.json')
    assert report['steps_executed']==2 and not report['qualified_cuts_applied']
    assert read(path)['state']=='ROLLBACK'
    from cgkn.application.verification import OracleExecutor,OracleStatus
    assert OracleExecutor().execute(cases()[0]['oracles'][0],workspace).status is OracleStatus.PASS


@pytest.mark.parametrize('status',['SUCCEEDED','FAILED','BUDGET_EXHAUSTED','UNKNOWN','TIMED_OUT','WORKER_FAILED','RECOVERY_FAILED'])
def test_every_controlled_terminal_report_preserves_business_status(tmp_path,status):
    @observed('test',lambda a:tmp_path)
    def run():return {'status':status}
    assert run()=={'status':status}
    report=read(tmp_path/'lean-report.json')
    assert report['report_status']=='COMPLETE' and report['observed_task_status']==status
    assert (tmp_path/'lean-report.md').is_file() and report['candidates_found']==0


@pytest.mark.parametrize('exc',[asyncio.CancelledError,TimeoutError,RuntimeError])
def test_exception_and_cancellation_emit_incomplete_without_swallowing(tmp_path,exc):
    @observed('test',lambda a:tmp_path)
    def run():raise exc('fixture')
    with pytest.raises(exc):run()
    assert read(tmp_path/'lean-report.json')['report_status']=='INCOMPLETE'


def test_crash_report_is_compensated_on_next_entry(tmp_path):
    LeanRun(tmp_path,'test') # durable policy definition exists, terminal report absent
    @observed('test',lambda a:tmp_path)
    def resumed():return {'status':'FAILED'}
    resumed()
    assert read(tmp_path/'lean-report.recovered.json')['report_status']=='INCOMPLETE'
    assert read(tmp_path/'lean-report.json')['observed_task_status']=='FAILED'


def test_report_failure_is_visible_but_does_not_change_result(tmp_path,monkeypatch,caplog):
    monkeypatch.setattr(LeanRun,'finish',lambda *a,**k: (_ for _ in ()).throw(OSError('fixture')))
    @observed('test',lambda a:tmp_path)
    def run():return {'status':'SUCCEEDED'}
    assert run()=={'status':'SUCCEEDED'}
    assert 'LEAN_REPORT_WRITE_FAILED' in caplog.text


def test_policy_is_frozen_during_run_and_emergency_off_works(tmp_path,monkeypatch):
    policy=tmp_path/'policy.json';policy.write_text(json.dumps({'version':'old'}))
    monkeypatch.setenv('CGKN_LEAN_POLICY',str(policy))
    scope=LeanRun(tmp_path/'run','task')
    policy.write_text(json.dumps({'version':'new'}))
    assert scope.policy['version']=='old'
    assert LeanRun(tmp_path/'run','task').policy['version']=='old'
    monkeypatch.setenv('CGKN_LEAN_MODE','OFF')
    assert LeanRun(tmp_path/'run','task').mode=='OFF'


@pytest.mark.parametrize('protection',['budget','unknown','permission','approval','oracle','delivery','evidence','cancel','recovery','required'])
def test_required_checks_cannot_be_qualified(tmp_path,protection):
    rows=[step('r',n,n,'verification','PASS',semantic_identity='same',protections=[protection],pure_inputs=True) for n in ('a','b')]
    candidate=discover(rows)[0]
    assert candidate['state']=='REJECTED'
    assert evaluate(candidate,cases(),lambda *a:pytest.fail('protected experiment must not run'),tmp_path)['status']=='BLOCKED'


def test_no_progress_and_communication_are_only_candidates():
    for kind,wanted in [('agent_turn','REDUNDANT_AGENT_TURN'),('provider','REDUNDANT_MODEL_CALL'),('communication','REDUNDANT_COMMUNICATION'),('recovery','NO_PROGRESS_RETRY')]:
        rows=[step('r',n,n,kind,'OBSERVED',semantic_identity='same') for n in ('a','b')]
        candidate=discover(rows)[0]
        assert candidate['kind']==wanted and candidate['state']=='CANDIDATE' and candidate['risk']=='UNQUALIFIED'


def test_production_observer_never_runs_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr('cgkn.telemetry.lean.discover',
                        lambda *args: pytest.fail('offline analysis in business run'))
    scope = LeanRun(tmp_path, 'production', mode='OBSERVE')
    scope.steps = [step('r', n, n, 'component', 'pass',
                        semantic_identity='same') for n in ('a', 'b')]
    report = scope.finish('SUCCEEDED')
    assert report['steps_observed'] == 2
    assert report['candidate_cuts'] == []
    assert report['discovery_status'] == 'NOT_RUN_OFFLINE_ONLY'


def test_default_observe_cannot_restore_historical_auto(tmp_path, monkeypatch):
    LeanRun(tmp_path, 'task', mode='AUTO_QUALIFIED')
    monkeypatch.delenv('CGKN_LEAN_MODE', raising=False)
    assert LeanRun(tmp_path, 'task').mode == 'OBSERVE'


def test_default_artifact_run_does_not_import_optimizer(tmp_path, monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        assert name != 'cgkn.telemetry.lean_policy', 'optimizer in default production path'
        return original(name, *args, **kwargs)
    monkeypatch.delenv('CGKN_LEAN_MODE', raising=False)
    monkeypatch.delenv('CGKN_LEAN_POLICY', raising=False)
    monkeypatch.setattr(builtins, '__import__', guarded)
    run_csv(tmp_path)


def test_cooldown_avoids_no_progress_experiments(tmp_path,qualified):
    candidate,receipt,_,_=qualified
    again=evaluate(candidate,cases(),run_case,tmp_path/'ablation')
    assert again['reused_evaluation'] and again['receipt_hash']==receipt['receipt_hash']


def test_state_machine_requires_evidence_and_structural_proof():
    assert transition('OBSERVE','CANDIDATE')=='CANDIDATE'
    with pytest.raises(ValueError):transition('CANDIDATE','AUTO_SKIP',qualified=True)
    with pytest.raises(ValueError):transition('CANDIDATE','ABLATION_PASS')
    assert transition('CANDIDATE','ABLATION_PASS',qualified=True)=='ABLATION_PASS'
    with pytest.raises(ValueError):transition('AUTO_SKIP','CLEANUP_READY')
    assert transition('AUTO_SKIP','ROLLBACK')=='ROLLBACK'


def test_independent_failure_revokes_policy_and_next_run_recovers(tmp_path,monkeypatch,qualified):
    from cgkn.application.verification import OracleExecutor,OracleStatus
    _,_,path,_=qualified
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    bad=tmp_path/'regression';bad.mkdir();run_csv(bad)
    (bad/'csv_cleaner/core.py').write_text('def clean(*args): return [], []\n',encoding='utf-8')
    evidence=OracleExecutor().execute(cases()[0]['oracles'][0],bad)
    assert evidence.status is OracleStatus.FAIL
    assert read(path)['state']=='ROLLBACK'
    assert read(bad/'run/lean-report.json')['rollback_events'][-1]['reason']=='INDEPENDENT_ORACLE_REGRESSION'
    fresh=tmp_path/'recovered';fresh.mkdir();runner,_=run_csv(fresh)
    assert all(e.cache_status=='miss' for e in runner.component_executions)
    assert OracleExecutor().execute(cases()[0]['oracles'][0],fresh).status is OracleStatus.PASS


def test_optimizer_cost_budget_suspends_future_cuts(tmp_path,monkeypatch,qualified):
    _,_,path,policy=qualified
    policy['review_budget_ms']=0;path.write_text(json.dumps(policy))
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    workspace=tmp_path/'expensive';workspace.mkdir();run_csv(workspace)
    assert read(path)['state']=='ROLLBACK'
    assert read(workspace/'run/lean-report.json')['rollback_events'][-1]['reason']=='OPTIMIZER_OVERHEAD_BUDGET_EXCEEDED'


@pytest.mark.parametrize('payload',['{bad','{"outputs":[{}]}'])
def test_corrupt_cache_falls_back_without_replaying_unknown(tmp_path,monkeypatch,qualified,payload):
    from cgkn.runtime.runner import ArtifactModuleRunner
    _,_,path,_=qualified
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    original=ArtifactModuleRunner._record_checkpoint
    def corrupt(self,checkpoint,lean_observation=None):
        original(self,checkpoint,lean_observation)
        if checkpoint['status']=='pass':
            self.cache._path(checkpoint['nodeId'],checkpoint['executionFingerprint']).write_text(payload,encoding='utf-8')
    monkeypatch.setattr(ArtifactModuleRunner,'_record_checkpoint',corrupt)
    workspace=tmp_path/'corrupt';workspace.mkdir();runner,_=run_csv(workspace)
    assert all(e.cache_status=='miss' for e in runner.component_executions)
    assert read(path)['state']=='ROLLBACK'


def break_candidate(variant,case,workspace):
    run_case(variant,case,workspace)
    if variant=='candidate':(workspace/'csv_cleaner/core.py').write_text('def clean(*args): return [], []\n',encoding='utf-8')


def test_needed_step_removal_fails_independent_acceptance(tmp_path,qualified):
    candidate,_,_,_=qualified
    receipt=evaluate(candidate,cases(),break_candidate,tmp_path/'needed')
    assert receipt['status']=='FAIL'
    with pytest.raises(ValueError):approve(receipt,tmp_path/'unsafe.json',version='bad',task_profile=FLOW,
        component_ref=COMPONENT,implementation_hash=source_identity(normalize_python))


def test_insufficient_holdout_blocks_experiment(tmp_path,qualified):
    candidate,_,_,_=qualified
    receipt=evaluate(candidate,cases()[:2],run_case,tmp_path/'insufficient')
    assert receipt['status']=='BLOCKED' and 'INSUFFICIENT_EVIDENCE' in receipt['reason']


def test_structural_candidate_does_not_equate_unused_with_dead():
    from cgkn.telemetry.lean_policy import structural_candidates
    rows=structural_candidates([{'duplicate_responsibility':'legacy controller','observed_calls':0,'proofs':[]}])
    assert rows[0]['state']=='CANDIDATE' and not rows[0]['automatic_source_mutation']


def test_corrupt_snapshot_never_enables_current_policy(tmp_path,monkeypatch):
    folder=tmp_path/'run';folder.mkdir();(folder/'lean-policy-snapshot.json').write_text('{bad')
    path=tmp_path/'policy.json';path.write_text(json.dumps({'version':'new','state':'AUTO_SKIP','approved':True}))
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    scope=LeanRun(folder,'task')
    assert scope.disabled and scope.mode=='OBSERVE' and not scope.policy
    assert (folder/'lean-policy-snapshot.json').read_text()=='{bad'


def test_true_process_exit_rebuilds_existing_checkpoint(tmp_path):
    import subprocess,sys
    code='from pathlib import Path; from cgkn.telemetry.lean import LeanRun; from cgkn.runtime.checkpoint import write_checkpoint; import os,sys; p=Path(sys.argv[1]); LeanRun(p,"task"); write_checkpoint(p,{"nodeId":"n","executionId":"original-attempt","status":"running","inputArtifactRefs":[],"outputArtifactRefs":[]}); os._exit(7)'
    completed=subprocess.run([sys.executable,'-c',code,str(tmp_path)],timeout=20,capture_output=True)
    assert completed.returncode==7
    @observed('task',lambda a:tmp_path)
    def resume():return {'status':'FAILED'}
    resume()
    report=read(tmp_path/'lean-report.recovered.json')
    assert report['report_status']=='INCOMPLETE' and report['steps'][0]['attempt_id']=='original-attempt'


def test_phase_projection_does_not_copy_secrets_or_invent_attempts(tmp_path):
    secret='do-not-copy-test-credential'
    (tmp_path/'provider_phase_log.jsonl').write_text(json.dumps({'phase':'provider','status':'UNKNOWN','message':secret})+'\n')
    report=LeanRun(tmp_path,'provider').finish('UNKNOWN')
    assert secret not in json.dumps(report)
    assert report['steps'][0]['attempt_id']=='NOT_AVAILABLE' and report['actual_cost_cny'] is None


def compensated_case(variant,case,workspace):
    run_case(variant,case,workspace)
    if not (workspace/'csv_cleaner/core.py').exists(): return
    original=(workspace/'csv_cleaner/core.py').read_text(encoding='utf-8')
    for name in ('a','b'):(workspace/(name+'.txt')).write_text(original,encoding='utf-8')
    if variant=='candidate':
        for name in case['input']['cuts']:(workspace/(name+'.txt')).unlink()
    remaining=[p for p in (workspace/'a.txt',workspace/'b.txt') if p.exists()]
    (workspace/'csv_cleaner/core.py').write_text(remaining[0].read_text(encoding='utf-8') if remaining else 'def clean(*args): return [], []\n',encoding='utf-8')


def test_bounded_combination_cannot_inherit_individual_passes(tmp_path,qualified):
    candidate,_,_,_=qualified
    verdicts=[]
    for cuts in (['a'],['b'],['a','b']):
        dataset=cases()
        for case in dataset:case['input']['cuts']=cuts
        receipt=evaluate(candidate,dataset,compensated_case,tmp_path/(''.join(cuts)))
        verdicts.append(receipt['status'])
    assert verdicts==['PASS','PASS','FAIL']


def test_review_cannot_revoke_newer_operator_policy(tmp_path):
    from cgkn.telemetry.lean_policy import _revoke
    path=tmp_path/'policy.json'
    old={'version':'old','state':'AUTO_SKIP'};new={'version':'new','state':'AUTO_SKIP'}
    path.write_text(json.dumps(new),encoding='utf-8')
    assert not _revoke(path,content_hash(old),'old run failed')
    assert read(path)==new


@pytest.mark.parametrize('subject',['../outside.py','C:outside.py'])
def test_subject_path_cannot_leave_isolated_workspace(tmp_path,subject):
    dataset=cases()
    dataset[0]['subjects']=[subject]
    candidate={'kind':'DUPLICATE_DETERMINISTIC','pure_inputs':True,
        'implementation_hash':source_identity(normalize_python),'component_contract_hash':'sha256:'+'0'*64,
        'task_profile':FLOW,'component_ref':COMPONENT}
    result=evaluate(candidate,dataset,run_case,tmp_path)
    assert result['status']=='BLOCKED' and not result['trials'] and 'workspace-contained' in result['reason']


@pytest.mark.parametrize('mode',['OFF','OBSERVE','AUTO_QUALIFIED'])
def test_optional_identity_failure_never_becomes_business_failure(tmp_path,monkeypatch,mode):
    from cgkn.telemetry import lean_policy
    from cgkn.application.verification import OracleExecutor,OracleStatus
    calls=[]
    def broken(*args,**kwargs):
        calls.append(True)
        raise OSError('injected optional identity failure')
    monkeypatch.setenv('CGKN_LEAN_MODE',mode)
    monkeypatch.setattr('cgkn.telemetry.lean.artifact_identity',broken)
    runner,_=run_csv(tmp_path)
    assert len(runner.component_executions)==2
    assert all(e.cache_status=='miss' for e in runner.component_executions)
    assert OracleExecutor().execute(cases()[0]['oracles'][0],tmp_path).status is OracleStatus.PASS
    assert bool(calls)==(mode!='OFF')


def test_unwritable_revocation_does_not_fail_original_execution(tmp_path,monkeypatch,qualified):
    from cgkn.telemetry import lean_policy
    from cgkn.application.verification import OracleExecutor,OracleStatus
    _,_,path,_=qualified
    def broken(*args,**kwargs):raise PermissionError('injected optional policy write denial')
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED')
    monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    monkeypatch.setattr('cgkn.telemetry.lean.artifact_identity',broken)
    monkeypatch.setattr(lean_policy,'_revoke',broken)
    for name in ('first','next'):
        workspace=tmp_path/name;workspace.mkdir()
        runner,_=run_csv(workspace)
        assert all(e.cache_status=='miss' for e in runner.component_executions)
        assert OracleExecutor().execute(cases()[0]['oracles'][0],workspace).status is OracleStatus.PASS


@pytest.mark.parametrize('mode',['OFF','OBSERVE','AUTO_QUALIFIED'])
@pytest.mark.parametrize('handled',[False,True])
def test_nested_same_run_unknown_never_executes_original_twice(tmp_path,monkeypatch,mode,handled):
    from cgkn.providers.gateway_client import GatewayCompletionError
    monkeypatch.setenv('CGKN_LEAN_MODE',mode)
    failure=GatewayCompletionError('UNKNOWN','controlled local effect',outcome_unknown=True)
    @observed('inner',lambda a:tmp_path)
    def inner():
        with (tmp_path/'effects.txt').open('a',encoding='utf-8') as stream:stream.write('effect\n')
        raise failure
    @observed('outer',lambda a:tmp_path)
    def outer():
        if not handled:return inner()
        try:inner()
        except GatewayCompletionError:return {'status':'UNKNOWN'}
    if handled:assert outer()['status']=='UNKNOWN'
    else:
        with pytest.raises(GatewayCompletionError) as raised:outer()
        assert raised.value is failure
    assert (tmp_path/'effects.txt').read_text().splitlines()==['effect']
    report=read(tmp_path/'lean-report.json')
    assert report['observed_task_status']==('UNKNOWN' if handled else 'GatewayCompletionError')
    assert report['report_status']==('COMPLETE' if handled else 'INCOMPLETE')


def test_post_result_metadata_failure_preserves_original_result(tmp_path,monkeypatch,caplog):
    original={'status':'PASS','run_dir':str(tmp_path/'actual')}
    def denied(*args):raise PermissionError('derived metadata write denied')
    monkeypatch.setattr(LeanRun,'relocate',denied)
    @observed('formal_project',lambda a:tmp_path/'fallback')
    def run():return original
    assert run() is original
    assert 'LEAN_REPORT_METADATA_FAILED' in caplog.text
    assert read(tmp_path/'fallback/lean-report.json')['observed_task_status']=='PASS'


def test_formal_resume_report_adopts_actual_frozen_run_policy(tmp_path,monkeypatch):
    from cgkn.telemetry.lean import ACTIVE
    old=tmp_path/'old.json';old.write_text(json.dumps({'version':'old'}))
    new=tmp_path/'new.json';new.write_text(json.dumps({'version':'new'}))
    actual=tmp_path/'actual'
    LeanRun(actual,'child',mode='OBSERVE',policy_path=old).finish('PASS')
    monkeypatch.setenv('CGKN_LEAN_MODE','OBSERVE');monkeypatch.setenv('CGKN_LEAN_POLICY',str(new))
    @observed('child',lambda a:actual)
    def child():
        assert ACTIVE.get().policy['version']=='old'
        ACTIVE.get().steps.append(step('actual','node','attempt','component','pass'))
        return {'status':'PASS'}
    @observed('formal_project',lambda a:tmp_path/'fallback')
    def formal():
        child()
        return {'status':'PASS','run_dir':str(actual)}
    assert formal()['status']=='PASS'
    report=read(actual/'lean-report.json')
    assert report['policy_version']=='old' and report['steps'][0]['policy_version']=='old'


def test_nested_distinct_runs_preserve_each_step_policy_version(tmp_path,monkeypatch):
    from cgkn.telemetry.lean import ACTIVE
    old=tmp_path/'old.json';old.write_text(json.dumps({'version':'old'}))
    new=tmp_path/'new.json';new.write_text(json.dumps({'version':'new'}))
    child_dir=tmp_path/'child'
    LeanRun(child_dir,'child',mode='OBSERVE',policy_path=old).finish('PASS')
    monkeypatch.setenv('CGKN_LEAN_MODE','OBSERVE');monkeypatch.setenv('CGKN_LEAN_POLICY',str(new))
    @observed('child',lambda a:child_dir)
    def child():
        ACTIVE.get().steps.append(step('child','child-node','child-attempt','component','pass'))
        return {'status':'PASS'}
    @observed('parent',lambda a:tmp_path/'parent')
    def parent():
        child()
        ACTIVE.get().steps.append(step('parent','parent-node','parent-attempt','component','pass'))
        return {'status':'PASS'}
    parent()
    rows=read(tmp_path/'parent/lean-report.json')['steps']
    assert {r['step_id']:r['policy_version'] for r in rows}=={'child-node':'old','parent-node':'new'}


@pytest.mark.parametrize('source',[None,'UNKNOWN','not-a-source-hash'])
def test_unknown_source_cannot_qualify(tmp_path,source):
    candidate={'kind':'DUPLICATE_DETERMINISTIC','pure_inputs':True,'implementation_hash':source,
        'component_contract_hash':'sha256:'+'0'*64,'task_profile':FLOW,'component_ref':COMPONENT}
    result=evaluate(candidate,cases(),run_case,tmp_path)
    assert result['status']=='BLOCKED' and not result['trials'] and 'known source' in result['reason']


def test_environment_identity_binds_execution_runtime_source(monkeypatch):
    from cgkn.telemetry.lean import environment_identity
    environment_identity.cache_clear();before=environment_identity()
    original=Path.read_bytes
    try:
        with monkeypatch.context() as patcher:
            patcher.setattr(Path,'read_bytes',lambda self:b'changed runtime' if self.as_posix().endswith('/runtime/runner.py') else original(self))
            environment_identity.cache_clear()
            assert environment_identity()!=before
    finally:environment_identity.cache_clear()


def test_canonical_proof_reuse_does_not_require_optional_native_cache(tmp_path,monkeypatch,qualified):
    _,_,path,policy=qualified
    policy['review_budget_ms']=1000;path.write_text(json.dumps(policy),encoding='utf-8')
    monkeypatch.setenv('CGKN_LEAN_MODE','AUTO_QUALIFIED');monkeypatch.setenv('CGKN_LEAN_POLICY',str(path))
    workspace=tmp_path/'resumed';workspace.mkdir()
    runner,_=run_csv(workspace)
    assert [e.cache_status for e in runner.component_executions]==['miss','hit']
    second_node=runner.component_executions[1].node_id
    for entry in (workspace/'run/cache'/second_node).glob('*.json'):entry.unlink()
    from cgkn.runtime import ArtifactModuleRunner
    source = runner.store.latest_produced_by_node('input','source').ref
    resumed = ArtifactModuleRunner(workspace/'specs-root',workspace/'run',FLOW)
    monkeypatch.setattr(resumed,'_run_node',lambda *a:pytest.fail('verified canonical node replayed'))
    resumed.run({'source':source})
    assert [e.cache_status for e in resumed.component_executions]==['hit','hit']
    assert not read(workspace/'run/lean-report.json')['qualified_cuts_applied']


def test_source_identity_binds_loaded_code_and_is_stable_across_processes(monkeypatch):
    import subprocess,sys
    def first():return 'first'
    def second():return 'second'
    before=source_identity(first)
    monkeypatch.setattr(first,'__code__',second.__code__)
    assert source_identity(first)!=before
    result=subprocess.run([sys.executable,'-c',
        'from cgkn.telemetry.lean import source_identity; from tests.leanloop_support import normalize_python; print(source_identity(normalize_python))'],
        capture_output=True,text=True,timeout=20,check=True)
    assert result.stdout.strip()==source_identity(normalize_python)
