from __future__ import annotations

from types import SimpleNamespace

import pytest

from cgkn.providers.client import ModelRoleConfig, OpenAICompatibleClient, parse_json_object


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]
CONFIG = ModelRoleConfig("agent", "model")


@pytest.mark.negative
@pytest.mark.parametrize("role, model", [("other", "m"), ("agent", "")])
def test_model_role_config_rejects_invalid_identity(role, model) -> None:
    with pytest.raises(ValueError): ModelRoleConfig(role, model)


@pytest.mark.roundtrip
def test_parse_json_object_plain_and_fenced() -> None:
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.negative
@pytest.mark.parametrize("text, exception", [("[]", ValueError), ("not-json", ValueError)])
def test_parse_json_object_rejects_non_object_and_malformed(text, exception) -> None:
    with pytest.raises(exception): parse_json_object(text)


def configure(monkeypatch, *, credentials=None, transport=None, text='{"ok":true}'):
    monkeypatch.setattr("cgkn.providers.client.check_connectivity._resolve_api_credentials", lambda: credentials if credentials is not None else {"api_key": "token", "base_url": "https://provider.invalid/v1"})
    monkeypatch.setattr("cgkn.providers.client.check_connectivity._build_openai_compatible_payload", lambda base, payload, **kwargs: {"base": base, **payload, **kwargs})
    monkeypatch.setattr("cgkn.providers.client.check_connectivity._openai_compatible_endpoint", lambda base, **kwargs: base + "/chat")
    monkeypatch.setattr("cgkn.providers.client.check_connectivity._extract_text", lambda _doc: text)
    value = transport if transport is not None else SimpleNamespace(doc={"id": "req", "model": "actual", "usage": {"total_tokens": 3}}, error="", attempts=[1, 2])
    monkeypatch.setattr("cgkn.providers.client.provider_transport.post_json_with_retry", lambda *args, **kwargs: value)


@pytest.mark.negative
def test_complete_rejects_missing_credentials(monkeypatch) -> None:
    for credentials in ({"api_key": "", "base_url": "x"}, {"api_key": "x", "base_url": ""}):
        configure(monkeypatch, credentials=credentials)
        with pytest.raises(RuntimeError, match="unavailable"):
            OpenAICompatibleClient().complete(system="s", user="u", schema_name="x", schema={}, config=CONFIG)


@pytest.mark.fault_injection
@pytest.mark.security
def test_transport_failure_is_redacted(monkeypatch) -> None:
    configure(monkeypatch, transport=SimpleNamespace(doc=None, error="contains token", attempts=[1]))
    monkeypatch.setattr("cgkn.providers.client.provider_transport._redact", lambda error, token: "[REDACTED]")
    with pytest.raises(RuntimeError, match="REDACTED"):
        OpenAICompatibleClient().complete(system="s", user="u", schema_name="x", schema={}, config=CONFIG)


@pytest.mark.negative
def test_empty_provider_response_is_rejected(monkeypatch) -> None:
    configure(monkeypatch, text="")
    with pytest.raises(RuntimeError, match="empty"):
        OpenAICompatibleClient().complete(system="s", user="u", schema_name="x", schema={}, config=CONFIG)


@pytest.mark.roundtrip
def test_success_builds_strict_schema_payload_and_normalizes_usage(monkeypatch) -> None:
    configure(monkeypatch)
    result = OpenAICompatibleClient().complete(system="s", user="u", schema_name="shape", schema={"type": "object"}, config=CONFIG)
    assert result.text == '{"ok":true}' and result.model == "actual" and result.request_id == "req"
    assert result.usage == {"total_tokens": 3} and result.attempts == 2
    configure(monkeypatch, transport=SimpleNamespace(doc={"id": "", "model": "", "usage": []}, error="", attempts=[1]))
    fallback = OpenAICompatibleClient().complete(system="s", user="u", schema_name="shape", schema={}, config=CONFIG)
    assert fallback.model == CONFIG.model and fallback.usage == {}
