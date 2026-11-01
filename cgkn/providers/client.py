from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Protocol



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
    thinking_mode: str = "default"
    model_id: str | None = None

    def __post_init__(self) -> None:
        if self.model_id is not None and (not isinstance(self.model_id, str) or not self.model_id.strip() or len(self.model_id) > 200):
            raise ValueError("invalid concrete model identity")
        if self.role not in {"agent", "worker"} or not self.model.strip():
            raise ValueError("model role and model are required")
        if not 1 <= int(self.timeout_seconds) <= 600:
            raise ValueError("model timeout must be between 1 and 600 seconds")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("model output limit must be a positive integer; model-specific capacity is enforced by the sourced envelope/provider")
        if not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("model temperature must be between 0 and 2")
        if not self.task_class.strip() or not self.operation.strip():
            raise ValueError("provider task class and operation are required")
        if self.outer_deadline_seconds < 0 or self.deadline_reserve_seconds < 0:
            raise ValueError("provider deadline values must be non-negative")
        if self.outer_deadline_seconds and self.outer_deadline_seconds <= self.deadline_reserve_seconds:
            raise ValueError("outer deadline must exceed its reserve")
        if self.thinking_mode not in {"default", "enabled", "disabled"}:
            raise ValueError("thinking mode must be default, enabled, or disabled")


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    model: str
    request_id: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 1
    selection_receipt: Mapping[str, Any] = field(default_factory=dict)
    transport_metadata: Mapping[str, Any] = field(default_factory=dict)
    routing: Mapping[str, Any] = field(default_factory=dict)
    raw_finish_reason: str | None = None


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


def __getattr__(name):
    # Import compatibility only on explicit access; keep stable historical import.
    if name=='OpenAICompatibleClient':
        from .legacy_client import OpenAICompatibleClient
        return OpenAICompatibleClient
    raise AttributeError(name)
