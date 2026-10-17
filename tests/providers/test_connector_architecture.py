from __future__ import annotations

import pathlib

import pytest

from cgkn.providers import ProviderConnectionError, ProviderConnectionHealth, ProviderConnectionSnapshot, ProviderConnectorRegistry, StructuredOutputMode, supported_provider_ids
from cgkn.providers.structured_output import parse_and_validate, resolve_credential, sanitize_vendor_text


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


def test_common_connection_contract_and_structured_helpers_cover_fail_closed_branches() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ProviderConnectionHealth("p", "PUBLIC", "PASS", "PASS", "m", "m", StructuredOutputMode.NATIVE_JSON_SCHEMA, "PASS", -1, "", True)
    with pytest.raises(ValueError, match="Provider"):
        ProviderConnectionHealth("", "PUBLIC", "PASS", "PASS", "m", "m", StructuredOutputMode.NATIVE_JSON_SCHEMA, "PASS", 0, "", True)
    health = ProviderConnectionHealth("p", "PUBLIC", "PASS", "PASS", "m", "m", StructuredOutputMode.NATIVE_JSON_SCHEMA, "PASS", 0, "", True)
    assert health.as_dict()["eligible"] is True
    snapshot = ProviderConnectionSnapshot("p", "PUBLIC", "m", StructuredOutputMode.NATIVE_JSON_SCHEMA, "sha256:x", True, {"region":"global"})
    assert snapshot.as_dict()["attributes"] == {"region":"global"}
    with pytest.raises(ProviderConnectionError, match="SCHEMA_FAILURE"):
        parse_and_validate("not-json", {"type":"object"})
    with pytest.raises(ProviderConnectionError, match="SCHEMA_FAILURE"):
        parse_and_validate('{"ok":"wrong"}', {"type":"object","properties":{"ok":{"type":"boolean"}}})
    assert sanitize_vendor_text("token other", ("token", "")) == "[REDACTED] other"
    assert resolve_credential({"NEW":"x"}, "NEW", "OLD") == ("x", True)
    assert resolve_credential({"OLD":"y"}, "NEW", "OLD") == ("y", True)
    assert resolve_credential({}, "NEW", "OLD") == ("", False)
    with pytest.raises(ProviderConnectionError, match="CONFIG_CONFLICT"):
        resolve_credential({"NEW":"x","OLD":"y"}, "NEW", "OLD")


def test_registry_rejects_empty_and_duplicate_ids_and_exposes_ids() -> None:
    class Connector:
        def __init__(self, provider_id): self.provider_id = provider_id
    with pytest.raises(ValueError, match="non-empty"):
        ProviderConnectorRegistry((Connector(""),))
    with pytest.raises(ValueError, match="unique"):
        ProviderConnectorRegistry((Connector("x"), Connector("x")))
    assert ProviderConnectorRegistry((Connector("x"),)).provider_ids == frozenset({"x"})

