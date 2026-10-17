from __future__ import annotations

import pytest

from cgkn_provider_lab.models import ConfigurationError, ProviderConfig


def make_provider(**overrides):
    values = {
        "provider_id": "test",
        "display_name": "Test",
        "base_url": "https://example.com/v1",
        "model": "model-a",
        "secret_backend": "environment",
        "secret_ref": "TEST_API_KEY",
    }
    values.update(overrides)
    return ProviderConfig(**values)


def test_provider_serialization_contains_reference_but_never_value() -> None:
    provider = make_provider()
    payload = provider.to_dict()
    assert payload["secret_ref"] == "TEST_API_KEY"
    assert "api_key" not in payload
    assert "secret" not in payload
    assert "token" not in payload


def test_public_metadata_omits_secret_location() -> None:
    payload = make_provider().public_dict()
    assert "secret_ref" not in payload
    assert "secret_backend" not in payload
    assert "auth_header" not in payload


@pytest.mark.parametrize("field", ["api_key", "token", "password", "secret"])
def test_plaintext_credential_fields_are_rejected(field: str) -> None:
    raw = make_provider().to_dict()
    raw[field] = "do-not-store-me"
    with pytest.raises(ConfigurationError, match="plaintext credential"):
        ProviderConfig.from_dict(raw)


def test_non_local_http_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="HTTPS"):
        make_provider(base_url="http://example.com/v1")


def test_local_http_is_allowed() -> None:
    provider = make_provider(
        base_url="http://127.0.0.1:8000/v1",
        secret_backend="none",
        secret_ref="",
        auth_header="",
    )
    assert provider.base_url.startswith("http://127.0.0.1")


def test_session_reference_cannot_hide_a_plaintext_key() -> None:
    with pytest.raises(ConfigurationError, match="must equal provider_id"):
        make_provider(secret_backend="session", secret_ref="not-the-provider-id")


def test_auth_metadata_is_allowlisted() -> None:
    with pytest.raises(ConfigurationError, match="auth_prefix"):
        make_provider(auth_prefix="Bearer embedded-secret")
    with pytest.raises(ConfigurationError, match="auth_header"):
        make_provider(auth_header="X-Custom-Secret")
