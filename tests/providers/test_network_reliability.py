"""Simulated faults use real loopback sockets/processes, never model requests."""
import concurrent.futures
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request

import httpx
import pytest
import yaml

from cgkn.providers.network_health import Circuits,probe
from cgkn.providers.network_transport import NetworkClients,Route,RouteFailure
from scripts.network_watchdog import InstanceLock,l1,process,start_proxy,controller


def unused_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); return s.getsockname()[1]


def wait_for(check,seconds=10):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=check()
        if value: return value
        time.sleep(.05)
    raise AssertionError('condition not observed within deadline')


def test_real_tcp_refusal_and_connect_tls_timeout():
    port=unused_port()
    row=probe('p','r',f'http://127.0.0.1:{port}','https://example.com/models',.25)
    assert row['category'] in ('TCP_REFUSED','TCP_TIMEOUT') and not row['tcp']
    class Tunnel(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            self.connection.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            time.sleep(.5)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Tunnel)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        url=f'http://127.0.0.1:{server.server_port}'
        def failed_observer(port):raise TypeError('diagnostic observer failure')
        row=probe('p','r',url,'https://example.com/models',.2,observer=failed_observer)
        assert row['tcp'] and row['connect'] and not row['tls'] and row['category']=='TLS_TIMEOUT'
        assert row['node_observation']['evidence']=='OBSERVER_UNAVAILABLE'
        c=NetworkClients({'a':Route('a',url,connect=.2)},{'p':'a'},version='socket-test')
        try:
            with pytest.raises(RouteFailure) as caught:
                c.opener('p',logical_id='tls',attempt_id='tls-1')(Request('https://example.com/models',data=b'{}'))
            assert caught.value.kind=='TLS_TIMEOUT'
            assert caught.value.retryable and not caught.value.submitted
        finally:c.close()
    finally:server.shutdown();server.server_close()


@pytest.mark.boundary
@pytest.mark.negative
def test_real_post_response_loss_is_not_safe_to_retry():
    hits=[]
    class Drop(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.close_connection=True
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Drop)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    c=NetworkClients({'a':Route('a',None)},{'p':'a'},version='socket-test')
    try:
        with pytest.raises(RouteFailure) as caught:
            c.opener('p',logical_id='one',attempt_id='one-1')(Request(f'http://127.0.0.1:{server.server_port}/',data=b'paid-like-body'))
        assert caught.value.submitted and not caught.value.retryable
        assert hits==[b'paid-like-body']
    finally:c.close();server.shutdown();server.server_close()


@pytest.mark.boundary
@pytest.mark.happy_path
def test_concurrent_circuit_provider_isolation_cooldown_and_recovery():
    clock=[0]; health=Circuits(threshold=2,cooldown=10,clock=lambda:clock[0])
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _:health.record('qwen','primary',False),range(8)))
    assert not health.available('qwen','primary') and health.available('grok','primary')
    assert health.available('qwen','backup')
    clock[0]=11
    assert health.available('qwen','primary')
    assert health.record('qwen','primary',True)=='RECOVERING'
    assert health.record('qwen','primary',True)=='HEALTHY'


@pytest.mark.boundary
@pytest.mark.negative
def test_route_circuit_switch_and_all_open_never_send():
    seen=[]; health=Circuits(threshold=1,cooldown=60)
    c=NetworkClients({'a':Route('a',None,fallback='b'),'b':Route('b',None,fallback='a')},
        {'p':'a'},version='test',health=health,
        transports={x:httpx.MockTransport(lambda req:httpx.Response(200,content=b'ok')) for x in ['a','b']},log=seen.append)
    try:
        health.record('p','a',False)
        assert c.opener('p',logical_id='x',attempt_id='1')(Request('https://example.com')).read()==b'ok'
        assert {e['route_id'] for e in seen}=={'b'}
        health.record('p','b',False)
        with pytest.raises(RouteFailure,match='NetworkUnavailable'):
            c.opener('p',logical_id='x',attempt_id='2')(Request('https://example.com'))
    finally:c.close()


def test_singleton_and_port_conflict(tmp_path):
    with InstanceLock(tmp_path/'lock'):
        with pytest.raises(RuntimeError,match='ALREADY_RUNNING'):
            with InstanceLock(tmp_path/'lock'):pass
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1',0)); occupied.listen()
        config=dict(executable=sys.executable,proxy_config=str(tmp_path/'config.yaml'),ports=[occupied.getsockname()[1]])
        assert start_proxy(config)=='PORT_CONFLICT'


@pytest.mark.skipif(not Path('D:/Clash Verge/verge-mihomo.exe').exists(),reason='real isolated Mihomo binary unavailable')
@pytest.mark.parametrize('fault',['crash','unresponsive'])
def test_real_mihomo_crash_recovery_duplicate_and_normal_stop(tmp_path,fault):
    ports=[unused_port() for _ in range(3)]
    private=tmp_path/'config.yaml'
    private.write_text(yaml.safe_dump({'allow-lan':False,'mode':'rule','log-level':'silent',
        'external-controller':f'127.0.0.1:{ports[2]}','tun':{'enable':False},
        'listeners':[{'name':'test-'+str(i),'type':'mixed','listen':'127.0.0.1','port':port,'proxy':'DIRECT'} for i,port in enumerate(ports[:2])],
        'rules':['MATCH,DIRECT']}))
    config=dict(executable='D:/Clash Verge/verge-mihomo.exe',proxy_config=str(private),state_dir=str(tmp_path/'state'),
        ports=ports,interval=.2,failure_threshold=1,probe_every=10000,max_restarts_per_hour=3)
    source=tmp_path/'watchdog.json';source.write_text(json.dumps(config))
    watchdog=subprocess.Popen([sys.executable,'-m','scripts.network_watchdog','run','--config',str(source),'--duration','25'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        original=wait_for(lambda:l1(config)['pid'] if l1(config)['ok'] else None,30)
        assert start_proxy(config)=='ALREADY_RUNNING'
        duplicate=subprocess.run([sys.executable,'-m','scripts.network_watchdog','run','--config',str(source),'--duration','1'],capture_output=True,timeout=5)
        assert duplicate.returncode==0 and b'ALREADY_RUNNING' in duplicate.stdout
        t=time.monotonic()
        if fault=='crash':process(config).kill()
        else:process(config).suspend()
        new_pid=wait_for(lambda:l1(config)['pid'] if l1(config)['ok'] and l1(config)['pid']!=original else None,18)
        assert new_pid!=original
        (tmp_path/'state'/'stop').touch()
        watchdog.wait(5)
        assert watchdog.returncode==0
        logs=[json.loads(line) for line in (tmp_path/'state'/'watchdog.jsonl').read_text().splitlines()]
        assert len([r for r in logs if r.get('event')=='restart'])==2
        expected='PROCESS_EXIT_OR_MISSING' if fault=='crash' else 'PROCESS_UNRESPONSIVE'
        assert [r for r in logs if r.get('event')=='restart'][-1]['reason']==expected
        assert logs[-1]['reason']=='requested'
        (tmp_path/'recovery-evidence.json').write_text(json.dumps({'initial_pid':original,'recovered_pid':new_pid,'recovery_seconds':time.monotonic()-t,'logs':logs},indent=2))
    finally:
        if watchdog.poll() is None: watchdog.terminate();watchdog.wait(5)
        proc=process(config)
        if proc:proc.terminate();proc.wait(5)


@pytest.mark.skipif(not Path('D:/Clash Verge/verge-mihomo.exe').exists(),reason='real isolated Mihomo binary unavailable')
def test_real_mihomo_node_fallback_and_rejoin(tmp_path):
    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(204 if self.path.endswith('/health') else 200)
            self.end_headers()
            if not self.path.endswith('/health'):self.wfile.write(b'backup-target')
        def log_message(self,*args):pass
    class Primary(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            self.connection.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
            first=self.rfile.readline()
            while self.rfile.readline() not in (b'\r\n',b''):pass
            health=b'/health ' in first
            body=b'' if health else b'primary-node'
            self.connection.sendall((b'HTTP/1.1 204 No Content' if health else b'HTTP/1.1 200 OK')+
                b'\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
            self.close_connection=True
        def do_GET(self):
            self.send_response(204 if self.path.endswith('/health') else 200)
            self.end_headers()
            if not self.path.endswith('/health'):self.wfile.write(b'primary-node')
        def log_message(self,*args):pass
    target=ThreadingHTTPServer(('127.0.0.1',0),Target)
    primary=ThreadingHTTPServer(('127.0.0.1',0),Primary);primary_port=primary.server_port
    for s in (target,primary):threading.Thread(target=s.serve_forever,daemon=True).start()
    port,api=unused_port(),unused_port()
    private=tmp_path/'config.yaml'
    private.write_text(yaml.safe_dump({'allow-lan':False,'mode':'rule','log-level':'silent',
        'external-controller':f'127.0.0.1:{api}','tun':{'enable':False},
        'proxies':[{'name':'primary','type':'http','server':'127.0.0.1','port':primary_port}],
        'proxy-groups':[{'name':'api-fallback','type':'fallback','proxies':['primary','DIRECT'],
            'url':f'http://127.0.0.1:{target.server_port}/health','interval':1,'timeout':500,'lazy':False,'max-failed-times':1}],
        'listeners':[{'name':'isolation','type':'mixed','listen':'127.0.0.1','port':port,'proxy':'api-fallback'}],
        'rules':['MATCH,DIRECT']}))
    config=dict(executable='D:/Clash Verge/verge-mihomo.exe',proxy_config=str(private),state_dir=str(tmp_path/'state'),ports=[port,api])
    timeline=[]
    try:
        assert start_proxy(config)=='STARTED'
        wait_for(lambda:l1(config)['ok'],30)
        with httpx.Client(proxy=f'http://127.0.0.1:{port}',trust_env=False,timeout=2) as client:
            url=f'http://127.0.0.1:{target.server_port}/data'
            assert client.get(url).content==b'primary-node'
            primary.shutdown();primary.server_close();t=time.monotonic()
            wait_for(lambda:controller(config,'/proxies/api-fallback').get('now')=='DIRECT')
            assert client.get(url).content==b'backup-target'
            timeline.append(dict(event='primary_down_backup_selected',seconds=time.monotonic()-t))
            primary=ThreadingHTTPServer(('127.0.0.1',primary_port),Primary)
            threading.Thread(target=primary.serve_forever,daemon=True).start();t=time.monotonic()
            wait_for(lambda:controller(config,'/proxies/api-fallback').get('now')=='primary')
            assert client.get(url).content==b'primary-node'
            timeline.append(dict(event='primary_rejoined',seconds=time.monotonic()-t))
            primary.shutdown();primary.server_close();target.shutdown();target.server_close();t=time.monotonic()
            try:
                result=client.get(url)
                assert result.status_code>=400 or not result.content
            except httpx.HTTPError:pass
            assert time.monotonic()-t<3
            timeline.append(dict(event='both_unavailable_bounded',seconds=time.monotonic()-t))
        (tmp_path/'fallback-evidence.json').write_text(json.dumps({'scope':'ISOLATED_MIHOMO_REAL_HTTP_SOCKETS_NO_MODEL','timeline':timeline},indent=2))
    finally:
        for s in (primary,target):s.shutdown();s.server_close()
        proc=process(config)
        if proc:proc.terminate();proc.wait(5)


def test_component_boundary_reports_network_blocked():
    from cgkn.executors.network_health import NetworkHealthExecutor,NETWORK_HEALTH_COMPONENT
    from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus
    spec=dict(provider='p',route_id='r',proxy_url=f'http://127.0.0.1:{unused_port()}',endpoint='https://example.com/models',timeout=.1)
    request=BlockExecutionRequest(project_id='test',run_id='run',attempt_id='attempt',node_id='network',
        component_ref=NETWORK_HEALTH_COMPONENT.ref,executor_ref='local.network-health@1',
        task_context=TaskContext('Check network'),input_values={'probe':spec},declared_effects=('network.probe',))
    result=NetworkHealthExecutor().execute(request)
    assert result.status==BlockStatus.BLOCKED and result.error.message=='NetworkUnavailable'
    assert result.outputs['health']['model_calls']==0


def test_null_controller_connections_do_not_crash_watchdog(monkeypatch):
    from scripts import network_watchdog
    monkeypatch.setattr(network_watchdog,'controller',lambda *args,**kwargs:{'connections':None})
    assert network_watchdog.observe_node({},12345)=={'evidence':'NOT_CAPTURED','chains':[]}
