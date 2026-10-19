from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import pathlib
import threading
from typing import Any

import pytest

from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, GatewayCompletionError, ModelRoleConfig, OpenAICompatibleClient
from cgkn.providers.gateway_client import _safe_gateway_error, completion_client_from_environment
from scripts import provider_api_budget


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


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
    response_text: str | None = None

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
                "model": payload["model"],
                "output_text": self.response_text if self.response_text is not None else json.dumps(self.response),
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            }
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
    Handler.response_text = None
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
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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


@pytest.mark.negative
@pytest.mark.security
def test_invalid_schema_output_auth_error_and_no_secret_leak(gateway) -> None:
    Handler.response = {"wrong": True}
    with pytest.raises(GatewayCompletionError, match="PROVIDER_SCHEMA_FAILURE"):
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

    monkeypatch.setattr("cgkn.providers.gateway_client.request.urlopen", timeout)
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
    assert isinstance(completion_client_from_environment(), OpenAICompatibleClient)
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

    class Response:
        status = 200

        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit: int) -> bytes:
            return self.body

    monkeypatch.setattr("cgkn.providers.gateway_client.MAX_REQUEST_BYTES", 1_048_576)
    monkeypatch.setattr("cgkn.providers.gateway_client.request.urlopen", lambda *_args, **_kwargs: Response(b"[]"))
    with pytest.raises(GatewayCompletionError) as invalid_root:
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen"))
    assert invalid_root.value.category == "invalid_response"
    monkeypatch.setattr(
        "cgkn.providers.gateway_client.request.urlopen",
        lambda *_args, **_kwargs: Response(json.dumps({"status": "completed", "output_text": ""}).encode()),
    )
    with pytest.raises(GatewayCompletionError) as empty:
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "qwen"))
    assert empty.value.category == "empty_response"


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
def test_paid_gateway_mode_requires_complete_budget_before_send(gateway) -> None:
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


def test_benchmark_budget_purpose_is_explicit_and_bounded() -> None:
    bound = GatewayCompletionClient(
        "http://127.0.0.1:8123/v1", "temporary-local-token", enforce_budget=False
    ).bind_run("benchmark-run", "case-a", budget_purpose="BENCHMARK")
    assert bound.run_id == "benchmark-run"
    assert bound.case_id == "case-a"
    assert bound.budget_purpose == "BENCHMARK"
    with pytest.raises(ValueError, match="budget purpose"):
        bound.bind_run("benchmark-run", "case-b", budget_purpose="FALLBACK")


def test_gateway_selects_unique_schema_valid_object_and_returns_receipt(gateway) -> None:
    Handler.response_text = '{"type":"object","properties":{"ok":{"type":"boolean"}}}\n{"ok":true}'
    completion = client(gateway).complete(
        system="s", user="u", schema_name="x", schema=SCHEMA,
        config=ModelRoleConfig("agent", "deepseek", task_class="project.compose", operation="COMPOSITION"),
    )
    assert json.loads(completion.text) == {"ok": True}
    assert completion.selection_receipt["json_candidate_count"] == 2
    assert completion.selection_receipt["schema_valid_candidate_count"] == 1
    assert completion.selection_receipt["final_status"] == "ACCEPTED"


def test_gateway_rejects_two_schema_valid_objects_with_receipt(gateway) -> None:
    Handler.response_text = '{"ok":true}\n{"ok":false}'
    with pytest.raises(GatewayCompletionError) as caught:
        client(gateway).complete(system="s", user="u", schema_name="x", schema=SCHEMA, config=ModelRoleConfig("agent", "deepseek"))
    assert caught.value.category == "PROVIDER_AMBIGUOUS_STRUCTURED_OUTPUT"
    assert caught.value.evidence["schema_valid_candidate_count"] == 2


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
