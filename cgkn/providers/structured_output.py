from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from .client import parse_json_object
from .connection_contracts import ProviderConnectionError


def canonical_validator(schema: Mapping[str, Any]):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ProviderConnectionError("SCHEMA_VALIDATOR_UNAVAILABLE", "jsonschema is required") from exc
    Draft202012Validator.check_schema(dict(schema))
    return Draft202012Validator(dict(schema))


def parse_and_validate(text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = parse_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderConnectionError("SCHEMA_FAILURE", str(exc)) from None
    errors = sorted(canonical_validator(schema).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        raise ProviderConnectionError("SCHEMA_FAILURE", errors[0].message)
    return value


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

