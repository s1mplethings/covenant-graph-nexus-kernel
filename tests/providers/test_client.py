from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest

from cgkn.providers.client import ModelRoleConfig, OpenAICompatibleClient, parse_json_object


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]
CONFIG = ModelRoleConfig("agent", "qwen",model_id='fixture')


@pytest.fixture(autouse=True)
def explicit_legacy_profile(tmp_path, monkeypatch):
    profile = tmp_path / 'legacy.json'
    profile.write_text('{"mode":"legacy"}', encoding='utf-8')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE', str(profile))
    monkeypatch.delenv('CGKN_NETWORK_MODE', raising=False)
    monkeypatch.setenv('CGKN_PROVIDER_GATEWAY_ENABLED','1')
    monkeypatch.setenv('CGKN_PROVIDER_GATEWAY_TOKEN','synthetic-token')
    for key,value in {'BUDGET_LEDGER':str(tmp_path/'budget.json'),'MAX_API_CALLS':'4',
        'MAX_INPUT_TOKENS':'100000','MAX_OUTPUT_TOKENS':'10000','MAX_ESTIMATED_COST':'10',
        'INPUT_COST_PER_MILLION':'1','OUTPUT_COST_PER_MILLION':'1','CACHE_MODE':'off'}.items():
        monkeypatch.setenv('CGKN_PROVIDER_'+key,value)
    from tests.providers.authority_fixtures import authorized_transport
    with authorized_transport(tmp_path/'authority',calls=4):yield



@pytest.mark.negative
@pytest.mark.parametrize("role, model", [("other", "m"), ("agent", "")])
def test_model_role_config_rejects_invalid_identity(role, model) -> None:
    with pytest.raises(ValueError): ModelRoleConfig(role, model)


@pytest.mark.negative
@pytest.mark.parametrize(
    "changes, message",
    [
        ({"timeout_seconds": 0}, "timeout"),
        ({"max_output_tokens": 0}, "output limit"),
        ({"temperature": 3.0}, "temperature"),
    ],
)
def test_model_role_config_rejects_invalid_limits(changes, message) -> None:
    with pytest.raises(ValueError, match=message):
        ModelRoleConfig("agent", "model", **changes)


@pytest.mark.roundtrip
def test_parse_json_object_plain_and_fenced() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.negative
@pytest.mark.parametrize("text, exception", [("[]", ValueError), ("not-json", ValueError)])
def test_parse_json_object_rejects_non_object_and_malformed(text, exception) -> None:
    with pytest.raises(exception): parse_json_object(text)


@pytest.fixture
def transport(monkeypatch):
    state={'text':'{"ok":true}','usage':{'input_tokens':2,'output_tokens':1,'total_tokens':3},'requests':[]}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(payload)
            from tests.providers.stream_fixtures import send_gateway
            send_gateway(self,payload,{'id':'req','model':'fixture','status':'completed',
                'output_text':state['text'],'usage':state['usage']})
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('CGKN_PROVIDER_GATEWAY_BASE_URL',f'http://127.0.0.1:{server.server_port}/v1')
    try:yield state
    finally:server.shutdown();server.server_close();thread.join(2)


@pytest.mark.negative
def test_complete_rejects_missing_credentials(monkeypatch) -> None:
    for credentials in ({"api_key": "", "base_url": "x"}, {"api_key": "x", "base_url": ""}):
        monkeypatch.setenv('CGKN_PROVIDER_GATEWAY_TOKEN',credentials['api_key'])
        monkeypatch.setenv('CGKN_PROVIDER_GATEWAY_BASE_URL',credentials['base_url'])
        with pytest.raises(RuntimeError, match="unavailable"):
            OpenAICompatibleClient().complete(system="s", user="u", schema_name="x", schema={}, config=CONFIG)


@pytest.mark.fault_injection
@pytest.mark.security
def test_transport_failure_is_redacted(monkeypatch,transport) -> None:
    def fail(*args,**kwargs):raise OSError('contains synthetic-token')
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',fail)
    with pytest.raises(RuntimeError, match="REDACTED") as failure:
        OpenAICompatibleClient().complete(system="s", user="u", schema_name="x", schema={}, config=CONFIG)
    assert 'synthetic-token' not in str(failure.value) and not transport['requests']


@pytest.mark.negative
def test_empty_provider_response_is_rejected(transport) -> None:
    transport['text']=''
    with pytest.raises(RuntimeError, match="empty"):
        OpenAICompatibleClient().complete(system="s", user="u", schema_name="x", schema={}, config=CONFIG)


@pytest.mark.roundtrip
@pytest.mark.boundary
@pytest.mark.happy_path
def test_success_builds_strict_schema_payload_and_normalizes_usage(transport) -> None:
    result = OpenAICompatibleClient().complete(system="s", user="u", schema_name="shape", schema={"type": "object"}, config=CONFIG)
    assert result.text == '{"ok":true}' and result.model == "fixture" and result.request_id == "req"
    assert result.usage == {'input_tokens':2,'output_tokens':1,'total_tokens':3,
                            'prompt_tokens':2,'completion_tokens':1} and result.attempts == 1
    assert transport['requests'][0]['text']['format']['strict'] is True
    transport['usage']=[]
    with pytest.raises(RuntimeError,match='usage'):
        OpenAICompatibleClient().complete(system="s", user="different", schema_name="shape", schema={}, config=CONFIG)
    assert len(transport['requests'])==2


@pytest.mark.boundary
@pytest.mark.negative
def test_compatibility_cannot_bypass_host_permit(transport):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(OpenAICompatibleClient().complete,system='s',user='u',
            schema_name='shape',schema={'type':'object'},config=CONFIG)
        with pytest.raises(ValueError,match='PERMIT_REQUIRED'):future.result()
    assert not transport['requests']
