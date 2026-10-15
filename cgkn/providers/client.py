from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from scripts import check_connectivity, provider_transport


@dataclass(frozen=True)
class ModelRoleConfig:
    role: str
    model: str
    timeout_seconds: int = 45
    max_output_tokens: int = 2200
    temperature: float = 0.0
    reasoning_effort: str = "none"

    def __post_init__(self) -> None:
        if self.role not in {"agent", "worker"} or not self.model.strip():
            raise ValueError("model role and model are required")


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    model: str
    request_id: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 1


class CompletionClient(Protocol):
    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion: ...


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = str(text).strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1]).strip()
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("provider response must be one JSON object")
    return value


class OpenAICompatibleClient:
    """Thin adapter over the repository's reviewed Provider transport and credentials."""

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
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
