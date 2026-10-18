from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class StructuredOutputMode(str, Enum):
    NATIVE_JSON_SCHEMA = "NATIVE_JSON_SCHEMA"
    NATIVE_JSON_OBJECT = "NATIVE_JSON_OBJECT"
    PROMPT_JSON_LOCAL_VALIDATE = "PROMPT_JSON_LOCAL_VALIDATE"


class ProviderConnectionError(RuntimeError):
    def __init__(
        self,
        error_class: str,
        message: str,
        *,
        http_status: int | None = None,
        outcome_unknown: bool = False,
        timeout_phase: str = "",
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        self.error_class = str(error_class)
        self.http_status = http_status
        self.outcome_unknown = bool(outcome_unknown)
        self.timeout_phase = str(timeout_phase)
        self.evidence = MappingProxyType(dict(evidence or {}))
        super().__init__(f"{self.error_class}: {str(message)[:1000]}")


@dataclass(frozen=True)
class ProviderConnectionHealth:
    provider_id: str
    endpoint_class: str
    auth_status: str
    catalog_status: str
    requested_model: str
    actual_model: str
    structured_output_mode: StructuredOutputMode
    structured_output_status: str
    latency_ms: int
    error_class: str
    eligible: bool
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    credential_present: bool = False
    workspace_configured: bool = False
    probe_steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.latency_ms < 0 or not self.provider_id.strip():
            raise ValueError("connection health requires a Provider and non-negative latency")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ProviderConnectionHealth",
            "schema_version": "1.0",
            "provider_id": self.provider_id,
            "endpoint_class": self.endpoint_class,
            "auth_status": self.auth_status,
            "catalog_status": self.catalog_status,
            "requested_model": self.requested_model,
            "actual_model": self.actual_model,
            "structured_output_mode": self.structured_output_mode.value,
            "structured_output_status": self.structured_output_status,
            "latency_ms": self.latency_ms,
            "error_class": self.error_class,
            "eligible": self.eligible,
            "checked_at": self.checked_at,
            "credential_present": self.credential_present,
            "workspace_configured": self.workspace_configured,
            "probe_steps": list(self.probe_steps),
            "contains_credentials": False,
        }


@dataclass(frozen=True)
class ProviderConnectionSnapshot:
    provider_id: str
    endpoint_class: str
    requested_model: str
    structured_output_mode: StructuredOutputMode
    config_hash: str
    credential_present: bool
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "ProviderConnectionSnapshot",
            "schema_version": "1.0",
            "provider_id": self.provider_id,
            "endpoint_class": self.endpoint_class,
            "requested_model": self.requested_model,
            "structured_output_mode": self.structured_output_mode.value,
            "config_hash": self.config_hash,
            "credential_present": self.credential_present,
            "attributes": dict(self.attributes),
            "contains_credentials": False,
        }


def canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()

