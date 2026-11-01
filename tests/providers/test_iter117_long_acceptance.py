import hashlib,json
from pathlib import Path
import pytest
from tests.providers.test_streaming_runtime import runtime
from tests.providers.test_iter117_bounded_acceptance import bounded
from experiments.api_acceptance.archive_20261029 import streaming_live_acceptance as acceptance

@pytest.fixture
def long_case(bounded,monkeypatch):
    monkeypatch.setattr(acceptance,'LONG_RUN',bounded)
    raw=Path('artifacts/streaming-long-request-plan-20261029/plan.json').read_bytes()
    (bounded/'plan.json').write_bytes(raw)
    (bounded/'authorization.json').write_text(json.dumps(dict(authorized=True,max_posts=1,max_cny=.75,plan_sha256=hashlib.sha256(raw).hexdigest())))
    return bounded

def test_long_single_call_contract_and_no_replay(runtime,long_case):
    from tests.test_general_requirement_compiler import proposal
    runtime['produce']=lambda payload:json.dumps(proposal('Plan an offline data import application'))
    result=acceptance.run_case('LIVE-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert result['status']=='PASS',result
    assert len(runtime['posts'])==1 and runtime['posts'][0]['max_tokens']==7000
    ledger=json.loads((long_case/'budget.json').read_text())
    assert len(ledger['calls'])==1
    with pytest.raises(ValueError,match='ALREADY_ATTEMPTED'):
        acceptance.run_case('LIVE-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==1

def test_long_unknown_never_resends(runtime,long_case):
    runtime['mode']='eof'
    assert acceptance.run_case('LIVE-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')['status']=='UNKNOWN'
    with pytest.raises(ValueError):acceptance.run_case('LIVE-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert len(runtime['posts'])==1

def test_old_authorization_cannot_authorize_new_call(runtime,long_case):
    p=long_case/'authorization.json';auth=json.loads(p.read_text());auth.update(max_posts=3,max_cny=2);p.write_text(json.dumps(auth))
    with pytest.raises(ValueError,match='AUTHORIZATION'):acceptance.run_case('LIVE-LONG-01','RUN_AUTHORIZED_STREAMING_CASE')
    assert runtime['posts']==[]

def test_long_frozen_payload_and_cost_caps():
    plan=json.loads(Path('artifacts/streaming-long-request-plan-20261029/plan.json').read_text())
    case=acceptance.prepare_long(plan)[0]
    assert case['upper_input_tokens']==7631 and case['upper_cost_cny']<.75
    plan['wire_payload']['messages'][1]['content']+=' changed'
    with pytest.raises(ValueError,match='PAYLOAD'):acceptance.prepare_long(plan)
