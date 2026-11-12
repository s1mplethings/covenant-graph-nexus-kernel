from tests.providers.offline_acceptance_plans import offline_plan
import dataclasses,hashlib,json,os
from pathlib import Path
import pytest
from tests.providers.test_streaming_runtime import runtime
from experiments.api_acceptance.archive_20261029 import streaming_live_acceptance as acceptance


@pytest.fixture
def bounded(runtime,monkeypatch):
    run=runtime['tmp']/'acceptance';run.mkdir();monkeypatch.setattr(acceptance,'RUN',run)
    raw=offline_plan('bounded')
    (run/'plan.json').write_bytes(raw)
    (run/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=3,max_cny=2,plan_sha256=hashlib.sha256(raw).hexdigest())))
    from cgkn.providers import canonical_gateway_adapter as adapter
    monkeypatch.setattr(adapter,'completion_client_from_environment',lambda:runtime['client'])
    from cgkn_provider_lab.storage import ProviderConfigStore
    providers=ProviderConfigStore().load()
    monkeypatch.setattr(ProviderConfigStore,'load',lambda self:[dataclasses.replace(p,model='qwen3.8-max' if p.provider_id=='qwen' else 'deepseek-flash') for p in providers])
    # Restore the worker's scoped environment after each isolated test.
    original=dict(os.environ)
    yield run
    os.environ.clear();os.environ.update(original)


def test_three_cases_exact_posts_and_progress(runtime,bounded):
    from tests.test_general_requirement_compiler import proposal
    def produce(payload):
        text=json.dumps(payload)
        if 'CGKN_QWEN_STREAM_OK' in text:return 'CGKN_QWEN_STREAM_OK'
        if 'CGKN_DEEPSEEK_STREAM_OK' in text:return 'CGKN_DEEPSEEK_STREAM_OK'
        return json.dumps(proposal('Plan an offline task tracker'))
    runtime['produce']=produce
    for case in ('LIVE-01','LIVE-02','LIVE-03'):
        result=acceptance.run_case(case,'RUN_AUTHORIZED_STREAMING_CASE')
        assert result['status']=='PASS',result
        assert result['meaningful_progress_at']<result['completed_at']
    assert len(runtime['posts'])==3
    assert len(json.loads((bounded/'budget.json').read_text())['calls'])==3
    with pytest.raises(ValueError,match='ALREADY_ATTEMPTED'):acceptance.run_case('LIVE-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==3


def test_unknown_stops_all_later_cases(runtime,bounded):
    runtime['mode']='eof'
    assert acceptance.run_case('LIVE-01','RUN_AUTHORIZED_STREAMING_CASE')['status']=='UNKNOWN'
    for case in ('LIVE-01','LIVE-02','LIVE-03'):
        with pytest.raises(ValueError):acceptance.run_case(case,'RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==1


def test_no_authorization_no_post(runtime,bounded):
    (bounded/'authorization.json').write_text('{}')
    with pytest.raises(ValueError,match='AUTHORIZATION'):acceptance.run_case('LIVE-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert runtime['posts']==[]


def test_cost_and_contract_caps():
    plan=json.loads(offline_plan('bounded').decode())
    cases=acceptance.prepare(plan)
    assert sum(c['upper_cost_cny'] for c in cases)<.8
    plan['tests'][0]['prompt']='x'*2048
    with pytest.raises(ValueError,match='INPUT_TOO_LARGE'):acceptance.prepare(plan)
    plan['total_budget_cny']=3
    with pytest.raises(ValueError,match='LIMIT_MISMATCH'):acceptance.prepare(plan)
