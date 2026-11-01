import dataclasses,json
from pathlib import Path
from unittest.mock import Mock
import pytest
from cgkn.providers import application_network as app

@pytest.fixture
def profile(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[2]
    routes=json.loads((root/'config/network_routes.json').read_text(encoding='utf-8'))
    routing=json.loads((root/'config/provider_profiles/domestic_model_routing.json').read_text(encoding='utf-8'))
    for name,doc in [('network.json',routes),('models.json',routing)]:
        (tmp_path/name).write_text(json.dumps(doc),encoding='utf-8')
    doc=dict(kind='CGKNApplicationNetwork',mode='domestic',network_config='network.json',model_routing='models.json',
             gateway_state_dir='state',interface_guid=routes['transport_profiles']['qwen_direct']['interface_guid'],
             gateway_python='not-used',auto_start_gateway=False)
    path=tmp_path/'application.json';path.write_text(json.dumps(doc),encoding='utf-8')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(path));monkeypatch.delenv('CGKN_NETWORK_MODE',raising=False)
    return path,doc

def test_saved_profile_selects_gateway_and_domestic_models_without_env(profile,monkeypatch):
    from cgkn.providers.gateway_client import completion_client_from_environment,GatewayCompletionClient
    monkeypatch.setattr(app,'session',lambda *a,**k:({'base_url':'http://127.0.0.1:12345/v1','access_token':'synthetic-local'},{'pid':42}))
    client=completion_client_from_environment()
    assert isinstance(client,GatewayCompletionClient)
    assert app.routing_path('wrong-default').name=='models.json'

@pytest.mark.parametrize('fault',['proxy','guid','role','fallback','missing','env'])
def test_mismatched_profile_never_creates_legacy_client(profile,monkeypatch,fault):
    from cgkn.providers.gateway_client import completion_client_from_environment
    path,doc=profile
    if fault in ('proxy','guid'):
        p=path.parent/'network.json';d=json.loads(p.read_text());d['transport_profiles']['qwen_direct'][{'proxy':'proxy_url','guid':'interface_guid'}[fault]]='invalid';p.write_text(json.dumps(d))
    elif fault in ('role','fallback'):
        p=path.parent/'models.json';d=json.loads(p.read_text())
        if fault=='role':d['roles']['worker']['provider_id']='grok'
        else:d['fallback']='allow'
        p.write_text(json.dumps(d))
    elif fault=='missing':path.unlink()
    else:monkeypatch.setenv('CGKN_NETWORK_MODE','legacy')
    with pytest.raises(RuntimeError,match='CONFIG_MISMATCH'):completion_client_from_environment()

def test_unavailable_gateway_and_explicit_legacy_client_fail_closed(profile):
    from cgkn.providers.gateway_client import completion_client_from_environment
    from cgkn.providers.client import OpenAICompatibleClient,ModelRoleConfig
    with pytest.raises(RuntimeError,match='GATEWAY_UNAVAILABLE'):completion_client_from_environment()
    with pytest.raises(RuntimeError,match='LEGACY_CLIENT_REFUSED'):
        OpenAICompatibleClient().complete(system='',user='',schema_name='x',schema={},config=ModelRoleConfig('agent','qwen'))

def test_old_http_entrypoints_cannot_post_or_dial_old_host(profile,monkeypatch):
    from urllib.request import Request
    from scripts import provider_transport,check_connectivity
    monkeypatch.setattr(app,'session',lambda *a,**k:({'base_url':'http://127.0.0.1:12345/v1','access_token':'synthetic-local'},{}))
    for opener in (provider_transport._urlopen,check_connectivity._urlopen):
        with pytest.raises(RuntimeError,match='OLD_ENDPOINT_REFUSED'):
            opener(Request('https://dashscope.aliyuncs.com/compatible-mode/v1/models'),2)
        with pytest.raises(RuntimeError,match='REQUIRES_BUDGETED'):
            opener(Request('http://127.0.0.1:12345/v1/responses',data=b'{}'),2)

def test_probe_never_calls_generation_endpoint(profile,monkeypatch):
    from scripts import check_connectivity
    rows=[dict(provider=p,upstream_http_status=200,ok=True,configured_model_listed=True,model_list_parse_valid=True) for p in ('qwen','deepseek')]
    monkeypatch.setattr(app,'probe_models',lambda:rows)
    state=Path(app.settings()['gateway_state_dir']);state.mkdir()
    result=check_connectivity.check_api(True,20,'gpt-4.1')
    assert result['ok'] and result['model_calls']==0
    assert result['endpoint_mode']=='non_generation_models'
    assert result['network_route_evidence']==rows

@pytest.mark.parametrize('text',['[]','null','{broken'])
def test_malformed_profile_has_explicit_configuration_failure(profile,text):
    path,_=profile;path.write_text(text,encoding='utf-8')
    with pytest.raises(RuntimeError,match='CONFIG_MISMATCH'):app.settings()

def test_concurrent_bootstrap_waits_for_existing_app_lock(monkeypatch,tmp_path):
    from scripts import network_watchdog
    events=[]
    class Lock:
        def __init__(self,path):pass
        def __enter__(self):
            events.append('enter')
            if events.count('enter')==1:raise RuntimeError('WATCHDOG_ALREADY_RUNNING')
        def __exit__(self,*args):events.append('exit')
    monkeypatch.setattr(network_watchdog,'InstanceLock',Lock)
    monkeypatch.setattr(app.time,'sleep',lambda delay:events.append('wait'))
    with app.bootstrap_lock(tmp_path/'bootstrap.lock'):events.append('owned')
    assert events==['enter','wait','enter','owned','exit']

def test_non_generation_probe_cannot_be_used_as_capability_evidence(profile,monkeypatch):
    from scripts import check_connectivity
    monkeypatch.setattr(app,'probe_models',lambda:pytest.fail('Capability probe must stay blocked'))
    result=check_connectivity.check_api(True,20,'qwen',structured=True)
    assert not result['ok'] and result['status']=='BLOCKED'
    assert result['structured_output_valid'] is False and result['model_calls']==0


def test_missing_default_profile_cannot_select_legacy(tmp_path,monkeypatch):
    from cgkn.providers.gateway_client import completion_client_from_environment
    monkeypatch.setattr(app,'ROOT',tmp_path)
    monkeypatch.delenv('CGKN_APPLICATION_PROFILE',raising=False)
    with pytest.raises(RuntimeError,match='CONFIG_MISSING'):completion_client_from_environment()


def test_explicit_legacy_profile_cannot_override_domestic_environment(tmp_path,monkeypatch):
    p=tmp_path/'legacy.json';p.write_text('{"kind":"CGKNApplicationNetwork","mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(p));monkeypatch.setenv('CGKN_NETWORK_MODE','domestic')
    with pytest.raises(RuntimeError,match='CONFIG_MISMATCH'):app.settings()


def test_gateway_import_does_not_load_legacy_sender():
    import subprocess,sys
    code="import sys; import cgkn.providers.gateway_client; assert 'cgkn.providers.legacy_client' not in sys.modules"
    result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
