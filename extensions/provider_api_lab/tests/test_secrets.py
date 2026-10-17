from __future__ import annotations

import pytest

from cgkn_provider_lab.models import ProviderConfig
from cgkn_provider_lab.secrets import SecretManager, SecretUnavailable


def provider(backend: str, reference: str = "alpha") -> ProviderConfig:
    return ProviderConfig(
        provider_id="alpha",
        display_name="Alpha",
        base_url="https://example.com/v1",
        model="model-a",
        secret_backend=backend,
        secret_ref=reference,
        auth_header="" if backend == "none" else "Authorization",
    )


def test_session_secret_is_write_only_through_manager() -> None:
    manager = SecretManager.create_default()
    item = provider("session")
    manager.set_for_provider(item, "session-secret")
    assert manager.resolve(item) == "session-secret"
    manager.delete_for_provider(item)
    with pytest.raises(SecretUnavailable):
        manager.resolve(item)


def test_environment_secret_is_resolved_without_persistence(monkeypatch) -> None:
    manager = SecretManager.create_default()
    item = provider("environment", "ALPHA_API_KEY")
    monkeypatch.setenv("ALPHA_API_KEY", "env-secret")
    assert manager.resolve(item) == "env-secret"


def test_none_backend_needs_no_secret() -> None:
    manager = SecretManager.create_default()
    assert manager.resolve(provider("none", "")) == ""
