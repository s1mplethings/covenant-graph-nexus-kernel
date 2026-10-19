from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def canonical_hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SupervisionMode(str, Enum):
    STREAM_AWARE = "STREAM_AWARE"
    CHUNK_AWARE = "CHUNK_AWARE"
    DEADLINE_ONLY = "DEADLINE_ONLY"


class ProgressEventType(str, Enum):
    REQUEST_CREATED = "REQUEST_CREATED"
    REQUEST_STARTED = "REQUEST_STARTED"
    CONNECTION_ESTABLISHED = "CONNECTION_ESTABLISHED"
    HEADERS_RECEIVED = "HEADERS_RECEIVED"
    FIRST_CONTENT = "FIRST_CONTENT"
    CONTENT_CHUNK = "CONTENT_CHUNK"
    STREAM_EVENT = "STREAM_EVENT"
    STRUCTURED_FRAGMENT = "STRUCTURED_FRAGMENT"
    RESPONSE_COMPLETED = "RESPONSE_COMPLETED"
    VALIDATION_STARTED = "VALIDATION_STARTED"
    VALIDATION_COMPLETED = "VALIDATION_COMPLETED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"


class SupervisorDecision(str, Enum):
    CONTINUE = "CONTINUE"
    EXTEND_DEADLINE = "EXTEND_DEADLINE"
    CANCEL_CONNECT_TIMEOUT = "CANCEL_CONNECT_TIMEOUT"
    CANCEL_FIRST_PROGRESS_TIMEOUT = "CANCEL_FIRST_PROGRESS_TIMEOUT"
    CANCEL_IDLE_TIMEOUT = "CANCEL_IDLE_TIMEOUT"
    CANCEL_PREDICTED_DEADLINE = "CANCEL_PREDICTED_DEADLINE"
    CANCEL_HARD_LIMIT = "CANCEL_HARD_LIMIT"
    COMPLETE = "COMPLETE"
    FAIL_TRANSPORT = "FAIL_TRANSPORT"


@dataclass(frozen=True)
class ProviderProgressEvent:
    event_id: str
    request_id: str
    provider_id: str
    model: str
    task_class: str
    operation: str
    event_type: ProgressEventType
    timestamp_monotonic_ms: int
    elapsed_ms: int
    bytes_received: int = 0
    total_bytes_received: int = 0
    estimated_tokens_received: int = 0
    payload_digest: str = ""
    meaningful_progress: bool = False
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        return {key: (value.value if isinstance(value, Enum) else value) for key, value in self.__dict__.items()}


@dataclass(frozen=True)
class ProviderRequestComplexity:
    system_chars: int
    user_chars: int
    schema_chars: int
    target_file_count: int
    current_source_chars: int
    failure_evidence_chars: int
    requested_output_tokens: int
    task_class: str
    provider_id: str
    actual_model: str

    def __post_init__(self) -> None:
        numeric = (self.system_chars, self.user_chars, self.schema_chars, self.target_file_count,
                   self.current_source_chars, self.failure_evidence_chars, self.requested_output_tokens)
        if any(value < 0 for value in numeric):
            raise ValueError("request complexity values cannot be negative")

    @property
    def complexity_hash(self) -> str:
        return canonical_hash(self.__dict__)


@dataclass(frozen=True)
class ProviderOperationPolicy:
    policy_id: str
    task_class: str
    operation: str
    supervision_mode: SupervisionMode
    connect_timeout_seconds: int
    first_progress_timeout_seconds: int
    idle_progress_timeout_seconds: int
    base_deadline_seconds: int
    min_deadline_seconds: int
    extension_seconds: int
    max_extensions: int
    hard_limit_seconds: int
    max_output_tokens: int
    retry_policy: str = "ACTION_POLICY_ONLY"
    backup_policy: str = "FROZEN_PLAN_ONLY"
    policy_version: str = "1.0"

    def __post_init__(self) -> None:
        values = (self.connect_timeout_seconds, self.first_progress_timeout_seconds,
                  self.idle_progress_timeout_seconds, self.base_deadline_seconds,
                  self.min_deadline_seconds, self.hard_limit_seconds, self.max_output_tokens)
        if not self.policy_id or not self.task_class or any(value <= 0 for value in values):
            raise ValueError("operation policy requires positive bounded values")
        if self.extension_seconds < 0 or self.max_extensions < 0:
            raise ValueError("operation policy extension values cannot be negative")
        if self.min_deadline_seconds > self.hard_limit_seconds or self.base_deadline_seconds > self.hard_limit_seconds:
            raise ValueError("deadline cannot exceed hard limit")

    @property
    def policy_hash(self) -> str:
        return canonical_hash(self.as_dict(include_hash=False))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {key: (item.value if isinstance(item, Enum) else item) for key, item in self.__dict__.items()}
        if include_hash:
            value["policy_hash"] = self.policy_hash
        return value


@dataclass(frozen=True)
class SupervisionReceipt:
    supervision_id: str
    request_id: str
    provider_id: str
    actual_model: str
    task_class: str
    operation: str
    policy_id: str
    policy_hash: str
    supervision_mode: SupervisionMode
    complexity_hash: str
    latency_snapshot_hash: str
    initial_deadline_seconds: int
    final_deadline_seconds: int
    hard_limit_seconds: int
    extension_count: int
    connect_elapsed_ms: int
    first_progress_ms: int
    last_progress_ms: int
    total_elapsed_ms: int
    bytes_received: int
    estimated_tokens_received: int
    termination_reason: str
    timeout_phase: str
    outcome_unknown: bool
    progress_event_count: int
    contains_credentials: bool = False
    schema_version: str = "1.0"

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(self.as_dict(include_hash=False))

    def as_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {key: (item.value if isinstance(item, Enum) else item) for key, item in self.__dict__.items()}
        if include_hash:
            value["receipt_hash"] = self.receipt_hash
        return value


@dataclass(frozen=True)
class SupervisedHttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    receipt: SupervisionReceipt

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True)
class SupervisedExecutionResult:
    decision: SupervisorDecision
    receipt: SupervisionReceipt
    progress_events: tuple[ProviderProgressEvent, ...]
    value: Any = None

