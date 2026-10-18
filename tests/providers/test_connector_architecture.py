from __future__ import annotations

import pathlib

import pytest

from cgkn.providers import (
    ProviderConnectionHealth,
    ProviderConnectionSnapshot,
    ProviderConnectorRegistry,
    StructuredOutputMode,
    supported_provider_ids,
)
from cgkn.providers.connection_contracts import canonical_hash


ROOT = pathlib.Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.fault_injection, pytest.mark.security]


def test_registered_connectors_are_provider_authority() -> None:
    assert supported_provider_ids() == frozenset({"qwen", "grok", "deepseek"})
    registry = ProviderConnectorRegistry()
    with pytest.raises(ValueError, match="unregistered"):
        registry.get("unknown")


def test_common_transport_and_registry_have_no_vendor_branching() -> None:
    for relative in ("cgkn/providers/gateway_client.py", "cgkn/providers/connector_registry.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "if provider ==" not in source
        assert "elif provider ==" not in source


def test_connection_contracts_validate_serialize_and_freeze_attributes() -> None:
    with pytest.raises(ValueError, match="Provider"):
        ProviderConnectionHealth("", "public", "PASS", "PASS", "m", "m", StructuredOutputMode.NATIVE_JSON_SCHEMA, "PASS", 0, "", True)
    with pytest.raises(ValueError, match="latency"):
        ProviderConnectionHealth("fake", "public", "PASS", "PASS", "m", "m", StructuredOutputMode.NATIVE_JSON_SCHEMA, "PASS", -1, "", True)
    health = ProviderConnectionHealth(
        "fake", "public", "PASS", "PASS", "m", "m",
        StructuredOutputMode.NATIVE_JSON_SCHEMA, "PASS", 3, "", True,
        checked_at="2026-01-01T00:00:00+00:00", credential_present=True,
        workspace_configured=True, probe_steps=("catalog", "schema"),
    )
    assert health.as_dict()["probe_steps"] == ["catalog", "schema"]
    assert health.as_dict()["contains_credentials"] is False
    attributes = {"region": "test"}
    snapshot = ProviderConnectionSnapshot(
        "fake", "public", "m", StructuredOutputMode.NATIVE_JSON_OBJECT,
        "sha256:test", True, attributes,
    )
    attributes["region"] = "changed"
    assert snapshot.as_dict()["attributes"] == {"region": "test"}
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})


def test_connector_registry_normalizes_identity_and_rejects_duplicates() -> None:
    class Connector:
        provider_id = " Fake "

    connector = Connector()
    registry = ProviderConnectorRegistry((connector,))
    assert registry.provider_ids == frozenset({"fake"})
    assert registry.get(" FAKE ") is connector
    with pytest.raises(ValueError, match="unique"):
        ProviderConnectorRegistry((connector, connector))
    connector.provider_id = " "
    with pytest.raises(ValueError, match="non-empty"):
        ProviderConnectorRegistry((connector,))

