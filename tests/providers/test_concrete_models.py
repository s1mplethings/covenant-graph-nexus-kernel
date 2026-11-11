import json
import threading
from contextvars import copy_context
from tests.providers.authority_fixtures import authorized_transport
from concurrent.futures import ThreadPoolExecutor

import httpx

from cgkn.providers.client import ModelRoleConfig
from cgkn.providers.domestic_gateway import DomesticGateway
from cgkn.providers.gateway_client import GatewayCompletionClient
from cgkn.providers.network_transport import NetworkClients, Route


def test_same_provider_models_reach_distinct_overlapping_payloads(tmp_path, monkeypatch):
    profile = tmp_path / 'offline.json'
    profile.write_text('{"mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE', str(profile))
    barrier = threading.Barrier(2, timeout=4)
    payloads = []
    events = []

    def upstream(request):
        # MockTransport does not emit httpcore submission events by itself.
        # Preserve the production watchdog's submission-before-progress contract.
        request.extensions['trace']('http11.send_request_headers.started', {'request': request})
        value = json.loads(request.content)
        payloads.append(value)
        barrier.wait()
        from tests.providers.stream_fixtures import upstream_wire
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},content=upstream_wire(value['model'],json.dumps({'model':value['model']})))


    network = NetworkClients({'r': Route(route_id='r', proxy_url=None, deadline=8)},
        {'qwen': 'r'}, version='OFFLINE_CONFORMANCE', provider_parallelism=2,
        transports={'r': httpx.MockTransport(upstream)}, log=events.append)

    class Secrets:
        def resolve(self, provider):
            return 'synthetic-only'

    gateway = DomesticGateway('D:/cgkn-provider-api-lab', None, network=network,
        secret_manager=Secrets(), provider_parallelism=2)
    gateway.available_models['qwen'] = {'synthetic-m1', 'synthetic-m2'}
    info = gateway.start()
    client = GatewayCompletionClient(info.base_url, info.access_token, enforce_budget=False)
    try:
        with authorized_transport(tmp_path/'authority',calls=2), ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run,client.complete, system='test', user=model,
                schema_name='raw', schema=None, config=ModelRoleConfig('worker', 'qwen',
                    timeout_seconds=10, model_id=model)) for model in ('synthetic-m1', 'synthetic-m2')]
            try:
                responses = [f.result() for f in futures]
            except Exception:
                print(json.dumps(events, default=str))
                raise
        assert {p['model'] for p in payloads} == {'synthetic-m1', 'synthetic-m2'}
        assert {r.model for r in responses} == {'synthetic-m1', 'synthetic-m2'}
        assert all(json.loads(r.text)['model'] == r.model for r in responses)
    finally:
        gateway.close()
