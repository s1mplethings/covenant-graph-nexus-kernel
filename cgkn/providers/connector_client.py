from __future__ import annotations

from typing import Any, Mapping

from .client import ModelRoleConfig, ProviderCompletion
from .connector_registry import ProviderConnectorRegistry


class ConnectorCompletionClient:
    """Canonical CompletionClient adapter over an explicit connector registry."""

    def __init__(self, registry: ProviderConnectorRegistry) -> None:
        self.registry = registry

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        return self.registry.get(config.model).complete_structured(
            system=system, user=user, schema_name=schema_name, schema=schema, config=config
        )
