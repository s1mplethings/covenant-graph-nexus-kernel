"""Offline checks for outer clocks, canonical job state and acceptance dispatch."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/cgkn-agent-kit/src'))
from cgkn_agent_kit import core


def test_domestic_cli_wait_has_no_total_clock(monkeypatch):
    from cgkn.providers import application_network
    monkeypatch.setattr(application_network,'settings',lambda:{'mode':'domestic'})
    calls=[]
    monkeypatch.setattr(core,'_run',lambda *a,**kw:calls.append(kw))
    core.run_generation(['worker'],cgkn_root=ROOT,timeout=90)
    assert calls[0]['timeout'] is None


def test_legacy_cli_limit_is_isolated(monkeypatch):
    from cgkn.providers import application_network
    monkeypatch.setattr(application_network,'settings',lambda:None)
    calls=[]
    monkeypatch.setattr(core,'_run',lambda *a,**kw:calls.append(kw))
    core.run_generation(['worker'],cgkn_root=ROOT,timeout=90)
    assert calls[0]['timeout']==90


def test_no_generation_clock_does_not_remove_tool_limits():
    from scripts import run_local_pipeline_impl as pipeline
    assert pipeline.remaining_timeout(None,180,cap=15)==15
    assert pipeline.remaining_timeout(None,30)==30
    assert pipeline.provider_emission_budget_deadline(None,reserve_completion=True) is None


def load_plugin():
    spec=importlib.util.spec_from_file_location('progress_plugin',ROOT/'plugins/cgkn/scripts/cgkn_mcp_server.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retired_paid_acceptance_is_not_discoverable_or_callable():
    module=load_plugin()
    assert 'cgkn_accept_streaming_case' not in module.TOOL_BY_NAME
    server=module.CGKNPluginServer(ROOT)
    with pytest.raises(module.ToolError):
        server.call_tool('cgkn_accept_streaming_case',{'case_id':'ITER118-DURATION-01','confirmation':'RUN_AUTHORIZED_STREAMING_CASE'})


def test_archived_acceptance_status_never_dispatches():
    module=load_plugin()
    server=object.__new__(module.CGKNPluginServer)
    server.cgkn_root=ROOT
    server.core=SimpleNamespace(generation_job_status=lambda path:{'state':'COMPLETE'})
    assert server.streaming_acceptance_status({'case_id':'ITER118-DURATION-01'})['state']=='COMPLETE'
    with pytest.raises(module.ToolError):server.streaming_acceptance_status({'case_id':'../../private'})


@pytest.mark.parametrize('status',['PASS','UNKNOWN'])
def test_acceptance_wrapper_keeps_original_call_identity(tmp_path,status):
    from experiments.api_acceptance.archive_20261029.streaming_acceptance_worker import main
    state=tmp_path/'generation_job.json'
    core.write_json(state,{'job_id':'wrapper-job','attempt_id':'wrapper-attempt','revision':1})
    calls=[]
    def runner(case,confirmation):
        calls.append((case,confirmation))
        return {'status':status}
    rc=main(['LIVE-LONG-01','RUN_AUTHORIZED_STREAMING_CASE','--result',str(tmp_path/'result.json'),
        '--generation-job-state',str(state),'--generation-job-id','wrapper-job',
        '--generation-attempt-id','wrapper-attempt'],runner=runner)
    assert rc==0 and len(calls)==1
    saved=core.read_json(state)
    assert saved['state']==('COMPLETE' if status=='PASS' else 'FAILED')
    assert saved['terminal_reason']=='ACCEPTANCE_'+status


def test_wrapper_identity_mismatch_prevents_runner(tmp_path):
    from experiments.api_acceptance.archive_20261029.streaming_acceptance_worker import main
    state=tmp_path/'generation_job.json'
    core.write_json(state,{'job_id':'another','attempt_id':'original'})
    with pytest.raises(RuntimeError,match='IDENTITY_CHANGED'):
        main(['LIVE-01','RUN_AUTHORIZED_STREAMING_CASE','--result',str(tmp_path/'result.json'),
            '--generation-job-state',str(state),'--generation-job-id','wrong',
            '--generation-attempt-id','wrong'],runner=lambda *a:pytest.fail('must not call'))
