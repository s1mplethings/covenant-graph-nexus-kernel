from decimal import Decimal
from unittest.mock import patch
import pytest
from cgkn.providers import ModelRoleConfig
from .budget_policy import choose_output,BoundedClient,ledger_cost

def test_promotion_real_reconstruction():
    n=choose_output(input_upper=90669,requested=8192,remaining='2.08656')
    assert n==4553 and Decimal(90669*20+n*60)/1000000<=Decimal('2.08656')

def test_input_alone_cannot_fit_and_no_unusable_output():
    with pytest.raises(RuntimeError):choose_output(input_upper=108337,requested=8192,remaining='1.45368')
    with pytest.raises(RuntimeError):choose_output(input_upper=1000,requested=8192,remaining='.03')

def test_real_config_forwarded_not_only_estimate(tmp_path):
    ledger=tmp_path/'ledger.json';ledger.write_text('{"calls":[]}')
    c=object.__new__(BoundedClient);c.root=tmp_path;c.cap=.3;c.run_cost=0;c.global_cap=.3;c.ledger=ledger
    with patch('experiments.product_eval_076_v8.live_provider.LiveClient.complete',return_value='sent') as transport:
        c.complete(system='s',user='u',schema={},schema_name='test',config=ModelRoleConfig('agent','qwen',max_output_tokens=8192))
        config=transport.call_args.kwargs['config']
        assert 1024<=config.max_output_tokens<8192
        assert (len('su{}'.encode())+4096)*20+config.max_output_tokens*60<=300000

def test_no_stage_authorization_no_live_client():
    with patch('experiments.product_eval_076_v8.live_provider.LiveClient.__init__') as init:
        with pytest.raises(RuntimeError,match='AUTHORIZATION'):BoundedClient()
        init.assert_not_called()

def test_actual_transport_body_and_ledger_share_adapted_limit(tmp_path,monkeypatch):
    import dataclasses,json,sys,time,types
    from urllib import request
    from scripts import provider_api_budget as budget
    @dataclasses.dataclass
    class Provider:
        model:str='qwen3.8-max'
        provider_id:str='qwen'
        timeout_seconds:float=300
    class Options:
        def __init__(self,**kw):self.__dict__.update(kw)
    monkeypatch.setitem(sys.modules,'cgkn_provider_lab.models',types.SimpleNamespace(ComparisonOptions=Options))
    monkeypatch.setitem(sys.modules,'cgkn_provider_lab',types.SimpleNamespace())
    monkeypatch.setitem(sys.modules,'cgkn_provider_lab.adapters',types.SimpleNamespace(request=request))
    ledger=tmp_path/'budget.json'
    for k,v in {'CGKN_PROVIDER_BUDGET_LEDGER':str(ledger),'CGKN_PROVIDER_MAX_ESTIMATED_COST':'.3','CGKN_PROVIDER_MAX_API_CALLS':'80','CGKN_PROVIDER_MAX_INPUT_TOKENS':'1000000','CGKN_PROVIDER_MAX_OUTPUT_TOKENS':'1000000','CGKN_PROVIDER_INPUT_COST_PER_MILLION':'20','CGKN_PROVIDER_OUTPUT_COST_PER_MILLION':'60'}.items():monkeypatch.setenv(k,v)
    c=object.__new__(BoundedClient);c.root=tmp_path;c.cap=.3;c.run_cost=0;c.global_cap=.3;c.ledger=ledger;c.calls=0;c.tokens=0;c.started=time.monotonic();c.run_id='offline-transport';c.providers={'qwen':Provider()};c.honor_reasoning_none=True
    ledger.write_text(json.dumps({'calls':[]}))
    emitted=[]
    class Response:
        headers={}
        def close(self):pass
        def read(self,*args):return json.dumps({'id':'synthetic','model':'qwen3.8-max','usage':{'prompt_tokens':10,'completion_tokens':10}}).encode()
    def fake_urlopen(req,*a,**kw):emitted.append(json.loads(req.data));return Response()
    monkeypatch.setattr(request,'urlopen',fake_urlopen)
    def invoke(provider,user,options):
        req=request.Request('https://offline.invalid',data=json.dumps({'max_tokens':options.max_tokens}).encode())
        with request.urlopen(req) as response:response.read()
        return types.SimpleNamespace(status='ok',text='{}',request_id='synthetic',to_dict=lambda:{'status':'ok','text':'{}'})
    c.service=types.SimpleNamespace(invoke_one=invoke)
    c.complete(system='s',user='u',schema={},schema_name='test',config=ModelRoleConfig('agent','qwen',max_output_tokens=8192))
    calls=json.loads(ledger.read_text())['calls']
    assert len(emitted)==len(calls)==1
    assert 1024<=emitted[0]['max_tokens']<8192
    assert emitted[0]['max_tokens']==calls[0]['reserved_output_tokens']
    assert emitted[0]['enable_thinking'] is False
    assert calls[0]['status']=='SUCCEEDED'
