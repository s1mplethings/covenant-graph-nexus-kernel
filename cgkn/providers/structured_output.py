from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .connection_contracts import ProviderConnectionError


SELECTOR_VERSION = "1.0"
DEFAULT_ENVELOPES = ("answer", "data", "result", "output", "response")


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_rejection(error: Any) -> str:
    path = "/".join(str(item) for item in error.path) or "$"
    return f"{error.validator}@{path}"


def canonical_validator(schema: Mapping[str, Any]):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ProviderConnectionError("SCHEMA_VALIDATOR_UNAVAILABLE", "jsonschema is required") from exc
    Draft202012Validator.check_schema(dict(schema))
    return Draft202012Validator(dict(schema))


@dataclass(frozen=True)
class StructuredSelectionReceipt:
    provider_id: str
    model: str
    task_class: str
    operation: str
    schema_name: str
    schema_hash: str
    prompt_hash: str
    raw_response_hash: str
    raw_length: int
    json_candidate_count: int
    schema_valid_candidate_count: int
    selected_candidate_index: int | None
    selected_candidate_hash: str | None
    envelope_detected: str | None
    normalizations: tuple[str, ...]
    candidate_rejections: tuple[str, ...]
    transport_attempts: int
    elapsed_ms: int
    usage_status: str
    final_status: str
    configured_timeout_seconds: int = 0
    effective_request_timeout_seconds: int = 0
    remaining_outer_seconds: int = 0
    max_output_tokens: int = 0
    logical_call_number: int = 1
    response_headers_received: bool = False
    finish_reason: str = ""
    transport_status: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    api_lab_commit: str = ""
    api_lab_contract_version: str = ""
    route_mode: str = ""
    request_id: str = ""
    thinking_mode: str = "default"
    reasoning_effort: str = "none"
    reasoning_tokens: int | None = None
    reasoning_text_present: bool = False
    reasoning_text_length: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    selector_version: str = SELECTOR_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGKNStructuredSelectionReceipt", "schema_version": "1.0",
            "selector_version": self.selector_version, "provider_id": self.provider_id,
            "model": self.model, "task_class": self.task_class, "operation": self.operation,
            "schema_name": self.schema_name, "schema_hash": self.schema_hash,
            "prompt_hash": self.prompt_hash, "raw_response_hash": self.raw_response_hash,
            "raw_length": self.raw_length, "json_candidate_count": self.json_candidate_count,
            "schema_valid_candidate_count": self.schema_valid_candidate_count,
            "selected_candidate_index": self.selected_candidate_index,
            "selected_candidate_hash": self.selected_candidate_hash,
            "envelope_detected": self.envelope_detected, "normalizations": list(self.normalizations),
            "candidate_rejections": list(self.candidate_rejections),
            "transport_attempts": self.transport_attempts, "elapsed_ms": self.elapsed_ms,
            "usage_status": self.usage_status, "final_status": self.final_status,
            "configured_timeout_seconds": self.configured_timeout_seconds,
            "effective_request_timeout_seconds": self.effective_request_timeout_seconds,
            "remaining_outer_seconds": self.remaining_outer_seconds,
            "max_output_tokens": self.max_output_tokens,
            "logical_call_number": self.logical_call_number,
            "response_headers_received": self.response_headers_received,
            "finish_reason": self.finish_reason,
            "transport_status": self.transport_status,
            "usage": dict(self.usage),
            "api_lab_commit": self.api_lab_commit,
            "api_lab_contract_version": self.api_lab_contract_version,
            "route_mode": self.route_mode,
            "request_id": self.request_id,
            "thinking_mode": self.thinking_mode,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_tokens": self.reasoning_tokens,
            "reasoning_text_present": self.reasoning_text_present,
            "reasoning_text_length": self.reasoning_text_length,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cached_tokens": self.cached_tokens,
            "contains_credentials": False,
        }


class StructuredSelectionError(ValueError):
    def __init__(self, status: str, receipt: StructuredSelectionReceipt):
        self.status = status
        self.receipt = receipt
        super().__init__(status)


def _strip_single_fence(text: str) -> tuple[str, tuple[str, ...]]:
    candidate = text.strip()
    lines = candidate.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip(), ("markdown_json_fence_removed",)
    return candidate, ()


def _json_candidates(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    candidates: list[Any] = []
    cursor = 0
    starters = "{[\"-0123456789tfn"
    while cursor < len(text):
        while cursor < len(text) and text[cursor] not in starters:
            cursor += 1
        if cursor >= len(text):
            break
        try:
            value, consumed = decoder.raw_decode(text[cursor:])
        except json.JSONDecodeError:
            cursor += 1
            continue
        candidates.append(value)
        cursor += max(consumed, 1)
    return candidates


class StructuredAnswerSelector:
    def __init__(self, *, known_envelopes: Sequence[str] = DEFAULT_ENVELOPES):
        self.known_envelopes = tuple(dict.fromkeys(str(item) for item in known_envelopes if str(item)))

    def select(
        self, raw_text: str, schema: Mapping[str, Any], *, schema_name: str,
        provider_id: str = "", model: str = "", task_class: str = "", operation: str = "",
        prompt_hash: str = "", transport_attempts: int = 1, elapsed_ms: int = 0,
        usage_status: str = "UNREPORTED", configured_timeout_seconds: int = 0,
        effective_request_timeout_seconds: int = 0, remaining_outer_seconds: int = 0,
        max_output_tokens: int = 0, logical_call_number: int = 1,
        response_headers_received: bool = False,
        finish_reason: str = "", transport_status: str = "",
        usage: Mapping[str, Any] | None = None, api_lab_commit: str = "",
        api_lab_contract_version: str = "", route_mode: str = "",
        request_id: str = "", thinking_mode: str = "default", reasoning_effort: str = "none",
        reasoning_tokens: int | None = None, reasoning_text_present: bool = False,
        reasoning_text_length: int = 0, prompt_tokens: int | None = None,
        completion_tokens: int | None = None, total_tokens: int | None = None,
        cached_tokens: int | None = None,
    ) -> tuple[dict[str, Any], StructuredSelectionReceipt]:
        started = time.monotonic()
        raw = str(raw_text or "")
        normalized, normalizations = _strip_single_fence(raw)
        validator = canonical_validator(schema)
        decoded = _json_candidates(normalized)
        evaluated: list[tuple[Any, str | None]] = []
        for value in decoded:
            envelope = None
            candidate = value
            if isinstance(value, Mapping) and len(value) == 1:
                key = next(iter(value))
                if key in self.known_envelopes and isinstance(value[key], Mapping):
                    candidate = value[key]
                    envelope = str(key)
            evaluated.append((candidate, envelope))

        valid: list[tuple[int, dict[str, Any], str | None, str]] = []
        rejections: list[str] = []
        seen: set[str] = set()
        for index, (candidate, envelope) in enumerate(evaluated):
            if not isinstance(candidate, Mapping):
                rejections.append(f"{index}:type")
                continue
            canonical = _canonical(candidate)
            candidate_hash = _hash_bytes(canonical.encode("utf-8"))
            if candidate_hash in seen:
                rejections.append(f"{index}:duplicate")
                continue
            seen.add(candidate_hash)
            errors = sorted(validator.iter_errors(candidate), key=lambda item: (list(item.path), list(item.schema_path)))
            if errors:
                rejections.append(f"{index}:{_safe_rejection(errors[0])}")
            else:
                valid.append((index, dict(candidate), envelope, candidate_hash))

        status = "ACCEPTED" if len(valid) == 1 else "PROVIDER_SCHEMA_FAILURE" if not valid else "PROVIDER_AMBIGUOUS_STRUCTURED_OUTPUT"
        selected = valid[0] if len(valid) == 1 else None
        receipt = StructuredSelectionReceipt(
            provider_id=str(provider_id), model=str(model), task_class=str(task_class), operation=str(operation),
            schema_name=str(schema_name), schema_hash=_hash_bytes(_canonical(dict(schema)).encode("utf-8")),
            prompt_hash=str(prompt_hash), raw_response_hash=_hash_bytes(raw.encode("utf-8")), raw_length=len(raw),
            json_candidate_count=len(decoded), schema_valid_candidate_count=len(valid),
            selected_candidate_index=selected[0] if selected else None,
            selected_candidate_hash=selected[3] if selected else None,
            envelope_detected=selected[2] if selected else None,
            normalizations=normalizations + (("exact_single_key_envelope",) if selected and selected[2] else ()),
            candidate_rejections=tuple(rejections), transport_attempts=max(0, int(transport_attempts)),
            elapsed_ms=max(int(elapsed_ms), int((time.monotonic() - started) * 1000)),
            usage_status=str(usage_status), final_status=status,
            configured_timeout_seconds=max(0, int(configured_timeout_seconds)),
            effective_request_timeout_seconds=max(0, int(effective_request_timeout_seconds)),
            remaining_outer_seconds=max(0, int(remaining_outer_seconds)),
            max_output_tokens=max(0, int(max_output_tokens)), logical_call_number=max(1, int(logical_call_number)),
            response_headers_received=bool(response_headers_received),
            finish_reason=str(finish_reason), transport_status=str(transport_status),
            usage=dict(usage or {}), api_lab_commit=str(api_lab_commit),
            api_lab_contract_version=str(api_lab_contract_version), route_mode=str(route_mode),
            request_id=str(request_id), thinking_mode=str(thinking_mode),
            reasoning_effort=str(reasoning_effort), reasoning_tokens=reasoning_tokens,
            reasoning_text_present=bool(reasoning_text_present),
            reasoning_text_length=max(0, int(reasoning_text_length)),
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            total_tokens=total_tokens, cached_tokens=cached_tokens,
        )
        if selected is None:
            raise StructuredSelectionError(status, receipt)
        return selected[1], receipt


def parse_and_validate(text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value, _ = StructuredAnswerSelector().select(text, schema, schema_name="structured_result")
        return value
    except StructuredSelectionError as exc:
        raise ProviderConnectionError(exc.status, exc.status, evidence=exc.receipt.as_dict()) from None


def sanitize_vendor_text(value: Any, secrets: Iterable[str] = ()) -> str:
    text = str(value or "")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text[:1000]


def resolve_credential(environment: Mapping[str, str], primary: str, compatibility: str) -> tuple[str, bool]:
    preferred = str(environment.get(primary, "")).strip()
    legacy = str(environment.get(compatibility, "")).strip()
    if preferred and legacy and preferred != legacy:
        raise ProviderConnectionError("CONFIG_CONFLICT", f"{primary} and {compatibility} differ")
    value = preferred or legacy
    return value, bool(value)
