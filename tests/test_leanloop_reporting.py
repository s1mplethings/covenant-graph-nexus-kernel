from pathlib import Path

import pytest

from cgkn.telemetry import lean, lean_policy
from tests.leanloop_support import run_csv, cases
from cgkn.application.verification import OracleExecutor, OracleStatus


@pytest.mark.parametrize('failure', [None, 'markdown', 'revocation'])
def test_one_final_json_survives_optional_reporting_failures(tmp_path, monkeypatch, failure):
    writes=[];original=lean.write;markdown_write=Path.write_text
    def record(path, value):
        if Path(path).name=='lean-report.json':writes.append(path)
        return original(path,value)
    def write_text(path, *args, **kwargs):
        if failure=='markdown' and path.name=='lean-report.md':raise PermissionError('fixture')
        return markdown_write(path,*args,**kwargs)
    monkeypatch.setattr(lean,'write',record);monkeypatch.setattr(Path,'write_text',write_text)
    if failure=='revocation':
        monkeypatch.setattr(lean_policy,'_revoke',lambda *a: (_ for _ in ()).throw(PermissionError('fixture')))
    @lean.observed('test',lambda a:tmp_path)
    def task():
        (tmp_path/'effect.txt').write_text('done')
        if failure=='revocation':
            scope=lean.ACTIVE.get();scope.applied.append({'step_id':'fixture'})
            scope.policy={'review_budget_ms':0};scope.policy_path=tmp_path/'policy.json'
        return {'status':'UNKNOWN'}
    assert task()=={'status':'UNKNOWN'}
    assert len(writes)==1 and (tmp_path/'effect.txt').read_text()=='done'
    report=lean.read(tmp_path/'lean-report.json')
    assert report['observed_task_status']=='UNKNOWN'
    assert report['optimization_overhead_ms']>=0
    if failure=='revocation':assert report['rollback_events']


def test_observation_hashes_source_once_per_node_with_real_oracle(tmp_path, monkeypatch):
    calls=[];original=lean.source_identity
    def identity(function):calls.append(function);return original(function)
    monkeypatch.setattr(lean,'source_identity',identity)
    monkeypatch.setattr(lean_policy,'source_identity',identity)
    monkeypatch.setenv('CGKN_LEAN_MODE','OBSERVE');monkeypatch.delenv('CGKN_LEAN_POLICY',raising=False)
    runner,_=run_csv(tmp_path)
    assert len(calls)==len(runner.component_executions)==2
    assert OracleExecutor().execute(cases()[0]['oracles'][0],tmp_path).status is OracleStatus.PASS


def test_artifact_identity_existing_call_signature_is_preserved(monkeypatch):
    monkeypatch.setattr(lean_policy,'source_identity',lambda f:'sha256:fixture')
    assert lean_policy.artifact_identity({}, {}, {}, None, 'p')==lean_policy.artifact_identity(
        {}, {}, {}, None, 'p',implementation_hash='sha256:fixture')
