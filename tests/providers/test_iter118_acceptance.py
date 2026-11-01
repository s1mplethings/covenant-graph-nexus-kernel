"""ITER-118 admission through actual budget client/Gateway/local TLS only."""
import hashlib,io,json,dataclasses,os
from pathlib import Path
import pytest
from tests.providers.test_streaming_runtime import runtime
from experiments.api_acceptance.archive_20261029 import api_final_acceptance as acceptance

@pytest.fixture
def batch(runtime,monkeypatch):
    run=runtime['tmp']/'acceptance';run.mkdir()
    raw=Path('artifacts/api-final-live-20261029/paid-plan.json').read_bytes();(run/'paid-plan.json').write_bytes(raw)
    (run/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=6,max_cny=3,plan_sha256=hashlib.sha256(raw).hexdigest())))
    # Import before patching the factory so its module-level binding cannot retain a fixture.
    from cgkn.providers import canonical_gateway_adapter
    for key in ('CGKN_MODEL_ATTEMPT_ID','CGKN_MODEL_JOB_ID','CGKN_BENCHMARK_RUN_ID','CGKN_PROVIDER_MAX_PLANNING_CALLS','CGKN_PROVIDER_MAX_GENERATION_CALLS','CGKN_PROVIDER_MAX_REPAIR_CALLS'):
        if key in os.environ:monkeypatch.setenv(key,os.environ[key])
        else:monkeypatch.delenv(key,raising=False)
    monkeypatch.setattr(acceptance,'RUN',run)
    monkeypatch.setattr('cgkn.providers.gateway_client.completion_client_from_environment',lambda:runtime['client'])
    for p,m in [('qwen','qwen3.8-max'),('deepseek','deepseek-flash')]:runtime['gateway'].available_models[p].add(m)
    return run

def test_no_authorization_zero_posts(runtime,batch):
    (batch/'authorization.json').unlink()
    with pytest.raises(ValueError,match='EXPLICIT_AUTHORIZATION'):acceptance.run_case('ITER118-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert not runtime['posts']

def test_unknown_never_replayed_or_advanced(runtime,batch):
    runtime['mode']='eof'
    result=acceptance.run_case('ITER118-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert result['status']=='UNKNOWN' and len(runtime['posts'])==1
    with pytest.raises(ValueError):acceptance.run_case('ITER118-01','RUN_AUTHORIZED_STREAMING_CASE')
    with pytest.raises(ValueError):acceptance.run_case('ITER118-02','RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==1

def test_final_wire_input_limit_rejects_before_provider_post(runtime,batch):
    client=dataclasses.replace(runtime['client'],input_token_ceiling=10)
    from cgkn.providers.client import ModelRoleConfig
    from cgkn.providers.gateway_client import GatewayCompletionError
    with pytest.raises(GatewayCompletionError) as exc:
        client.complete(system='offline',user='bounded',schema_name='x',schema=None,config=ModelRoleConfig('agent','qwen',max_output_tokens=20))
    assert not exc.value.outcome_unknown and not runtime['posts']

def test_six_slots_real_contract_handoff_and_no_seventh_post(runtime,batch):
    from tests.test_general_requirement_compiler import proposal
    from tests.application.software_project.test_gateway_e2e import ProjectGateway
    from cgkn.providers.streaming_sse import sse_events,StreamLimits
    ProjectGateway.models=[];ProjectGateway.agent_calls=0
    def produce(payload):
        n=len(runtime['posts'])
        if n==1:return 'CGKN_QWEN_STREAM_OK'
        if n==2:return 'CGKN_DEEPSEEK_STREAM_OK'
        if n==3:return json.dumps(proposal('offline backup planning',core=['snapshot']))
        provider='deepseek' if payload['model'].startswith('deepseek') else 'qwen'
        schema_name='cgkn_scoped_project_worker' if provider=='deepseek' else 'cgkn_agent_decision'
        fake=object.__new__(ProjectGateway);fake.rfile=io.BytesIO(json.dumps(dict(model=provider,text={'format':{'name':schema_name}})).encode())
        fake.headers={'Content-Length':len(fake.rfile.getvalue())};fake.wfile=io.BytesIO();fake.send_response=lambda *a:None;fake.send_header=lambda *a:None;fake.end_headers=lambda:None
        fake.do_POST();rows=list(sse_events(fake.wfile.getvalue().splitlines(keepends=True),limits=StreamLimits()))
        return json.loads(rows[-1].data)['response']['output_text']
    runtime['produce']=produce
    for name in ('ITER118-01','ITER118-02','ITER118-03','ITER118-04'):
        result=acceptance.run_case(name,'RUN_AUTHORIZED_STREAMING_CASE')
        assert result['status']=='PASS',result
    assert [p['model'] for p in runtime['posts']]==['qwen3.8-max','deepseek-flash','qwen3.8-max','qwen3.8-max','deepseek-flash','qwen3.8-max']
    assert result['receipt']['internal_test_result']=='PASS' and result['receipt']['hidden_acceptance_result']=='PASS'
    before=(batch/'budget.json').read_bytes()
    with pytest.raises(ValueError):acceptance.run_case('ITER118-04','RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==6 and (batch/'budget.json').read_bytes()==before
    rows=json.loads(before)['calls'];assert len(rows)==6 and all(x['status']=='SUCCEEDED' for x in rows)
    assert all(p.get('max_completion_tokens',p.get('max_tokens'))<=r[3] for p,r in zip(runtime['posts'],acceptance.EXPECTED))


def test_dual_long_authorized_caps_and_no_replay(runtime,batch,monkeypatch):
    from tests.test_general_requirement_compiler import proposal
    raw=Path('artifacts/api-live-dual-long-20261029/paid-plan.json').read_bytes()
    (batch/'paid-plan.json').write_bytes(raw)
    (batch/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=2,max_cny=10,plan_sha256=hashlib.sha256(raw).hexdigest())))
    monkeypatch.setattr(acceptance,'DUAL_RUN',batch)
    runtime['produce']=lambda payload:json.dumps(proposal('offline backup planning',core=['snapshot']))
    for case in ('ITER118-LONG-01','ITER118-LONG-02'):
        result=acceptance.run_case(case,'RUN_AUTHORIZED_STREAMING_CASE')
        assert result['status']=='PASS',result
    assert [p['model'] for p in runtime['posts']]==['qwen3.8-max','deepseek-flash']
    with pytest.raises(ValueError):acceptance.run_case('ITER118-LONG-02','RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==2


def test_explicit_unused_deepseek_resume_preserves_unknown(runtime,batch,monkeypatch):
    from tests.test_general_requirement_compiler import proposal
    raw=Path('artifacts/api-live-dual-long-20261029/paid-plan.json').read_bytes();(batch/'paid-plan.json').write_bytes(raw)
    (batch/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=2,max_cny=10,plan_sha256=hashlib.sha256(raw).hexdigest())))
    monkeypatch.setattr(acceptance,'DUAL_RUN',batch)
    runtime['mode']='eof';assert acceptance.run_case('ITER118-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')['status']=='UNKNOWN'
    prior=(batch/'call-01-result.json').read_bytes();ledger_before=json.loads((batch/'budget.json').read_text())['calls'][0]
    with pytest.raises(ValueError):acceptance.run_case('ITER118-LONG-02','RUN_AUTHORIZED_STREAMING_CASE')
    (batch/'resume-unused-deepseek.json').write_text(json.dumps(dict(authorized=True,case_id='ITER118-LONG-02',plan_sha256=hashlib.sha256(raw).hexdigest(),preserved_unknown_sha256=hashlib.sha256(prior).hexdigest())))
    runtime['mode']='ok';runtime['produce']=lambda payload:json.dumps(proposal('offline backup planning',core=['snapshot']))
    assert acceptance.run_case('ITER118-LONG-02','RUN_AUTHORIZED_STREAMING_CASE')['status']=='PASS'
    assert len(runtime['posts'])==2 and runtime['posts'][1]['model']=='deepseek-flash'
    assert (batch/'call-01-result.json').read_bytes()==prior
    assert json.loads((batch/'budget.json').read_text())['calls'][0]==ledger_before
    with pytest.raises(ValueError):acceptance.run_case('ITER118-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')
    with pytest.raises(ValueError):acceptance.run_case('ITER118-LONG-02','RUN_AUTHORIZED_STREAMING_CASE')


def test_efficient_pair_bound_once(runtime,batch,monkeypatch):
    raw=Path('artifacts/api-efficient-stream-20261029/paid-plan.json').read_bytes();(batch/'paid-plan.json').write_bytes(raw)
    (batch/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=2,max_cny=10,plan_sha256=hashlib.sha256(raw).hexdigest())))
    monkeypatch.setattr(acceptance,'EFFICIENT_RUN',batch)
    runtime['produce']=lambda payload:json.dumps({'cases':['case '+str(i) for i in range(12)]})
    for case in ('ITER118-SAVE-01','ITER118-SAVE-02'):
        assert acceptance.run_case(case,'RUN_AUTHORIZED_STREAMING_CASE')['status']=='PASS'
    assert len(runtime['posts'])==2
    for case in ('ITER118-SAVE-01','ITER118-SAVE-02'):
        with pytest.raises(ValueError):acceptance.run_case(case,'RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==2


def test_duration_pair_caps_and_no_replay(runtime,batch,monkeypatch):
    raw=Path('artifacts/api-duration100-20261029/paid-plan.json').read_bytes();(batch/'paid-plan.json').write_bytes(raw)
    (batch/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=2,max_cny=10,plan_sha256=hashlib.sha256(raw).hexdigest())))
    monkeypatch.setattr(acceptance,'DURATION_RUN',batch)
    def produce(payload):
        count=40 if payload['model']=='qwen3.8-max' else 120
        return json.dumps({'cases':[dict(id=i,area='manifest_integrity',scenario='offline fixture',steps=['prepare','execute','assert'],expected='unchanged',recovery_check='read back') for i in range(1,count+1)]})
    runtime['produce']=produce
    for case in ('ITER118-DURATION-01','ITER118-DURATION-02'):
        assert acceptance.run_case(case,'RUN_AUTHORIZED_STREAMING_CASE')['status']=='PASS'
    assert len(runtime['posts'])==2
    assert [p.get('max_completion_tokens',p.get('max_tokens')) for p in runtime['posts']]==[10000,28000]
    with pytest.raises(ValueError):acceptance.run_case('ITER118-DURATION-02','RUN_AUTHORIZED_STREAMING_CASE')


def test_archived_live_plans_refuse_even_existing_authorization():
    with pytest.raises(RuntimeError,match='ARCHIVED_ACCEPTANCE_LIVE_DISABLED'):
        acceptance.run_case('ITER118-DURATION-01','RUN_AUTHORIZED_STREAMING_CASE')
