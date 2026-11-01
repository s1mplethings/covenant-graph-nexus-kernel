from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol



@dataclass(frozen=True)
class ModelRoleConfig:
    role: str
    model: str
    timeout_seconds: int = 45
    max_output_tokens: int = 2200
    temperature: float = 0.0
    reasoning_effort: str = "none"
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


@dataclass(frozen=True)
class ProviderCompletion:
    text: str
    model: str
    request_id: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 1
    routing: Mapping[str, Any] = field(default_factory=dict)
    raw_finish_reason: str | None = None


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


def __getattr__(name):
    # Import compatibility only on explicit access; keep stable historical import.
    if name=='OpenAICompatibleClient':
        from .legacy_client import OpenAICompatibleClient
        return OpenAICompatibleClient
    raise AttributeError(name)
