from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
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
    task_class: str = "project.domain.simple"
    operation: str = "STRUCTURED_COMPLETION"
    outer_deadline_seconds: int = 0
    deadline_reserve_seconds: int = 30

    def __post_init__(self) -> None:
        if self.role not in {"agent", "worker"} or not self.model.strip():
            raise ValueError("model role and model are required")
        if not 1 <= int(self.timeout_seconds) <= 600:
            raise ValueError("model timeout must be between 1 and 600 seconds")
        if not 1 <= int(self.max_output_tokens) <= 131_072:
            raise ValueError("model output limit must be between 1 and 131072 tokens")
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("model temperature must be between 0 and 2")
        if not self.task_class.strip() or not self.operation.strip():
            raise ValueError("provider task class and operation are required")
        if self.outer_deadline_seconds < 0 or self.deadline_reserve_seconds < 0:
            raise ValueError("provider deadline values must be non-negative")
        if self.outer_deadline_seconds and self.outer_deadline_seconds <= self.deadline_reserve_seconds:
            raise ValueError("outer deadline must exceed its reserve")


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    model: str
    request_id: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 1
    selection_receipt: Mapping[str, Any] = field(default_factory=dict)
    transport_metadata: Mapping[str, Any] = field(default_factory=dict)


class CompletionClient(Protocol):
    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion: ...


@dataclass(frozen=True)
class GenerationRequest:
    """Layer-neutral request consumed by optional generation-context adapters."""

    task_class: str
    operation: str
    project_id: str
    capability_ref: str
    provider_id: str
    system: str
    goal: Any
    contract: Any
    state: Any
    failure_evidence: Any
    schema_name: str
    schema: Mapping[str, Any]
    model_config: Any
    lesson_policy: str = "ENABLED"
    dependency_risk_policy: Any = field(default_factory=dict)
    allowed_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    run_id: str = ""
    projected_prompt: Mapping[str, Any] | None = None
    prompt_projection_hash: str = ""


@dataclass(frozen=True)
class GenerationResult:
    completion: ProviderCompletion
    lesson_snapshot_hash: str = ""
    applied_lesson_ids: tuple[str, ...] = ()
    lesson_context_chars: int = 0
    generation_context_hash: str = ""


class GenerationClient(Protocol):
    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class DirectGenerationClient:
    """Adapt the canonical CompletionClient without depending on an L6 context policy."""

    def __init__(self, client: CompletionClient):
        self.client = client

    def generate(self, request: GenerationRequest) -> GenerationResult:
        prompt = request.projected_prompt or {
            "goal": request.goal,
            "contract": request.contract,
            "current_state": request.state,
            "failure_evidence": request.failure_evidence,
            "allowed_actions": list(request.allowed_actions),
            "forbidden_actions": list(request.forbidden_actions),
        }
        completion = self.client.complete(
            system=request.system,
            user=json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            schema_name=request.schema_name,
            schema=request.schema,
            config=replace(request.model_config, task_class=request.task_class, operation=request.operation),
        )
        return GenerationResult(completion)


def as_generation_client(client: CompletionClient | GenerationClient) -> GenerationClient:
    return client if callable(getattr(client, "generate", None)) else DirectGenerationClient(client)


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
