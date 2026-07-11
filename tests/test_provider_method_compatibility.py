from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_connectivity, provider_transport
from scripts.agent_leaf_provider_guard import call_responses_provider, classify_provider_error


def test_gptsapi_gpt54nano_uses_responses_method() -> None:
    root = "https://api.gptsapi.net/v1"

    assert provider_transport.select_provider_api_method(root, "gpt-5.4-nano") == "responses"
    assert check_connectivity._openai_compatible_endpoint(root, model="gpt-5.4-nano") == "https://api.gptsapi.net/v1/responses"


def test_gptsapi_non_gpt5_model_keeps_chat_compatibility() -> None:
    root = "https://api.gptsapi.net/v1"

    assert provider_transport.select_provider_api_method(root, "legacy-provider-model") == "chat_completions"
    assert check_connectivity._openai_compatible_endpoint(root, model="legacy-provider-model") == "https://api.gptsapi.net/v1/chat/completions"


def test_non_gptsapi_explicit_responses_override_is_allowed() -> None:
    root = "https://provider.example/v1"

    assert provider_transport.select_provider_api_method(root, "gpt-5.4-nano", "responses") == "responses"
    assert check_connectivity._openai_compatible_endpoint(root, model="gpt-5.4-nano", requested_method="responses") == "https://provider.example/v1/responses"


def test_leaf_generation_uses_same_method_selection_as_readiness(monkeypatch) -> None:
    calls: list[str] = []

    def fake_post(endpoint, payload, token, timeout):
        calls.append(endpoint)
        assert payload["model"] == "gpt-5.4-nano"
        assert "input" in payload
        assert "messages" not in payload
        return {"output_text": "pong"}, ""

    monkeypatch.setattr("scripts.agent_leaf_provider_guard.check_connectivity._post_json", fake_post)

    doc, error, attempts = call_responses_provider(
        base_url="https://api.gptsapi.net/v1",
        token="test-token-not-real",
        payload={"model": "gpt-5.4-nano", "input": "ping", "max_tokens": 20},
        timeout=10,
    )

    assert doc == {"output_text": "pong"}
    assert error == ""
    assert attempts == 1
    assert calls == ["https://api.gptsapi.net/v1/responses"]


def test_method_unsupported_is_blocked_not_fake_success() -> None:
    error = 'HTTP 400: {"error":"model does not support this API (call_methods must include responses)"} [retryable=false]'

    assert check_connectivity._provider_error_type(error) == "PROVIDER_METHOD_UNSUPPORTED"
    result = classify_provider_error(error)
    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"
    assert result["not_proven"] is True
    assert result["fake_success"] is False


def test_provider_errors_are_redacted() -> None:
    fake_secret = "sk-" + "t" * 48
    error = f"HTTP 400: {fake_secret} does not support this API"

    result = classify_provider_error(error)

    assert fake_secret not in result["public_safe_error"]
    assert "<redacted>" in result["public_safe_error"]
