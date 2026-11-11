import json
import pytest
from cgkn.providers import ModelRoleConfig
from cgkn.protocol.adaptive_context import ContextPacker
from tests.providers.test_gateway_client import Handler, gateway, client, isolated_profile


@pytest.mark.parametrize('role', ['agent', 'worker'])
def test_default_gateway_packs_without_semantic_protocol(gateway, role):
    evidence = {'requirement': 'Preserve exact input identifiers and values. ' * 160,
                'source_sha256': 'a' * 64, 'negative_evidence': 'Do not invent attribution'}
    prompt = {'goal': 'Summarize a local record', 'first': evidence, 'second': evidence}
    result = client(gateway).complete(system='Return the requested schema.', user=json.dumps(prompt),
        schema_name='business_protocol', schema={'type': 'object'},
        config=ModelRoleConfig(role, 'qwen', max_output_tokens=100))
    sent = Handler.requests[-1]['payload']['input']
    packed = json.loads(sent[1]['content'])
    assert len(sent[1]['content']) < len(json.dumps(prompt))
    assert ContextPacker.restore(packed) == prompt
    receipt = result.routing['request_packing']
    assert receipt['envelope']['role'] == role
    assert receipt['envelope']['output_reserve'] == 100
    assert receipt['critical_context_preserved'] is True
    assert receipt['envelope']['policy_hash']
    assert receipt['provider_dispatched'] is True


def test_concrete_model_always_checks_final_wire(gateway):
    result = client(gateway).complete(system='s', user='u', schema_name='business',
        schema={'type': 'object'}, config=ModelRoleConfig('worker','deepseek',model_id='deepseek-flash'))
    wire = result.routing['request_packing']['final_wire']
    assert wire['request_bytes'] > 0
    assert wire['unit'] == 'bytes'
    assert wire['within_ceiling']
    assert wire['limit_source'].endswith('MAX_REQUEST_BYTES')


def test_no_permit_still_denies_before_transport(tmp_path):
    from cgkn.providers import GatewayCompletionClient
    from concurrent.futures import ThreadPoolExecutor
    def invoke():
        return GatewayCompletionClient('http://127.0.0.1:1/v1', 'fixture', enforce_budget=False).complete(
            system='s', user='u', schema_name='x', schema={}, config=ModelRoleConfig('worker','qwen'))
    with pytest.raises(ValueError, match='PERMIT_REQUIRED'):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(invoke).result()


def test_cached_completion_retains_preparation_without_dispatch(gateway, tmp_path, monkeypatch):
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','read_write')
    monkeypatch.setenv('CGKN_PROVIDER_RESPONSE_CACHE_DIR',str(tmp_path/'cache'))
    request=dict(system='Return the schema.',user='Bounded local record',schema_name='record',
        schema={'type':'object'},config=ModelRoleConfig('worker','qwen',max_output_tokens=100))
    first=client(gateway).complete(**request)
    assert len(Handler.requests)==1
    second=client(gateway).complete(**request)
    assert len(Handler.requests)==1 and second.attempts==0
    assert second.text==first.text
    receipt=second.routing['request_packing']
    assert receipt['provider_dispatched'] is False
    assert receipt['response_source']=='identity_bound_cache'
    assert receipt['final_wire']==first.routing['request_packing']['final_wire']
