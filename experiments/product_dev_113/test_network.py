import concurrent.futures
import json
import threading
import time
from urllib.request import Request

import httpx
import pytest

from cgkn.providers import ModelRoleConfig
from cgkn.providers.network_transport import NetworkClients, Route, RouteFailure
from experiments.product_dev_113.network_client import NetworkClient


def make_client(tmp_path, monkeypatch, handlers, cap=2):
    # LiveClient configures its budget environment; restore it between tests.
    import os
    for key in ('CGKN_PROVIDER_BUDGET_LEDGER','CGKN_PROVIDER_MAX_API_CALLS','CGKN_PROVIDER_MAX_INPUT_TOKENS',
                'CGKN_PROVIDER_MAX_OUTPUT_TOKENS','CGKN_PROVIDER_MAX_ESTIMATED_COST',
                'CGKN_PROVIDER_INPUT_COST_PER_MILLION','CGKN_PROVIDER_OUTPUT_COST_PER_MILLION'):
        monkeypatch.setenv(key,os.environ.get(key,''))
    config=tmp_path/'transport.json'
    config.write_text(json.dumps({'version':'test','trust_env':False,'verify_tls':True,
        'provider_bindings':{'deepseek':'one','grok':'two'},
        'transport_profiles':{'one':{'proxy_url':None,'fallback':'two','deadline':5},
                              'two':{'proxy_url':None,'deadline':5}}}))
    auth=tmp_path/'auth.json'
    auth.write_text(json.dumps(dict(stage='ITER-113-ACV-MULTI-API',approved=True,
        user_authorization_reference='OFFLINE_ONLY',cumulative_cap_cny=cap,
        route_cap_cny=cap,max_requests=6,max_tokens=6000000)))
    client=NetworkClient('D:/cgkn-provider-api-lab',tmp_path/'ledger.json',tmp_path/'logs',
        'network-test',run_cap_cny=cap,authorization=auth,transport_config=config,
        honor_reasoning_none=True)
    monkeypatch.setattr(type(client.service.secret_manager),'resolve',lambda self,p:'synthetic-'+p.provider_id)
    client.network.close()
    client.network=NetworkClients({'one':Route('one',None,deadline=5,fallback='two'),
                                  'two':Route('two',None,deadline=5)},
        {'deepseek':'one','grok':'two'},version='offline',
        transports={k:httpx.MockTransport(v) for k,v in handlers.items()},log=client._trace)
    return client


def arguments(alias):
    return dict(system='Return JSON',user='Return {"ok":true}',schema_name='check',
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False},
        config=ModelRoleConfig('agent' if alias=='deepseek' else 'worker',alias,max_output_tokens=128))


def response(req):
    return httpx.Response(200,json={'model':req.url.host,'id':'test',
        'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}})


def test_actual_adapter_concurrency_route_credentials_and_no_environment_fallback(tmp_path,monkeypatch):
    barrier=threading.Barrier(2);seen=[]
    def handler(route):
        def send(req):
            seen.append((route,req.url.host,req.headers['authorization']))
            barrier.wait(timeout=3)
            return response(req)
        return send
    monkeypatch.setenv('HTTPS_PROXY','http://127.0.0.1:1')
    c=make_client(tmp_path,monkeypatch,{'one':handler('one'),'two':handler('two')})
    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            jobs=[pool.submit(c.complete,**arguments(x)) for x in ['deepseek','grok']]
            values=[j.result() for j in jobs]
        assert {v.model for v in values}=={'api.deepseek.com','api.x.ai'}
        assert set(seen)=={('one','api.deepseek.com','Bearer synthetic-deepseek'),('two','api.x.ai','Bearer synthetic-grok')}
        assert c.calls==2
        ledger=json.loads((tmp_path/'ledger.json').read_text())
        assert len(ledger['calls'])==2 and len({x['call_id'] for x in ledger['calls']})==2
    finally:c.close()
    with pytest.raises(ValueError,match='UNKNOWN_PROVIDER_ROUTE'):
        NetworkClients({'one':Route('one',None)},{'deepseek':'missing'},version='bad')


@pytest.mark.parametrize('mode',['connect','read','auth','partial'])
def test_submissions_retries_unknown_fee_and_partial_response(tmp_path,monkeypatch,mode):
    hits=[]
    def first(req):
        hits.append('one')
        if mode=='connect':raise httpx.ConnectError('injected')
        if mode=='read':raise httpx.ReadError('injected-after-send')
        if mode=='auth':return httpx.Response(401,json={'error':'denied'})
        return httpx.Response(200,content=b'{"choices":')
    def second(req):hits.append('two');return response(req)
    c=make_client(tmp_path,monkeypatch,{'one':first,'two':second})
    try:
        if mode == 'connect':
            result=c.complete(**arguments('deepseek'))
            assert result.model=='api.deepseek.com' and result.attempts==2
            assert hits==['one','two']
            rows=json.loads((tmp_path/'ledger.json').read_text())['calls']
            assert not isinstance(rows[0]['input_tokens'],int) # unknown reserve retained
        else:
            with pytest.raises(RuntimeError):c.complete(**arguments('deepseek'))
            assert hits==['one']
    finally:c.close()


def test_shared_fee_admission_rejects_before_submission(tmp_path,monkeypatch):
    entered=threading.Event();release=threading.Event();hits=[]
    def handler(req):hits.append(1);entered.set();release.wait(1);return response(req)
    c=make_client(tmp_path,monkeypatch,{'one':handler,'two':handler},cap=.12)
    try:
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            first=pool.submit(c.complete,**arguments('deepseek'));assert entered.wait(1)
            second=pool.submit(c.complete,**arguments('grok'))
            with pytest.raises(RuntimeError):second.result()
            release.set();first.result()
        assert len(hits)==1
    finally:c.close()


def test_deadline_cancel_and_late_response_never_return_success():
    entered=threading.Event();cancel=threading.Event();events=[]
    def delayed(req):entered.set();time.sleep(.12);return response(req)
    c=NetworkClients({'one':Route('one',None,deadline=.04)},{'deepseek':'one'},version='test',
        transports={'one':httpx.MockTransport(delayed)},log=events.append)
    start=time.monotonic()
    with pytest.raises(RouteFailure):
        c.opener('deepseek',logical_id='old',attempt_id='old-1',cancel=cancel)(Request('https://example.com/',data=b'{}'))
    assert time.monotonic()-start<.1
    c.close();assert any(x.get('expired') for x in events)
    # Cancellation before send consumes no network operation.
    cancel.set()
    with pytest.raises(RouteFailure):
        c.opener('deepseek',logical_id='cancel',attempt_id='c',cancel=cancel)(Request('https://example.com/'))


def test_late_usage_settles_once_without_late_result(tmp_path,monkeypatch):
    from dataclasses import replace
    from scripts import provider_api_budget as budget
    cancelled=threading.Event();entered=threading.Event()
    def delayed(req):entered.set();cancelled.set();time.sleep(.12);return response(req)
    c=make_client(tmp_path,monkeypatch,{'one':delayed,'two':delayed})
    try:
        with pytest.raises(RuntimeError):c.complete(cancel=cancelled,**arguments('deepseek'))
        assert entered.is_set()
        c.close()
        row=json.loads((tmp_path/'ledger.json').read_text())['calls'][0]
        assert row['input_tokens']==10 and row['output_tokens']==10 and c.calls==1
        reservation={'path':str(tmp_path/'ledger.json'),'call_id':row['call_id'],'started_monotonic':time.monotonic()}
        budget.finalize_call(reservation,usage=None,http_status='UNKNOWN',status='FAILED')
        budget.finalize_call(reservation,usage={'prompt_tokens':10,'completion_tokens':10},http_status=200,status='FAILED')
        row2=json.loads((tmp_path/'ledger.json').read_text())['calls'][0]
        assert row2==row
    finally:pass


def test_heartbeat_body_is_not_an_unlimited_deadline():
    class Heartbeats(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(100):time.sleep(.01);yield b' '
    c=NetworkClients({'one':Route('one',None,deadline=.04)},{'deepseek':'one'},version='test',
        transports={'one':httpx.MockTransport(lambda r:httpx.Response(200,stream=Heartbeats()))})
    start=time.monotonic()
    with pytest.raises(RouteFailure):c.opener('deepseek',logical_id='heartbeat',attempt_id='h')(Request('https://example.com/'))
    c.close();assert time.monotonic()-start<.2


def test_network_failure_resume_keeps_completed_tool_receipt(tmp_path,monkeypatch):
    import importlib.util
    spec=importlib.util.spec_from_file_location('existing_graph_fixture','tests/runtime/test_graph_commit.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    executor,runner=fixture.setup(tmp_path/'state');tree=fixture.tree('written')
    fixture.run(runner,tree)
    failed=[True];hits=[]
    def handler(req):
        hits.append(1)
        if failed[0]:raise httpx.ReadError('injected network loss after completed tool')
        return response(req)
    c=make_client(tmp_path,monkeypatch,{'one':handler,'two':handler})
    try:
        with pytest.raises(RuntimeError):c.complete(**arguments('deepseek'))
        assert len(hits)==1
        failed[0]=False;c.complete(**arguments('deepseek'))
        restored=fixture.FeedbackDAGRunner(runner.registry,fixture.FileRunStore(tmp_path/'state'))
        result=fixture.run(restored,tree,resume=True)
        assert executor.calls==[('r','written')] and result.reused_nodes==('written',)
    finally:c.close()
