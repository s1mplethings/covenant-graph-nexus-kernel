from __future__ import annotations

from types import MappingProxyType
from typing import Iterable

from .connectors.protocol import ProviderConnector


class ProviderConnectorRegistry:
    def __init__(self, connectors: Iterable[ProviderConnector] = ()) -> None:
        values: dict[str, ProviderConnector] = {}
        for connector in connectors:
            provider_id = str(connector.provider_id).strip().lower()
            if not provider_id or provider_id in values:
                raise ValueError("connector Provider IDs must be non-empty and unique")
            values[provider_id] = connector
        self._connectors = MappingProxyType(values)

    @property
    def provider_ids(self) -> frozenset[str]:
        return frozenset(self._connectors)

    def get(self, provider_id: str) -> ProviderConnector:
        normalized = str(provider_id).strip().lower()
        try:
            return self._connectors[normalized]
        except KeyError:
            raise ValueError(f"unregistered Provider connector: {normalized or '<empty>'}") from None


def supported_provider_ids() -> frozenset[str]:
    from .connectors import DeepSeekConnector, GrokConnector, QwenConnector

    return frozenset((QwenConnector.provider_id, GrokConnector.provider_id, DeepSeekConnector.provider_id))

