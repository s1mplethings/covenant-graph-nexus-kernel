from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import pathlib
import threading
from typing import Any

import pytest

from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, GatewayCompletionError, ModelRoleConfig
from cgkn.providers.gateway_client import _safe_gateway_error, completion_client_from_environment
from scripts import provider_api_budget


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path,monkeypatch):
    profile=tmp_path/'legacy.json';profile.write_text('{"kind":"CGKNApplicationNetwork","mode":"legacy"}')
    monkeypatch.setenv('CGKN_APPLICATION_PROFILE',str(profile))
    monkeypatch.setenv('CGKN_PROVIDER_CACHE_MODE','off')
    import socket
    connect=socket.socket.connect
    def local(sock,address):
        assert address[0] in ('127.0.0.1','::1','localhost'),'Unit test must not use a production route'
        return connect(sock,address)
    monkeypatch.setattr(socket.socket,'connect',local)
    from tests.providers.authority_fixtures import authorized_transport
    with authorized_transport(tmp_path/'authority'):
        yield


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok"],
    "properties": {"ok": {"type": "boolean"}},
}


class Handler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    response: dict[str, Any] = {"ok": True}
    status = 200
    error_type = "gateway_error"
    completion_status = "completed"

    def log_message(self, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "payload": payload})
        if self.status != 200:
            body = {"error": {"type": self.error_type, "message": "rejected"}}
        else:
            body = {
                "id": "gateway-request",
                "object": "response",
                "status": self.completion_status,
                "model": payload.get("cgkn_model_id") or payload["model"],
                "output_text": json.dumps(self.response),
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            }
        if self.status==200:
            from tests.providers.stream_fixtures import send_gateway
            return send_gateway(self,payload,body)
        encoded = json.dumps(body).encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


@pytest.fixture
def gateway():
    Handler.requests = []
    Handler.response = {"ok": True}
    Handler.status = 200
    Handler.error_type = "gateway_error"
    Handler.completion_status = "completed"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def client(server: ThreadingHTTPServer, token: str = "temporary-local-token", *, enforce_budget: bool = False) -> GatewayCompletionClient:
    return GatewayCompletionClient(f"http://127.0.0.1:{server.server_port}/v1", token, enforce_budget=enforce_budget).bind_run("run-1", "case-1")


def test_responses_preserve_roles_schema_usage_and_provider_alias(gateway) -> None:
    completion = client(gateway).complete(
        system="system-boundary",
        user="user-boundary",
        schema_name="bounded_result",
        schema=SCHEMA,
        config=ModelRoleConfig("agent", "qwen", max_output_tokens=100),
    )
    sent = Handler.requests[0]
    assert sent["path"] == "/v1/responses"
    assert sent["authorization"] == "Bearer temporary-local-token"
    assert sent["payload"]["input"] == [{"role": "system", "content": "system-boundary"}, {"role": "user", "content": "user-boundary"}]
    assert sent["payload"]["text"]["format"]["schema"] == SCHEMA
    assert sent["payload"]["model"] == "qwen"
    assert completion.model == "qwen" and completion.usage["total_tokens"] == 18


def test_chat_completions_compatibility_path_preserves_schema(gateway) -> None:
    Handler.response = {"ok": True}
    gateway_client = GatewayCompletionClient(f"http://127.0.0.1:{gateway.server_port}/v1", "temporary-local-token", "chat_completions", enforce_budget=False)
    original = Handler.do_POST

    def chat_response(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        type(self).requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "payload": payload})
        body = json.dumps({"id": "chat-request", "model": payload["model"], "choices": [{"message": {"content": json.dumps({"ok": True})}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}}).encode()
        from tests.providers.stream_fixtures import send_gateway
        send_gateway(self,payload,json.loads(body))

    Handler.do_POST = chat_response
    try:
        completion = gateway_client.complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen"))
    finally:
        Handler.do_POST = original
    assert Handler.requests[-1]["path"] == "/v1/chat/completions"
    assert Handler.requests[-1]["payload"]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert completion.usage["total_tokens"] == 4


@pytest.mark.parametrize("provider", ["qwen", "deepseek", "grok"])
def test_all_supported_provider_routes_are_explicit(gateway, provider: str) -> None:
    client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("worker", provider))
    assert Handler.requests[-1]["payload"]["model"] == provider


@pytest.mark.parametrize("api_method", ["responses", "chat_completions"])
@pytest.mark.parametrize("protocol", ["cgkn_semantic_v1", "unstructured_text"])
def test_semantic_object_transport_preserves_unstructured_requests(gateway, monkeypatch, api_method, protocol):
    """Inspect actual loopback wire requests, without any production dispatch."""
    def complete_response(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.requests.append({"path": self.path, "payload": payload})
        text = '{"op":0,"path":1}'
        body = {"id":"local-semantic", "model":payload["model"], "status":"completed",
                "output_text":text,
                "choices":[{"message":{"content":text},"finish_reason":"stop"}],
                "usage":{"input_tokens":1,"output_tokens":1,"total_tokens":2}}
        from tests.providers.stream_fixtures import send_gateway
        send_gateway(self,payload,body)
    monkeypatch.setattr(Handler,"do_POST",complete_response)
    gateway_client=GatewayCompletionClient(f"http://127.0.0.1:{gateway.server_port}/v1",
        "local-test-token",api_method,enforce_budget=False)
    result=gateway_client.complete(system="Return one JSON object",user="Read path 1",
        schema_name=protocol,schema=None,config=ModelRoleConfig("worker","qwen"))
    assert result.text == '{"op":0,"path":1}'
    payload=Handler.requests[-1]["payload"]
    # Exercise the installed gateway's real admission parser, not just a
    # permissive HTTP fixture. It only admits JSON Schema envelopes.
    monkeypatch.syspath_prepend("D:/cgkn-provider-api-lab/src")
    from cgkn_provider_lab.gateway import _options
    options=_options(payload,"Return one JSON object")
    if protocol == "cgkn_semantic_v1":
        format_value=payload.get("response_format") or payload["text"]["format"]
        envelope=format_value.get("json_schema",format_value)
        assert format_value["type"] == "json_schema"
        assert envelope["schema"] == {"type":"object"}
        assert envelope["strict"] is False
        assert options.response_format["json_schema"]["schema"] == {"type":"object"}
        from jsonschema import Draft202012Validator
        validator=Draft202012Validator(envelope["schema"])
        assert not list(validator.iter_errors({"op":0,"path":1}))
        assert list(validator.iter_errors([{"op":0,"path":1}]))
        assert list(validator.iter_errors("explanation then JSON"))
    else:
        assert "response_format" not in payload and "text" not in payload
        assert not options.response_format


@pytest.mark.negative
@pytest.mark.security
def test_invalid_schema_output_auth_error_and_no_secret_leak(gateway) -> None:
    Handler.response = {"wrong": True}
    with pytest.raises(GatewayCompletionError, match="schema_validation_failed"):
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen"))
    Handler.status = 401
    Handler.error_type = "authentication_error"
    token = "do-not-render-this-token"
    with pytest.raises(GatewayCompletionError) as caught:
        client(gateway, token).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen"))
    assert caught.value.category == "authentication_error"
    assert token not in str(caught.value) and token not in repr(client(gateway, token))


@pytest.mark.fault_injection
def test_rate_limit_and_truncation_propagate_without_fallback(gateway) -> None:
    Handler.status = 429
    Handler.error_type = "provider_rate_limited"
    with pytest.raises(GatewayCompletionError) as limited:
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("worker", "deepseek"))
    assert limited.value.category == "provider_rate_limited"
    assert len(Handler.requests) == 1 and Handler.requests[0]["payload"]["model"] == "deepseek"
    Handler.status = 200
    Handler.completion_status = "incomplete"
    with pytest.raises(GatewayCompletionError) as truncated:
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "grok"))
    assert truncated.value.category == "truncated_response"


@pytest.mark.fault_injection
def test_timeout_after_send_is_outcome_unknown_and_not_retried(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def timeout(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise TimeoutError("timed out")

    monkeypatch.setattr("cgkn.providers.gateway_client._open_loopback", timeout)
    with pytest.raises(GatewayCompletionError) as caught:
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen"))
    assert caught.value.category == "outcome_unknown" and caught.value.outcome_unknown is True
    assert calls == 1


@pytest.mark.negative
@pytest.mark.security
def test_invalid_model_remote_address_and_stopped_gateway_fail_closed(gateway) -> None:
    with pytest.raises(GatewayCompletionError, match="invalid_model"):
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "other"))
    with pytest.raises(ValueError, match="loopback"):
        GatewayCompletionClient("https://example.com/v1", "token", enforce_budget=False)
    port = gateway.server_port
    gateway.shutdown()
    gateway.server_close()
    with pytest.raises(GatewayCompletionError) as caught:
        GatewayCompletionClient(f"http://127.0.0.1:{port}/v1", "token", enforce_budget=False).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen", timeout_seconds=1))
    assert caught.value.category in {"outcome_unknown", "gateway_unavailable"}


@pytest.mark.negative
@pytest.mark.parametrize(
    "base_url, token, method, message",
    [
        ("http://127.0.0.1:8123/admin", "token", "responses", "path"),
        ("http://127.0.0.1:8123/v1", "", "responses", "token"),
        ("http://127.0.0.1:8123/v1", "token", "other", "method"),
    ],
)
def test_gateway_constructor_rejects_unsafe_settings(base_url, token, method, message) -> None:
    with pytest.raises(ValueError, match=message):
        GatewayCompletionClient(base_url, token, method, enforce_budget=False)


@pytest.mark.negative
@pytest.mark.security
def test_safe_error_and_environment_factory_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _safe_gateway_error({"error": "not-an-object"}, "secret", "fallback") == ("gateway_error", "fallback")
    monkeypatch.delenv("CGKN_PROVIDER_GATEWAY_ENABLED", raising=False)
    with pytest.raises(RuntimeError,match='GOVERNED_GATEWAY_REQUIRED'):
        completion_client_from_environment()
    monkeypatch.setenv("CGKN_PROVIDER_GATEWAY_ENABLED", "yes")
    monkeypatch.setenv("CGKN_PROVIDER_GATEWAY_BASE_URL", "http://127.0.0.1:8123/v1")
    monkeypatch.setenv("CGKN_PROVIDER_GATEWAY_TOKEN", "temporary-token")
    assert isinstance(completion_client_from_environment(), GatewayCompletionClient)


@pytest.mark.negative
def test_reasoning_request_size_and_response_shapes_are_bounded(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cgkn.providers.gateway_client.MAX_REQUEST_BYTES", 1)
    with pytest.raises(GatewayCompletionError) as oversized:
        client(gateway).complete(
            system="s", user="u", schema_name="x", schema=SCHEMA,
            config=ModelRoleConfig("agent", "qwen", reasoning_effort="high"),
        )
    assert oversized.value.category == "request_too_large"

    import io
    from tests.providers.stream_fixtures import gateway_wire
    class Response(io.BytesIO):
        status=200
        headers={'Content-Type':'text/event-stream'}
    monkeypatch.setattr('cgkn.providers.gateway_client.MAX_REQUEST_BYTES',1_048_576)
    def serve(doc):
        return lambda req,**kwargs:Response(gateway_wire(json.loads(req.data),doc))
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',serve([]))
    with pytest.raises(GatewayCompletionError,match='gateway_stream_invalid_terminal'):
        client(gateway).complete(system='s',user='u',schema_name='x',schema=SCHEMA,config=ModelRoleConfig('agent','qwen'))
    monkeypatch.setattr('cgkn.providers.gateway_client._open_loopback',serve(dict(id='x',model='qwen',status='completed',output_text='',usage={'input_tokens':1,'output_tokens':1})))
    with pytest.raises(GatewayCompletionError,match='empty_response'):
        client(gateway).complete(system='s',user='u',schema_name='x',schema=SCHEMA,config=ModelRoleConfig('agent','qwen'))


@pytest.mark.negative
def test_chat_extraction_rejects_invalid_and_truncated_choices(gateway) -> None:
    gateway_client = GatewayCompletionClient(f"http://127.0.0.1:{gateway.server_port}/v1", "token", "chat_completions", enforce_budget=False)
    assert gateway_client._extract_text({"choices": []}) == ""
    assert gateway_client._extract_text({"choices": [{"message": "invalid"}]}) == ""
    with pytest.raises(GatewayCompletionError, match="truncated_response"):
        gateway_client._extract_text({"choices": [{"finish_reason": "length", "message": {"content": "x"}}]})


@pytest.mark.negative
def test_budget_reservation_blocks_before_second_send(gateway, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "budget.json"
    values = {
        "CGKN_PROVIDER_BUDGET_LEDGER": str(ledger),
        "CGKN_PROVIDER_MAX_API_CALLS": "1",
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": "10000",
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": "10000",
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "1",
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": "1",
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": "1",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    bounded = client(gateway, enforce_budget=True)
    bounded.complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen", max_output_tokens=10))
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted):
        bounded.complete(system="s2", user="u2", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("worker", "deepseek", max_output_tokens=10))
    assert len(Handler.requests) == 1
    doc = json.loads(ledger.read_text(encoding="utf-8"))
    assert doc["calls"][0]["run_id"] == "run-1"
    assert doc["calls"][0]["provider"] == "qwen"


@pytest.mark.negative
def test_paid_gateway_mode_requires_complete_budget_before_send(gateway,monkeypatch) -> None:
    for key in ('CGKN_PROVIDER_INPUT_COST_PER_MILLION','CGKN_PROVIDER_OUTPUT_COST_PER_MILLION'):
        monkeypatch.delenv(key,raising=False)
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted, match="operator-supplied price estimates"):
        GatewayCompletionClient(f"http://127.0.0.1:{gateway.server_port}/v1", "token").complete(
            system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen")
        )
    assert Handler.requests == []


@pytest.mark.roundtrip
@pytest.mark.security
def test_routing_switch_grok_and_snapshot_are_immutable(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({
        "kind": "CGKNModelRouting", "schema_version": "1.0",
        "roles": {"agent": {"provider_id": "deepseek"}, "worker": {"provider_id": "grok"}},
        "allowed_providers": ["qwen", "deepseek", "grok"], "fallback": "deny",
    }), encoding="utf-8")
    routing = CGKNModelRouting.load(path)
    snapshot = routing.snapshot("fixed-run")
    assert snapshot.roles == {"agent": "deepseek", "worker": "grok"}
    with pytest.raises(TypeError):
        snapshot.roles["agent"] = "qwen"  # type: ignore[index]
    target = snapshot.write_once(tmp_path / "snapshot.json")
    with pytest.raises(FileExistsError):
        snapshot.write_once(target)
    text = target.read_text(encoding="utf-8").lower()
    assert "access_token" not in text and "authorization" not in text and "temporary-local-token" not in text


@pytest.mark.negative
@pytest.mark.security
def test_fallback_configuration_is_rejected(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({
        "kind": "CGKNModelRouting", "schema_version": "1.0",
        "roles": {"agent": {"provider_id": "qwen"}, "worker": {"provider_id": "deepseek"}},
        "allowed_providers": ["qwen", "deepseek", "grok"], "fallback": "allow",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="fallback"):
        CGKNModelRouting.load(path)


@pytest.mark.negative
@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda doc: doc.update(kind="wrong"), "unsupported"),
        (lambda doc: doc.update(extra=True), "unknown or missing"),
        (lambda doc: doc.update(roles={"agent": {"provider_id": "qwen"}}), "exactly"),
        (lambda doc: doc.update(allowed_providers=[]), "unsupported Provider"),
        (lambda doc: doc["roles"]["agent"].update(extra=True), "routing fields"),
        (lambda doc: doc["roles"]["agent"].update(provider_id="grok"), "not allowed"),
    ],
)
def test_routing_rejects_malformed_documents(tmp_path: pathlib.Path, mutation, message) -> None:
    doc = {
        "kind": "CGKNModelRouting", "schema_version": "1.0",
        "roles": {"agent": {"provider_id": "qwen"}, "worker": {"provider_id": "deepseek"}},
        "allowed_providers": ["qwen", "deepseek"], "fallback": "deny",
    }
    mutation(doc)
    path = tmp_path / "routing-invalid.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        CGKNModelRouting.load(path)


def test_final_wire_preflight_rejects_without_reservation_or_http(gateway,monkeypatch):
    from dataclasses import replace
    def forbidden(**kwargs):raise AssertionError('must not reserve an unsendable request')
    monkeypatch.setattr(provider_api_budget,'reserve_call',forbidden)
    bounded=replace(client(gateway),input_token_ceiling=64000)
    from veriarbor.governance import LegacyPolicy,legacy_scope
    with legacy_scope(LegacyPolicy(True,('wire-fixture',)),caller='wire-fixture',reason='Offline loopback serializer test',event_sink=lambda e:None), pytest.raises(GatewayCompletionError) as caught:
        bounded.complete(execution_mode='LEGACY',system='system',user='x'*65000,schema_name='bounded_result',schema=SCHEMA,config=ModelRoleConfig('agent','qwen',model_id='qwen3.8-flash'))
    assert caught.value.category=='provider_request_rejected_before_send'
    assert caught.value.provider_dispatched is False
    assert not Handler.requests


def test_preflight_does_not_shadow_http_error_module(gateway,monkeypatch):
    from dataclasses import replace
    from veriarbor.governance import LegacyPolicy,legacy_scope
    bounded=replace(client(gateway),input_token_ceiling=64000)
    from urllib.error import HTTPError
    from io import BytesIO
    from cgkn.execution import node_effects
    def reject(*args,**kwargs):raise HTTPError('http://127.0.0.1',401,'fixture',{},BytesIO(b'{"error":{"type":"authentication_error","message":"fixture"}}'))
    monkeypatch.setattr(node_effects,'governed_provider_open',reject)
    with legacy_scope(LegacyPolicy(True,('wire-fixture',)),caller='wire-fixture',reason='Offline HTTP exception regression',event_sink=lambda e:None), pytest.raises(GatewayCompletionError) as caught:
        bounded.complete(execution_mode='LEGACY',system='s',user='u',schema_name='test',schema=SCHEMA,config=ModelRoleConfig('agent','qwen',model_id='qwen3.8-flash'))
    assert caught.value.category=='authentication_error'


def test_input_ceiling_is_not_reserved_again_as_the_entire_campaign(gateway,tmp_path,monkeypatch):
    from dataclasses import replace
    ledger=tmp_path/'budget.json'
    for key,value in {'BUDGET_LEDGER':str(ledger),'MAX_API_CALLS':'3','MAX_INPUT_TOKENS':'1000000',
        'MAX_OUTPUT_TOKENS':'10000','MAX_ESTIMATED_COST':'20','INPUT_COST_PER_MILLION':'2','OUTPUT_COST_PER_MILLION':'8'}.items():
        monkeypatch.setenv('CGKN_PROVIDER_'+key,value)
    bounded=replace(client(gateway,enforce_budget=True),input_token_ceiling=1000000)
    config=ModelRoleConfig('agent','qwen',model_id='qwen3.7-flash',max_output_tokens=10)
    for prompt in ('first request','next request with fetched public input'):
        bounded.complete(system='s',user=prompt,schema_name='x',schema=SCHEMA,config=config)
    doc=json.loads(ledger.read_text(encoding='utf-8'))
    assert len(Handler.requests)==2
    assert all(0<row['reserved_input_tokens']<1000000 for row in doc['calls'])
    assert doc['totals']['api_calls']==2 and doc['totals']['unknown_calls']==0


def test_permit_budget_rejection_is_known_before_send_not_invalid_response(gateway,tmp_path,monkeypatch):
    from cgkn.execution import node_effects
    ledger=tmp_path/'budget.json'
    for key,value in {'BUDGET_LEDGER':str(ledger),'MAX_API_CALLS':'3','MAX_INPUT_TOKENS':'100000',
        'MAX_OUTPUT_TOKENS':'10000','MAX_ESTIMATED_COST':'20','INPUT_COST_PER_MILLION':'2','OUTPUT_COST_PER_MILLION':'8'}.items():
        monkeypatch.setenv('CGKN_PROVIDER_'+key,value)
    def denied(*args):raise ValueError('BUDGET_SCOPE_REJECT: requested=2 allowed=1')
    monkeypatch.setattr(node_effects,'guard_provider_transport',denied)
    with pytest.raises(GatewayCompletionError) as caught:
        client(gateway,enforce_budget=True).complete(system='s',user='u',schema_name='x',schema=SCHEMA,
            config=ModelRoleConfig('agent','qwen',model_id='offline',max_output_tokens=10))
    assert caught.value.category=='provider_request_rejected_before_send'
    assert caught.value.provider_dispatched is False and caught.value.outcome_unknown is False
    assert 'requested=2 allowed=1' in str(caught.value)
    assert not Handler.requests
    doc=json.loads(ledger.read_text())
    assert doc['totals']['api_calls']==0 and doc['totals']['unknown_calls']==0
    assert doc['calls'][0]['status']=='CANCELLED_BEFORE_SEND'
