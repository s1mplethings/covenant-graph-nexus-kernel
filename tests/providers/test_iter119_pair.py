import dataclasses
import hashlib
import json
from pathlib import Path
import pytest
from experiments.api_acceptance import iter119_pair as pair
from tests.providers.test_streaming_runtime import runtime


def plan():
    return pair.read(pair.ROOT/'artifacts/api-progress-clock-20261029/live-authorized-01/plan.json')


def test_preflight_shared_budget_and_no_oversized_request():
    value=plan();result=pair.preflight(value)
    assert result['combined_upper_cost_cny']==pytest.approx(.1024)
    assert result['shared_cap_cny']==.5
    value['requests'][0]['user']='X'*9000
    with pytest.raises(ValueError,match='INPUT_TOO_LARGE'):pair.preflight(value)
    value=plan();value['max_cny']=1
    with pytest.raises(ValueError,match='AUTHORIZATION_BOUNDS'):pair.preflight(value)
    value=plan();value['requests'].append(value['requests'][0])
    with pytest.raises(ValueError,match='MODELS_OR_COUNT'):pair.preflight(value)


def test_no_authorization_no_generation(tmp_path,monkeypatch):
    monkeypatch.setattr(pair,'RUN',tmp_path)
    (tmp_path/'plan.json').write_text(json.dumps(plan()))
    (tmp_path/'authorization.json').write_text('{}')
    with pytest.raises(ValueError,match='AUTHORIZATION_REQUIRED'):pair.validate_authorization()
    assert not (tmp_path/'attempt-claimed.json').exists()


def test_exact_pair_through_tls_dag_and_full_input_reservation(runtime,monkeypatch):
    from tests.test_general_requirement_compiler import proposal
    value=plan();monkeypatch.setattr(pair,'RUN',runtime['tmp'])
    runtime['produce']=lambda payload:json.dumps(proposal('Create a local calculator that adds two numbers and displays the sum.',core=['add_numbers'])) if payload['model']=='qwen3.8-flash' else '{"status":"ok","result":42,"check":"19+23=42"}'
    for row in value['requests']:runtime['gateway'].available_models[row['provider']].add(row['model'])
    client=dataclasses.replace(runtime['client'],input_token_ceiling=8192,api_method='chat_completions')
    result=pair.execute_pair(value,client,'offline-iter119')
    assert result.status=='SUCCEEDED'
    assert len(runtime['posts'])==2
    for payload in runtime['posts']:
        row=next(r for r in value['requests'] if r['model']==payload['model'])
        wire=pair.wire(row)
        assert json.loads(wire)==payload
        assert wire==json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    calls=pair.read(runtime['tmp']/'budget.json')['calls']
    assert len(calls)==2 and all(c['reserved_input_tokens']==8192 for c in calls)
    assert all(c['status']=='SUCCEEDED' for c in calls)


def test_mcp_permanent_claim_prevents_second_worker(tmp_path,monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(pair,'RUN',tmp_path)
    monkeypatch.setattr(pair,'validate_authorization',lambda:(plan(),{}))
    launched=[]
    server=SimpleNamespace(_loaded=lambda p:(None,None,None,tmp_path),core=SimpleNamespace(
        start_generation_job=lambda *a,**kw:launched.append(1) or {'started':True}))
    (tmp_path/'plan.json').write_text(json.dumps(plan()))
    assert pair.start(server,tmp_path/'project')['started']
    with pytest.raises(FileExistsError):pair.start(server,tmp_path/'project')
    assert launched==[1]


def test_reservation_job_attempt_identity_reaches_clock(runtime,monkeypatch):
    from cgkn.providers import ModelRoleConfig
    from cgkn.providers.progress_clock import read_progress
    monkeypatch.setenv('CGKN_MODEL_JOB_ID','original-job')
    monkeypatch.setenv('CGKN_MODEL_ATTEMPT_ID','original-attempt')
    monkeypatch.setenv('CGKN_PROGRESS_ROOT',str(runtime['tmp']/'progress'))
    runtime['client'].complete(system='offline',user='identity check',schema_name='fixture',schema={'type':'object'},
        config=ModelRoleConfig('agent','qwen',max_output_tokens=100,model_id='qwen-fixture'),call_identity='different-call-key')
    ledger=pair.read(runtime['tmp']/'budget.json')['calls'][0]
    clocks=read_progress(runtime['tmp']/'progress','original-job',attempt_id='original-attempt')['calls']
    assert len(clocks)==1
    for key in ('call_id','request_identity','job_id','attempt_id'):assert clocks[0][key]==ledger[key]
    assert any(e.get('client_job_id')=='original-job' for e in runtime['events'])
