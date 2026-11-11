"""Independent loopback TLS checks for interruptible pooled reads; no external POST."""
import dataclasses
import json
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request

import httpx
import pytest

from cgkn.providers.network_transport import NetworkClients, Route, RouteFailure
from cgkn.providers.streaming_sse import MeaningfulProgressWatchdog, read_sse_response
from tests.providers.test_streaming_runtime import runtime
from tests.providers.stream_fixtures import upstream_wire


@pytest.fixture
def pooled(runtime):
    state={'mode':'headers','requests':[], 'entered':threading.Event(), 'release':threading.Event(), 'progress':threading.Event()}
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):
            state['requests'].append(('GET',self.client_address[1]))
            self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}');self.wfile.flush()
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append((payload['model'],self.client_address[1]));state['entered'].set()
            wire=upstream_wire(payload['model'],'{\"ok\":true}')
            chunks=[]
            if payload['model']=='qwen' and state['mode']=='stream':
                text='{"ok":true}'
                for fragment in text[:-1]:
                    delta={'id':'fixture-request','model':'qwen','choices':[{'index':0,'delta':{'content':fragment}}]}
                    chunks.append(('data: '+json.dumps(delta)+'\n\n').encode())
                chunks.append(upstream_wire('qwen',text[-1:],'fixture-request'))
                wire=b''.join(chunks)
            if payload['model']=='qwen' and state['mode']=='headers':state['release'].wait(4)
            try:
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(wire)));self.end_headers();self.wfile.flush()
                if payload['model']=='qwen' and state['mode']=='body':state['release'].wait(4)
                if chunks:
                    for chunk in chunks:
                        self.wfile.write(chunk);self.wfile.flush();state['progress'].set();time.sleep(.05)
                else:self.wfile.write(wire);self.wfile.flush()
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(runtime['cert_path'],str(runtime['tmp']/'key.pem'))
    server.socket=tls.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    trust=ssl.create_default_context(cafile=runtime['cert_path'])
    routes={p:Route(p,None,connect=1,read=1,first_response=.25,progress=.2) for p in ('qwen','deepseek')}
    events=[]
    network=NetworkClients(routes,{p:p for p in routes},version='OFFLINE_POOLED',log=events.append,
        transports={p:httpx.HTTPTransport(verify=trust,trust_env=False,retries=0) for p in routes})
    url=f'https://127.0.0.1:{server.server_port}/v1'
    def warm(provider='qwen'):
        with network.opener(provider,logical_id='warm',attempt_id='warm')(Request(url)) as response:assert response.read()==b'{}'
    def run(provider='qwen',cancel=None):
        route=network.routes[provider]
        watchdog=MeaningfulProgressWatchdog(initial_timeout=route.first_response,idle_timeout=route.progress)
        req=Request(url,data=json.dumps({'model':provider}).encode(),headers={'Content-Type':'application/json'})
        return network.opener(provider,logical_id=provider,attempt_id=provider,cancel=cancel,watchdog=watchdog,
            consume=lambda response:read_sse_response(response,on_progress=lambda row:watchdog.progress(row['meaningful_events'])))(req)
    state.update(network=network,warm=warm,run=run,events=events)
    try:yield state
    finally:
        state['release'].set();network.close();server.shutdown();server.server_close();thread.join(2)


@pytest.mark.parametrize('mode',['headers','body'])
def test_reused_tls_connection_silent_read_is_interruptible(pooled,mode):
    pooled['mode']=mode;pooled['warm']()
    begin=time.monotonic()
    with pytest.raises(RouteFailure) as exc:pooled['run']()
    assert exc.value.kind=='NO_INITIAL_MEANINGFUL_PROGRESS'
    assert exc.value.submitted and not exc.value.retryable
    assert time.monotonic()-begin<1
    assert pooled['requests'][0][1]==pooled['requests'][1][1], 'must exercise reused socket'
    assert len(pooled['requests'])==2


@pytest.mark.parametrize('stop',['cancel','shutdown'])
def test_reused_connection_cancel_and_shutdown_do_not_wait_180_seconds(pooled,stop):
    pooled['network'].routes['qwen']=dataclasses.replace(pooled['network'].routes['qwen'],first_response=180,progress=120)
    pooled['warm']();cancel=threading.Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(pooled['run'],'qwen',cancel)
        assert pooled['entered'].wait(1)
        begin=time.monotonic()
        if stop=='cancel':cancel.set()
        else:pooled['network'].close()
        with pytest.raises(RouteFailure) as exc:future.result(timeout=1)
        assert exc.value.kind==('USER_CANCELLED' if stop=='cancel' else 'GATEWAY_SHUTDOWN')
        assert time.monotonic()-begin<1
    assert pooled['requests'][0][1]==pooled['requests'][1][1]


def test_other_provider_completes_without_refreshing_stalled_provider(pooled):
    pooled['warm']()
    with ThreadPoolExecutor(max_workers=2) as executor:
        slow=executor.submit(pooled['run'],'qwen')
        assert pooled['entered'].wait(1)
        fast=executor.submit(pooled['run'],'deepseek')
        assert fast.result(timeout=1).text=='{"ok":true}'
        with pytest.raises(RouteFailure,match='NO_INITIAL_MEANINGFUL_PROGRESS'):slow.result(timeout=1)
    assert [r[0] for r in pooled['requests']]==['GET','qwen','deepseek']
    assert all(row.get('provider') in ('qwen','deepseek') for row in pooled['events'])
    for row in pooled['events']:
        if row.get('logical_id')!='warm':assert row.get('logical_id')==row.get('provider')


def test_actual_gateway_close_cancels_inflight_formal_client(runtime):
    from tests.providers.test_streaming_runtime import call
    from cgkn.providers.gateway_client import GatewayCompletionError
    runtime['mode']='stalled'
    network=runtime['gateway'].network
    network.routes['qwen']=dataclasses.replace(network.routes['qwen'],first_response=180,progress=120)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(copy_context().run,call,runtime)
        until=time.monotonic()+2
        while not runtime['posts'] and time.monotonic()<until:time.sleep(.005)
        assert runtime['posts']
        begin=time.monotonic();runtime['gateway'].close()
        with pytest.raises(GatewayCompletionError):future.result(timeout=1)
        assert time.monotonic()-begin<1.5
    assert len(runtime['posts'])==1
    ledger=json.loads((runtime['tmp']/'budget.json').read_text())
    assert ledger['calls'][0]['status']=='INTERRUPTED_UNKNOWN'


def test_gateway_process_crash_and_new_session_preserve_unknown(runtime):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from cgkn.providers.gateway_client import GatewayCompletionClient, GatewayCompletionError
    from cgkn.providers.client import ModelRoleConfig
    from scripts.provider_api_budget import ProviderBudgetExhausted
    root=Path(__file__).resolve().parents[2]
    script=runtime['tmp']/'isolated_crash_gateway.py'
    script.write_text("""import json,os,socket,ssl,sys,time
from pathlib import Path
original=socket.socket.connect
def local(self,address):
    if address[0] not in ('127.0.0.1','::1','localhost'):raise OSError('OFFLINE_EXTERNAL_CONNECTION_REFUSED')
    return original(self,address)
socket.socket.connect=local
import httpx
sys.path.insert(0,'D:/cgkn-provider-api-lab/src')
from cgkn_provider_lab.storage import ProviderConfigStore
from cgkn_provider_lab.models import ProviderConfig
from cgkn.providers.network_transport import NetworkClients,Route
from cgkn.providers.domestic_gateway import DomesticGateway
ProviderConfigStore.load=lambda self:[ProviderConfig(p,p,os.environ['TEST_PROVIDER_URL'],p+'-fixture',secret_backend='environment',secret_ref='SYNTHETIC_ONLY') for p in ('qwen','deepseek')]
routes={p:Route(p,None,first_response=180,progress=120) for p in ('qwen','deepseek')}
trust=ssl.create_default_context(cafile=os.environ['TEST_PROVIDER_CA'])
network=NetworkClients(routes,{p:p for p in routes},version='ISOLATED_CRASH_TEST',transports={p:httpx.HTTPTransport(verify=trust,trust_env=False,retries=0) for p in routes})
class Secrets:
    def resolve(self,p):return 'synthetic-offline'
gateway=DomesticGateway('D:/cgkn-provider-api-lab',None,network=network,secret_manager=Secrets())
info=gateway.start()
Path(os.environ['TEST_SESSION_FILE']).write_text(json.dumps({'url':info.base_url,'token':info.access_token,'pid':os.getpid(),'session_id':gateway.stream_session_id}))
while True:time.sleep(.1)
""")
    runtime['delay']=3
    env={**os.environ,'PYTHONPATH':str(root),'TEST_PROVIDER_URL':runtime['upstream_url'],'TEST_PROVIDER_CA':runtime['cert_path']}
    processes=[]
    def start(name):
        session=runtime['tmp']/(name+'.json')
        log=(runtime['tmp']/(name+'.log')).open('w')
        process=subprocess.Popen([sys.executable,str(script)],cwd=root,env={**env,'TEST_SESSION_FILE':str(session)},stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        processes.append((process,log))
        until=time.monotonic()+10
        while not session.exists() and process.poll() is None and time.monotonic()<until:time.sleep(.02)
        assert session.exists(),(runtime['tmp']/(name+'.log')).read_text()
        info=json.loads(session.read_text());assert info['pid']==process.pid
        return process,info
    kwargs=dict(system='crash fixture',user='same immutable content',schema_name='fixture',schema={'type':'object'},config=ModelRoleConfig('agent','qwen',max_output_tokens=100,model_id='qwen-fixture'))
    try:
        process,session=start('first-session')
        client=GatewayCompletionClient(session['url'],session['token']).bind_run('isolated-crash','same-attempt')
        with ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(copy_context().run,client.complete,**kwargs)
            until=time.monotonic()+3
            while not runtime['posts'] and time.monotonic()<until:time.sleep(.005)
            assert len(runtime['posts'])==1 and process.poll() is None
            # The Popen object identifies only the child created above, never a saved PID.
            process.kill();process.wait(timeout=3)
            with pytest.raises(GatewayCompletionError) as failure:future.result(timeout=3)
            assert failure.value.outcome_unknown
        before=(runtime['tmp']/'budget.json').read_bytes()
        ledger=json.loads(before);assert ledger['calls'][0]['status']=='INTERRUPTED_UNKNOWN'
        reopened,new_session=start('second-session')
        assert new_session['session_id']!=session['session_id']
        new_client=GatewayCompletionClient(new_session['url'],new_session['token']).bind_run('isolated-crash','same-attempt')
        with pytest.raises(ProviderBudgetExhausted,match='ALREADY_UNKNOWN'):new_client.complete(**kwargs)
        assert len(runtime['posts'])==1
        assert (runtime['tmp']/'budget.json').read_bytes()==before
        (runtime['tmp']/'crash-evidence.json').write_text(json.dumps({'scope':'ISOLATED_FAKE_TLS_PROVIDER','old_gateway_pid':process.pid,'new_gateway_pid':reopened.pid,'old_session':session['session_id'],'new_session':new_session['session_id'],'provider_posts':1,'reopened_posts':0,'status':'INTERRUPTED_UNKNOWN'}))
    finally:
        for process,log in processes:
            if process.poll() is None:process.kill();process.wait(timeout=3)
            log.close()


def test_independent_provider_finishes_during_qwen_meaningful_stream(pooled):
    pooled['mode']='stream'
    with ThreadPoolExecutor(max_workers=2) as executor:
        slow=executor.submit(pooled['run'],'qwen')
        assert pooled['progress'].wait(1)
        fast=executor.submit(pooled['run'],'deepseek')
        assert fast.result(timeout=1).text=='{"ok":true}'
        assert not slow.done(), 'DeepSeek should complete while Qwen is still streaming'
        assert slow.result(timeout=2).text=='{"ok":true}'
    assert [r[0] for r in pooled['requests']]==['qwen','deepseek']
    assert all(row['logical_id']==row['provider'] for row in pooled['events'])
