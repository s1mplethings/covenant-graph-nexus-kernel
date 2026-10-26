from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .client import ModelRoleConfig
from .connector_registry import supported_provider_ids


ALLOWED_PROVIDER_IDS = supported_provider_ids()


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CGKNModelRouting:
    agent: ModelRoleConfig
    worker: ModelRoleConfig
    allowed_providers: frozenset[str]
    fallback: str = "deny"
    schema_version: str = "1.0"

    @classmethod
    def load(cls, path: pathlib.Path | str) -> "CGKNModelRouting":
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("kind") != "CGKNModelRouting" or raw.get("schema_version") != "1.0":
            raise ValueError("unsupported CGKN model routing configuration")
        if set(raw) != {"kind", "schema_version", "roles", "allowed_providers", "fallback"}:
            raise ValueError("model routing configuration has unknown or missing fields")
        roles = raw.get("roles")
        if not isinstance(roles, dict) or set(roles) != {"agent", "worker"}:
            raise ValueError("model routing must define exactly agent and worker roles")
        allowed = frozenset(str(item).strip().lower() for item in raw.get("allowed_providers", ()))
        if not allowed or not allowed <= ALLOWED_PROVIDER_IDS:
            raise ValueError("model routing contains an unsupported Provider ID")
        fallback = str(raw.get("fallback", "")).strip().lower()
        if fallback != "deny":
            raise ValueError("automatic Provider fallback is forbidden")
        configs: dict[str, ModelRoleConfig] = {}
        for role in ("agent", "worker"):
            value = roles[role]
            if not isinstance(value, dict) or set(value) - {"provider_id", "timeout_seconds", "max_output_tokens", "temperature", "reasoning_effort", "thinking_mode"}:
                raise ValueError(f"invalid {role} routing fields")
            provider_id = str(value.get("provider_id", "")).strip().lower()
            if provider_id not in allowed:
                raise ValueError(f"{role} Provider ID is not allowed")
            configs[role] = ModelRoleConfig(
                role,
                provider_id,
                int(value.get("timeout_seconds", 90)),
                int(value.get("max_output_tokens", 6000)),
                float(value.get("temperature", 0.0)),
                str(value.get("reasoning_effort", "none")),
                thinking_mode=str(value.get("thinking_mode", "default")),
            )
        return cls(configs["agent"], configs["worker"], allowed, fallback)

    def as_dict(self) -> dict[str, Any]:
        def role(config: ModelRoleConfig) -> dict[str, Any]:
            return {
                "provider_id": config.model,
                "timeout_seconds": config.timeout_seconds,
                "max_output_tokens": config.max_output_tokens,
                "temperature": config.temperature,
                "reasoning_effort": config.reasoning_effort,
                "thinking_mode": config.thinking_mode,
            }

        return {
            "kind": "CGKNModelRouting",
            "schema_version": self.schema_version,
            "roles": {"agent": role(self.agent), "worker": role(self.worker)},
            "allowed_providers": sorted(self.allowed_providers),
            "fallback": self.fallback,
        }

    @property
    def config_hash(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical(self.as_dict()).encode("utf-8")).hexdigest()

    def snapshot(self, run_id: str, *, gateway_protocol: str = "openai-compatible-local-v1") -> "ModelRoutingSnapshot":
        roles = MappingProxyType({"agent": self.agent.model, "worker": self.worker.model})
        limits = MappingProxyType({
            "agent": MappingProxyType({"max_output_tokens": self.agent.max_output_tokens, "timeout_seconds": self.agent.timeout_seconds}),
            "worker": MappingProxyType({"max_output_tokens": self.worker.max_output_tokens, "timeout_seconds": self.worker.timeout_seconds}),
        })
        return ModelRoutingSnapshot(
            run_id=str(run_id),
            roles=roles,
            actual_models=MappingProxyType({"agent": "", "worker": ""}),
            gateway_protocol=gateway_protocol,
            routing_config_hash=self.config_hash,
            limits=limits,
            fallback="deny",
            created_at=datetime.now(timezone.utc).isoformat(),
        )


@dataclass(frozen=True)
class ModelRoutingSnapshot:
    run_id: str
    roles: Mapping[str, str]
    actual_models: Mapping[str, str]
    gateway_protocol: str
    routing_config_hash: str
    limits: Mapping[str, Mapping[str, int]]
    fallback: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ModelRoutingSnapshot",
            "schema_version": "1.0",
            "run_id": self.run_id,
            "roles": dict(self.roles),
            "actual_models": dict(self.actual_models),
            "gateway_protocol": self.gateway_protocol,
            "routing_config_hash": self.routing_config_hash,
            "limits": {key: dict(value) for key, value in self.limits.items()},
            "fallback": self.fallback,
            "created_at": self.created_at,
            "contains_credentials": False,
        }

    def write_once(self, path: pathlib.Path | str) -> pathlib.Path:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        return target
