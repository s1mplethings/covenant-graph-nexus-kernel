"""Real loopback Gateway, real adapters, synthetic in-memory upstream only."""
import json,threading,time
from pathlib import Path
from urllib.request import Request
import httpx,pytest
from cgkn.providers.network_transport import NetworkClients,Route
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.gateway_client import GatewayCompletionClient,_open_loopback
from cgkn.providers.client import ModelRoleConfig
from cgkn.providers.route_diagnostics import install

@pytest.fixture
def gateway(tmp_path,monkeypatch):
    legacy=tmp_path/'legacy.json';legacy.write_text('{"kind":"CGKNApplicationNetwork","mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(legacy))
    from tests.providers.test_domestic_repair import admit
    admit(monkeypatch,tmp_path)
    blocked=threading.Event();release=threading.Event();control=dict(block=False,status=200,mode='valid',method='GET');logs=[];models={}
    def upstream(request):
        if request.method=='POST':
            request.extensions['trace']('http11.send_request_headers.started',{'request':request})
        provider='qwen' if 'aliyun' in request.url.host else 'deepseek'
        network.emit(dict(phase='mock_upstream',observed_provider=provider))
        if provider=='qwen' and control['block'] and request.method==control['method']:
            blocked.set();assert release.wait(5)
        if request.method=='GET':
            if control['mode']=='dns_failure':raise httpx.ConnectError('DIRECT_DNS_FAILED')
            if control['mode']=='secret_failure':raise httpx.ConnectError('secret-must-not-leak')
            if control['mode']=='invalid':return httpx.Response(control['status'],content=b'{bad')
            data=[{'id':models[provider]}] if control['mode']=='valid' else [{'id':'not-configured'}]
            return httpx.Response(control['status'],json={'data':data})
        from tests.providers.stream_fixtures import upstream_wire
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=upstream_wire(models[provider],json.dumps({'provider':provider})))
    routes={p:Route(route_id=p,proxy_url=None,read=4,deadline=5) for p in ('qwen','deepseek')}
    network=NetworkClients(routes,{p:p for p in routes},version='OFFLINE',transports={p:httpx.MockTransport(upstream) for p in routes},log=logs.append)
    class Secrets:
        def resolve(self,provider):return 'synthetic-upstream-only'
    gw=DomesticGateway('D:/cgkn-provider-api-lab',None,network=network,secret_manager=Secrets())
    control['audit_path']=str(tmp_path/'audit.jsonl')
    models.update({p.provider_id:p.model for p in gw.providers});install(gw,read_only=False,
        identity=dict(gateway_session_id='offline-session',network_sha256='offline-config'),
        audit_path=control['audit_path']);info=gw.start()
    client=GatewayCompletionClient(info.base_url,info.access_token)
    try:yield client,blocked,release,control,logs
    finally:release.set();gw.close()

@pytest.mark.parametrize('method',['GET','POST'])
def test_qwen_block_does_not_serialize_deepseek(gateway,method):
    client,blocked,release,control,logs=gateway;control.update(block=True,method=method);results=[]
    def qwen():
        results.append(client.models('qwen') if method=='GET' else client.complete(system='',user='blocked qwen',schema_name='raw',schema=None,config=ModelRoleConfig('agent','qwen',max_output_tokens=30)))
    thread=threading.Thread(target=qwen);thread.start();assert blocked.wait(2)
    start=time.monotonic()
    result=client.complete(system='',user='free deepseek',schema_name='raw',schema=None,config=ModelRoleConfig('worker','deepseek',max_output_tokens=30))
    assert json.loads(result.text)['provider']=='deepseek'
    assert time.monotonic()-start<1.5 and thread.is_alive()
    release.set();thread.join(3);assert not thread.is_alive()
    if method=='GET':
        row=results[0];assert row['ok']
        assert all(event.get('logical_id')==row['request_id'] for event in row['trace'])
        assert not any(event.get('provider')=='deepseek' for event in row['trace'])
    markers=[row for row in logs if row.get('phase')=='mock_upstream']
    assert {row['provider'] for row in markers}=={'qwen','deepseek'}
    assert all(row['provider']==row['observed_provider'] for row in markers)

@pytest.mark.parametrize('status,mode,reason',[(201,'valid','UNEXPECTED_UPSTREAM_STATUS'),(401,'missing','UNEXPECTED_UPSTREAM_STATUS'),(200,'missing','CONFIGURED_MODEL_MISSING'),(200,'invalid','INVALID_MODEL_LIST_RESPONSE')])
def test_diagnostic_preserves_real_status_and_failure(gateway,status,mode,reason):
    client,_,_,control,_=gateway;control.update(status=status,mode=mode)
    result=client.models('qwen')
    assert result['gateway_http_status']==200
    assert result['upstream_http_status']==status and result['reason']==reason
    assert not result['ok'] and result['response_sha256'] and result['response_bytes']>0

@pytest.mark.parametrize('mode,reason',[('dns_failure','DIRECT_DNS_FAILED'),('secret_failure','TCP_CONNECT_FAILED')])
def test_local_503_preserves_bounded_diagnostics_without_exception_text(gateway,mode,reason):
    client,_,_,control,_=gateway;control['mode']=mode
    row=client.models('qwen')
    assert row['gateway_http_status']==503 and row['upstream_http_status'] is None
    assert row['request_id'] and row['gateway_pid'] and row['route_id']=='qwen'
    assert row['reason']==reason and row['exception_type']=='RouteFailure'
    assert row['stages'][:3]==['provider_slot_acquired','credential_resolved','route_initialized']
    assert row['outcome']['submitted'] is False
    assert row['trace'][-1]['last_transport_phase']=='queued'
    assert not row['ok'] and 'secret-must-not-leak' not in json.dumps(row)
    assert row['gateway_session_id']=='offline-session'
    persisted=[json.loads(line) for line in Path(control['audit_path']).read_text().splitlines()]
    assert len(persisted)==1 and persisted[0]['request_id']==row['request_id']
    assert persisted[0]['reason']==reason and 'secret-must-not-leak' not in json.dumps(persisted)

@pytest.mark.parametrize('healthy',[True,False])
def test_plugin_domestic_summary_uses_saved_roles_not_legacy_model_default(healthy):
    import importlib.util,types
    path=Path(__file__).resolve().parents[2]/'plugins/cgkn/scripts/cgkn_mcp_server.py'
    spec=importlib.util.spec_from_file_location('probe_summary_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    server=object.__new__(module.CGKNPluginServer)
    server._project=lambda value:Path(value)
    server.core=types.SimpleNamespace(redact=lambda text:text)
    checks=[dict(provider=p,ok=healthy,gateway_http_status=200 if healthy else 503,
                 upstream_http_status=200 if healthy else None) for p in ('qwen','deepseek')]
    result=dict(ok=healthy,configured=True,endpoint_mode='non_generation_models',
                saved_roles={'agent':{'provider_id':'qwen'},'worker':{'provider_id':'deepseek'}},
                checked_providers=['qwen','deepseek'],gateway_state={'state':'ALIVE'},network_route_evidence=checks)
    server.connectivity=types.SimpleNamespace(check_api=lambda *args:result,_base_url_domain=lambda value:'')
    row=server.probe_provider(dict(project_root='.',confirmation='RUN_PROVIDER_PROBE'))
    assert row['ok']==healthy and row['probe']['model'] is None
    assert row['probe']['provider_checks']==checks and row['probe']['gateway_state']['state']=='ALIVE'
    assert not row['probe']['generation_executed'] and row['probe']['model_calls']==0
    assert 'gpt-4.1-mini' not in json.dumps(row)
