import json
from pathlib import Path
from urllib import request
import pytest
from cgkn.providers import ModelRoleConfig
from experiments.product_dev_113.budget_policy import BoundedClient

@pytest.fixture(autouse=True)
def restore_budget_environment(monkeypatch):
    import os
    for key in ('CGKN_PROVIDER_BUDGET_LEDGER','CGKN_PROVIDER_MAX_API_CALLS','CGKN_PROVIDER_MAX_INPUT_TOKENS',
                'CGKN_PROVIDER_MAX_OUTPUT_TOKENS','CGKN_PROVIDER_MAX_ESTIMATED_COST',
                'CGKN_PROVIDER_INPUT_COST_PER_MILLION','CGKN_PROVIDER_OUTPUT_COST_PER_MILLION'):
        monkeypatch.setenv(key,os.environ.get(key,''))

@pytest.mark.parametrize('alias',['qwen','deepseek','grok'])
def test_adapters_usage_tool_feedback_and_unknown_reservation(tmp_path,monkeypatch,alias):
    auth=tmp_path/'authorization.json'
    auth.write_text(json.dumps(dict(stage='ITER-113-ACV-MULTI-API',approved=True,user_authorization_reference='HARNESS_CONFORMANCE_ONLY',cumulative_cap_cny=100,route_cap_cny=100)))
    sent=[]
    class Response:
        headers={}
        def read(self,*args):return json.dumps({'id':'stub','model':alias+'-actual','choices':[{'message':{'content':'{"done":true}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':30,'completion_tokens':20,'total_tokens':50,'completion_tokens_details':{'reasoning_tokens':5}}}).encode()
        def close(self):pass
    def send(req,*a,**kw):sent.append(json.loads(req.data));return Response()
    monkeypatch.setattr(request,'urlopen',send)
    c=BoundedClient('D:/cgkn-provider-api-lab',tmp_path/'ledger.json',tmp_path/'logs','offline',run_cap_cny=100,honor_reasoning_none=True,authorization=auth)
    c.unavailable=set()
    # Avoid using real credentials even though no network transport is reachable.
    monkeypatch.setattr(type(c.service.secret_manager),'resolve',lambda self,p:'synthetic-only')
    args=dict(system='Return JSON',user='Raw previous tool result: exit=0 stdout=SAVED',schema_name='s',schema={'type':'object'},config=ModelRoleConfig('worker',alias,max_output_tokens=1024))
    result=c.complete(**args)
    assert result.model==alias+'-actual' and c.tokens==50
    assert 'SAVED' in sent[0]['messages'][-1]['content']
    assert sent[0].get('max_completion_tokens',sent[0].get('max_tokens'))==128 or sent[0].get('max_completion_tokens',sent[0].get('max_tokens'))>=1024
    assert 'tools' not in sent[0]
    # Unknown request outcome retains its upper bound before propagating error.
    def fail(*a,**kw):raise OSError('synthetic offline failure')
    monkeypatch.setattr(request,'urlopen',fail)
    prior=c.tokens
    with pytest.raises(RuntimeError):c.complete(**args)
    assert c.tokens>prior and c.calls==3
    ledger=json.loads((tmp_path/'ledger.json').read_text())
    assert len(ledger['calls'])==3
