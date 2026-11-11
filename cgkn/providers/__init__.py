from .client import CompletionClient, ModelRoleConfig, ProviderCompletion, parse_json_object
from .gateway_client import GatewayCompletionClient, GatewayCompletionError, completion_client_from_environment
from .routing import ALLOWED_PROVIDER_IDS, CGKNModelRouting, ModelRoutingSnapshot

__all__ = [
    "ALLOWED_PROVIDER_IDS", "CGKNModelRouting", "CompletionClient", "GatewayCompletionClient",
    "GatewayCompletionError", "ModelRoleConfig", "ModelRoutingSnapshot", "OpenAICompatibleClient",
    "ProviderCompletion", "completion_client_from_environment", "parse_json_object",
]


def __getattr__(name):
    if name == "OpenAICompatibleClient":
        from .legacy_client import OpenAICompatibleClient
        return OpenAICompatibleClient
    raise AttributeError(name)
