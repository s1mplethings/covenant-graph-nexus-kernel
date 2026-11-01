"""Explicit legacy-only compatibility. Never selected by domestic live routing."""
from scripts import check_connectivity,provider_transport
from .client import ModelRoleConfig,ProviderCompletion
from typing import Any,Mapping

class OpenAICompatibleClient:
    """Thin adapter over the repository's reviewed Provider transport and credentials."""

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        from .application_network import settings
        if settings():
            raise RuntimeError('DOMESTIC_EXPLICIT_LEGACY_CLIENT_REFUSED_USE_GATEWAY_FACTORY')
        credentials = check_connectivity._resolve_api_credentials()
        token = str(credentials.get("api_key", "")).strip()
        base_url = str(credentials.get("base_url", "")).strip()
        if not token or not base_url:
            raise RuntimeError("Provider credentials are unavailable")
        response_format = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": dict(schema)}}
        payload = check_connectivity._build_openai_compatible_payload(
            base_url,
            {"model": config.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": config.temperature, "max_tokens": config.max_output_tokens, "response_format": response_format},
            model=config.model,
            reasoning_effort=config.reasoning_effort,
        )
        endpoint = check_connectivity._openai_compatible_endpoint(base_url, model=config.model)
        transport = provider_transport.post_json_with_retry(endpoint, payload, token, config.timeout_seconds, max_attempts=3, base_delay_sec=0.5)
        if transport.doc is None:
            raise RuntimeError(provider_transport._redact(transport.error, token))
        text = check_connectivity._extract_text(transport.doc)
        if not text:
            raise RuntimeError("Provider returned an empty response")
        usage = transport.doc.get("usage", {}) if isinstance(transport.doc.get("usage"), dict) else {}
        return ProviderCompletion(text, str(transport.doc.get("model") or config.model), str(transport.doc.get("id", "")), usage, len(transport.attempts))
