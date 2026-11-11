"""Historical import name delegating exclusively to the governed Gateway."""
import os
from typing import Any, Mapping
from .client import ModelRoleConfig, ProviderCompletion


class OpenAICompatibleClient:
    """Compatibility facade; no direct credentials, transport or retry owner."""

    def complete(self, *, system: str, user: str, schema_name: str,
                 schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        from .application_network import settings
        if settings():
            raise RuntimeError('DOMESTIC_EXPLICIT_LEGACY_CLIENT_REFUSED_USE_GATEWAY_FACTORY')
        from .gateway_client import GatewayCompletionClient, _enabled
        if not _enabled(os.environ.get('CGKN_PROVIDER_GATEWAY_ENABLED')):
            raise RuntimeError('Provider credentials are unavailable: explicit governed Gateway required')
        if not all(os.environ.get(k, '').strip() for k in (
                'CGKN_PROVIDER_GATEWAY_BASE_URL', 'CGKN_PROVIDER_GATEWAY_TOKEN')):
            raise RuntimeError('Provider credentials are unavailable')
        client=GatewayCompletionClient.from_environment()
        return client.complete(system=system,user=user,schema_name=schema_name,schema=schema,config=config)
