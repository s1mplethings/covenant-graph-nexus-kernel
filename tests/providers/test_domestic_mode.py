"""Local conformance/fault tests; synthetic responses are never L4 evidence."""
import dataclasses
import json
from pathlib import Path
import socket
import struct
import sys

import httpx
import pytest

from cgkn.providers.direct_transport import PreconnectInterfaceBackend,IP_UNICAST_IF,parse_dns
from cgkn.providers.domestic_mode import domestic_state,SubstitutionAdmission,DomesticFailoverClient
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.gateway_client import GatewayCompletionClient,GatewayCompletionError
from cgkn.providers.network_transport import NetworkClients,Route
from cgkn.providers import ModelRoleConfig
from tests.providers.test_application_network import profile


@pytest.mark.boundary
@pytest.mark.happy_path
def test_outgoing_interface_is_set_before_connect(monkeypatch):
    calls=[]
    class Sock:
        def setsockopt(self,*args):calls.append(('option',args))
        def settimeout(self,*args):pass
        def bind(self,*args):calls.append(('bind',args))
        def connect(self,*args):
            assert ('option',(socket.IPPROTO_IP,IP_UNICAST_IF,socket.htonl(14))) in calls
            assert calls[-1][0]=='bind';calls.append(('connect',args))
        def close(self):pass
    monkeypatch.setattr(socket,'socket',lambda *a,**k:Sock())
    stream=PreconnectInterfaceBackend().connect_tcp('8.8.8.8',443,1,'192.168.1.100',[(socket.IPPROTO_IP,IP_UNICAST_IF,socket.htonl(14))])
    stream.close();assert calls[-1][0]=='connect'


@pytest.mark.parametrize('ip,accepted',[('39.96.213.166',True),('198.18.0.181',False),('127.0.0.1',False)])
@pytest.mark.boundary
@pytest.mark.negative
def test_dns_rejects_fakeip_and_private_addresses(ip,accepted):
    packet=struct.pack('!6H',17,0x8180,0,1,0,0)+b'\0'+struct.pack('!HHIH',1,1,30,4)+socket.inet_aton(ip)
    if accepted:assert parse_dns(packet,17)[0]==[ip]
    else:
        with pytest.raises(ValueError,match='NON_PUBLIC'):parse_dns(packet,17)
    with pytest.raises(ValueError):parse_dns(packet,18)


def test_domestic_network_readiness_is_separate_from_grok():
    rows=[dict(provider='qwen',http_reached=True),dict(provider='deepseek',http_reached=True),dict(provider='grok',http_reached=False)]
    assert domestic_state(rows)=='DOMESTIC_READY'
    rows[0]['http_reached']=False;assert domestic_state(rows)=='DOMESTIC_DEGRADED'
    rows[1]['http_reached']=False;assert domestic_state(rows)=='DOMESTIC_UNAVAILABLE'
    rows[0]['http_reached']=True;assert domestic_state(rows)=='DOMESTIC_DEGRADED'
    rows[1]['http_reached']=True;assert domestic_state(rows)=='DOMESTIC_READY'


def test_domestic_environment_selects_gateway_and_fails_closed_without_session(profile, monkeypatch):
    from cgkn.providers import application_network as app
    from cgkn.providers.gateway_client import completion_client_from_environment
    monkeypatch.setenv('CGKN_NETWORK_MODE', 'domestic')
    with pytest.raises(RuntimeError, match='DOMESTIC_GATEWAY_UNAVAILABLE_NO_FALLBACK'):
        completion_client_from_environment()
    monkeypatch.setattr(app, 'session', lambda *a, **k: (
        {'base_url': 'http://127.0.0.1:43210/v1', 'access_token': 'synthetic-private-local-token'},
        {'pid': 42}))
    client = completion_client_from_environment()
    assert isinstance(client, GatewayCompletionClient) and client.enforce_budget
    assert 'synthetic-private-local-token' not in repr(client)


def test_domestic_policy_rejects_proxy_and_shared_pool(tmp_path):
    doc=json.loads(Path('config/network_routes.json').read_text());path=tmp_path/'routes.json'
    doc['transport_profiles']['qwen_direct']['proxy_url']='http://127.0.0.1:17890'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):NetworkClients.load(path)
    doc=json.loads(Path('config/network_routes.json').read_text());doc['provider_bindings']['deepseek']='qwen_direct';path.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='INDEPENDENT'):NetworkClients.load(path)


@pytest.mark.parametrize('category,unknown',[('network_unavailable_before_send',False),('provider_outcome_unknown',True)])
def test_network_failure_blocks_worker_without_task_writes_or_automatic_retry(tmp_path,category,unknown):
    from cgkn.executors.llm import LLMExecutor
    from cgkn.execution import BlockExecutionRequest,TaskContext,BlockStatus
    class Client:
        calls=0
        def complete(self,**kwargs):
            self.calls+=1;raise GatewayCompletionError(category,'synthetic network failure',outcome_unknown=unknown)
    client=Client();executor=LLMExecutor(tmp_path,client,ModelRoleConfig('worker','deepseek'))
    from cgkn.orchestration.leaf_contract import build_leaf_contract
    contract=build_leaf_contract(goal='Bounded transport failure probe',kind='IMPLEMENTATION',
        scope=['output.txt'],acceptance=['file-content'],checker='fixture.files',
        output_identity='output.txt',effect_domains=['output.txt'],executor='llm.cheap@1',
        expected_delta='write the requested output file')
    request=BlockExecutionRequest(project_id='domestic-test',run_id='r',attempt_id='1',node_id='worker',component_ref='test.worker@1',executor_ref='llm.cheap@1',task_context=TaskContext('Do bounded work',{'leaf_contract':contract}))
    from tests.executor_authority_support import invoke_bound_executor
    result=invoke_bound_executor(executor,request)
    assert result.status==BlockStatus.BLOCKED and not result.retryable and client.calls==1
    assert result.error.details['failure_class']=='network' and result.error.details['outcome_unknown']==unknown
    assert not list(tmp_path.iterdir())


def test_rollback_validates_all_hashes_before_any_write(tmp_path):
    import hashlib
    from scripts.domestic_network import rollback
    rows=[]
    for name in ['one','two']:
        (tmp_path/name).write_text('new');(tmp_path/(name+'.old')).write_text('old')
        rows.append(dict(path=name,backup=name+'.old',after_sha256=hashlib.sha256(b'new').hexdigest(),before_sha256=hashlib.sha256(b'old').hexdigest()))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'files':rows}))
    assert rollback(manifest,workspace=tmp_path)['state']=='HASHES_VALID_DRY_RUN'
    (tmp_path/'two').write_text('unrelated-later-change')
    with pytest.raises(ValueError,match='CURRENT_HASH'):rollback(manifest,apply=True,workspace=tmp_path)
    assert (tmp_path/'one').read_text()=='new'


def admission(primary,backup):
    return SubstitutionAdmission('worker','bounded-json',primary,backup,frozenset(['structured-json']),
        frozenset(['structured-json']),'SYNTHETIC_TEST_ADMISSION_ONLY')


def arguments(primary):
    return dict(system='Return JSON',user='Check',schema_name='bounded-json',schema={'type':'object'},config=ModelRoleConfig('worker',primary))


@pytest.mark.parametrize('primary,backup',[('qwen','deepseek'),('deepseek','qwen')])
@pytest.mark.boundary
@pytest.mark.happy_path
def test_capability_admitted_failover_only_before_submission(primary,backup):
    calls=[];events=[]
    class Client:
        def complete(self,**kwargs):
            model=kwargs['config'].model;calls.append(model)
            if model==primary:raise GatewayCompletionError('network_unavailable_before_send','isolated')
            return 'ok'
    c=DomesticFailoverClient(Client(),[admission(primary,backup)],events.append)
    assert c.complete(**arguments(primary))=='ok' and calls==[primary,backup]
    assert len({e['logical_id'] for e in events})==1 and len({e['attempt_id'] for e in events})==2


@pytest.mark.boundary
@pytest.mark.negative
def test_both_fail_unknown_submission_and_capability_gate_never_blind_retry():
    calls=[]
    class Client:
        category='network_unavailable_before_send';unknown=False
        def complete(self,**kwargs):
            calls.append(kwargs['config'].model)
            raise GatewayCompletionError(self.category,'isolated',outcome_unknown=self.unknown)
    raw=Client();c=DomesticFailoverClient(raw,[admission('qwen','deepseek')])
    with pytest.raises(GatewayCompletionError):c.complete(**arguments('qwen'))
    assert calls==['qwen','deepseek']
    calls.clear();raw.category='provider_outcome_unknown';raw.unknown=True
    with pytest.raises(GatewayCompletionError):c.complete(**arguments('qwen'))
    assert calls==['qwen']
    calls.clear();raw.category='network_unavailable_before_send';raw.unknown=False
    with pytest.raises(GatewayCompletionError):c.complete(**{**arguments('qwen'),'schema_name':'stronger-task'})
    assert calls==['qwen']
    with pytest.raises(ValueError,match='CAPABILITY_GATE'):
        dataclasses.replace(admission('qwen','deepseek'),required_capabilities=frozenset(['grok-only-capability']))


@pytest.mark.skipif(not Path('D:/cgkn-provider-api-lab/src').exists(),reason='existing API Lab dependency unavailable')
@pytest.mark.parametrize('mode',['ok','connect','read'])
def test_existing_gateway_uses_routed_adapters_and_preserves_unknown(mode,monkeypatch,tmp_path):
    profile=tmp_path/'legacy.json';profile.write_text('{"mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(profile))
    seen=[]
    def handler(req):
        seen.append(req.url.host)
        if mode=='connect':raise httpx.ConnectError('synthetic-before-send')
        if mode=='read':raise httpx.ReadError('synthetic-after-send')
        req.extensions['trace']('http11.send_request_headers.started', {'request': req})
        req.extensions['trace']('http11.send_request_headers.complete', {'request': req})
        from tests.providers.stream_fixtures import upstream_wire
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=upstream_wire(json.loads(req.content)['model'],'{"ok":true}'))

    network=NetworkClients({'q':Route('q',None),'d':Route('d',None),'g':Route('g','http://127.0.0.1:1')},
        {'qwen':'q','deepseek':'d','grok':'g'},version='SYNTHETIC_GATEWAY_CONFORMANCE',disabled_providers=['grok'],
        transports={x:httpx.MockTransport(handler) for x in ['q','d','g']})
    class Secrets:
        def resolve(self,provider):return 'synthetic-not-a-real-key'
    gateway=DomesticGateway('D:/cgkn-provider-api-lab','unused',network=network,secret_manager=Secrets())
    info=gateway.start()
    # The loopback client must not inherit a broken environment proxy.
    for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:monkeypatch.setenv(k,'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY','')
    client=GatewayCompletionClient(info.base_url,info.access_token,enforce_budget=False)
    try:
        assert {p.provider_id for p in gateway.providers}=={'qwen','deepseek'}
        assert network.clients['q'] is not network.clients['d']
        if mode=='ok':assert json.loads(client.complete(**arguments('qwen')).text)=={'ok':True}
        else:
            with pytest.raises(GatewayCompletionError) as caught:client.complete(**arguments('qwen'))
            assert caught.value.category==('network_unavailable_before_send' if mode=='connect' else 'provider_outcome_unknown')
            assert caught.value.outcome_unknown==(mode=='read')
        assert seen==['dashscope.aliyuncs.com']
    finally:gateway.close()


def test_failover_and_recovery_preserve_completed_cgkn_task(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('domestic_state_fixture','tests/runtime/test_graph_commit.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    executor,runner=fixture.setup(tmp_path/'state');tree=fixture.tree('written')
    fixture.run(runner,tree)
    failed=set();calls=[]
    class Client:
        def complete(self,**kwargs):
            alias=kwargs['config'].model;calls.append(alias)
            if alias in failed:raise GatewayCompletionError('network_unavailable_before_send','synthetic network fault')
            return alias
    c=DomesticFailoverClient(Client(),[admission('qwen','deepseek'),admission('deepseek','qwen')])
    failed.add('qwen');assert c.complete(**arguments('qwen'))=='deepseek'
    failed.clear();failed.add('deepseek');assert c.complete(**arguments('deepseek'))=='qwen'
    failed.add('qwen')
    with pytest.raises(GatewayCompletionError):c.complete(**arguments('qwen'))
    failed.remove('qwen');assert c.complete(**arguments('qwen'))=='qwen'
    failed.remove('deepseek');assert c.complete(**arguments('deepseek'))=='deepseek'
    restored=fixture.probe_runner(runner.registry,fixture.FileRunStore(tmp_path/'state'),execution_mode='GOVERNED')
    result=fixture.run(restored,tree,resume=True)
    assert executor.calls==[('r','written')] and result.reused_nodes==('written',)
    assert calls==['qwen','deepseek','deepseek','qwen','qwen','deepseek','qwen','deepseek']
