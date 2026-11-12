"""Real Host Permit + HTTP + ledger for bounded public context acquisition."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cgkn.protocol.adaptive_context import ContextPacker, public_context_view
from cgkn.protocol.exchange import complete_with_context
from cgkn.providers import GatewayCompletionClient, ModelRoleConfig
from scripts.provider_api_budget import ProviderBudgetExhausted
from tests.providers.authority_fixtures import authorized_transport
from tests.providers.stream_fixtures import send_gateway


@pytest.mark.boundary
@pytest.mark.parametrize('role', ['agent', 'worker'])
@pytest.mark.parametrize('call_limit', [1, 2])
def test_context_fetch_uses_same_permit_and_budget_without_retry(tmp_path, monkeypatch, role, call_limit):
    profile = tmp_path/'network.json'
    profile.write_text('{"mode":"legacy"}')  # Isolated route selection, not execution mode.
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE', str(profile))
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE', 'off')
    for key, value in {'BUDGET_LEDGER': str(tmp_path/'ledger.json'), 'MAX_API_CALLS': call_limit,
                      'MAX_INPUT_TOKENS': 100000, 'MAX_OUTPUT_TOKENS': 1000, 'MAX_ESTIMATED_COST': 1,
                      'INPUT_COST_PER_MILLION': 1, 'OUTPUT_COST_PER_MILLION': 1}.items():
        monkeypatch.setenv('CGKN_PROVIDER_'+key, str(value))
    original = {'goal': 'Inspect the complete public result', 'failure_details': {'reason': 'wrong value'},
                'execution_results': {'n': {'status': 'FAILED', 'outputs': {'rows': ['public']*1000}}}}
    view, resolver = public_context_view(original)
    requests = []
    failures = []
    schema = {'type': 'object', 'properties': {'ok': {'const': True}},
              'required': ['ok'], 'additionalProperties': False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            try:
                assert self.headers['Authorization'] == 'Bearer dummy-loopback-context'
                prompt = ContextPacker.restore(json.loads(payload['input'][1]['content']))
                assert prompt['goal'] == original['goal']
                assert prompt['failure_details'] == original['failure_details']
                advertised=payload['text']['format']['schema']
                assert (advertised['anyOf'][0] if len(requests)==1 else advertised) == schema
                if len(requests) == 1:
                    result = {'context_operation': 'fetch_dependency_result',
                              'ref': view['execution_results']['n']['result_ref'], 'reason': 'inspect all rows'}
                else:
                    assert next(iter(prompt['fetched_context'].values()))['value'] == original['execution_results']['n']
                    result = {'ok': True}
                send_gateway(self, payload, {'id': 'wire-'+str(len(requests)), 'model': 'local-qwen',
                    'status': 'completed', 'output_text': json.dumps(result),
                    'usage': {'input_tokens': 4, 'output_tokens': 3}})
            except Exception as exc:
                failures.append(exc)
                self.send_error(500)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = GatewayCompletionClient(f'http://127.0.0.1:{server.server_port}/v1',
            'dummy-loopback-context', run_id='offline', case_id=role,
            authorization_reference='ISOLATED_LOOPBACK_ONLY')
        args = dict(resolver=resolver, system='Inspect the public evidence.', user=json.dumps(view),
                    schema_name='business', schema=schema,
                    config=ModelRoleConfig(role, 'qwen', model_id='local-qwen', max_output_tokens=100))
        with authorized_transport(tmp_path/'authority', calls=2) as (authority, permit):
            if call_limit == 1:
                with pytest.raises(ProviderBudgetExhausted):
                    complete_with_context(client, **args)
            else:
                result = complete_with_context(client, **args)
                assert json.loads(result.text) == {'ok': True}
                assert result.usage == {'input_tokens': 8, 'output_tokens': 6,
                                        'prompt_tokens': 8, 'completion_tokens': 6}
                assert result.attempts == 2
            assert authority.validate_permit(permit.permit_id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not failures
    assert len(requests) == call_limit
    ledger = json.loads((tmp_path/'ledger.json').read_text())
    assert len(ledger['calls']) == call_limit
    assert all(row['status'] == 'SUCCEEDED' for row in ledger['calls'])
