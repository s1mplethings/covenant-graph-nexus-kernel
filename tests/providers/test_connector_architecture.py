from __future__ import annotations

import pathlib

import pytest

from cgkn.providers import ProviderConnectorRegistry, supported_provider_ids


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

